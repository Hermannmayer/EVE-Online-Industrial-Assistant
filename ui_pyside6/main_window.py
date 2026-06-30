"""
主窗口 — QMainWindow + 导航树 + 内容区 + 状态栏
"""

import json
import os
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUBS
from core.container import get_container
from core.paths import (
    ensure_dirs_exist,
    search_history_file,
    window_geometry_file,
)

# ── 导航树节点定义 ──
# 格式: ("key", "标签", "图标") — 导航项，可点击
#        ("key", "标签", "图标", True) — 即将推出的导航项（Coming Soon，灰色不可点击）
#        ("__section__", "分组名称") — 分组标题（不可点击）
NAV_TREE = [
    ("__section__", "⚡ 核心功能"),
    ("estimate", "估价", "💰"),
    ("query", "物品查询", "🔍"),
    ("industry", "工业制造", "🏭"),
    ("trade", "市场贸易", "📊"),
    ("watchlist", "价格监控", "🔔"),
    ("contract", "合同市场", "📄"),
    ("storage", "仓库管理", "📦"),
]


class PriceUpdateWorker(QThread):
    """后台线程执行价格更新"""

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, regions: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._regions = regions

    def run(self):
        try:
            from services.workers.getprices import run_price_update

            run_price_update(self._regions)
            self.finished_signal.emit(True, "价格更新完成")
        except Exception as ex:
            self.finished_signal.emit(False, str(ex))


class PriceCheckWorker(QThread):
    """后台线程检查价格数据时效"""

    result = Signal(bool, str)  # needs_update, status_text

    def __init__(self, interval_minutes: int = 30, parent=None):
        super().__init__(parent)
        self._interval = interval_minutes * 60

    def run(self):
        try:
            conn = get_container().db.direct_connect("mkt")
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                diff = (now_utc - dt).total_seconds()
                if diff > self._interval:
                    self.result.emit(True, f"价格数据已过期 {diff / 60:.0f} 分钟，需要更新")
                else:
                    self.result.emit(False, f"价格数据 {(diff / 60):.0f} 分钟前更新，无需更新")
            else:
                self.result.emit(True, "无价格数据，需要更新")
        except Exception as ex:
            self.result.emit(False, f"价格检查失败: {ex}")


class MainWindow(QMainWindow):
    """EVE 商人助手主窗口"""

    def __init__(self):
        super().__init__()

        theme.set_geometry_file(window_geometry_file())
        ensure_dirs_exist()

        self.setWindowTitle("EVE 商人助手")
        self.setMinimumSize(1200, 700)

        # ── 主题 ──
        self.setStyleSheet(theme.get_stylesheet())
        # 加载上次主题偏好（theme.apply_theme 会触发 _on_theme_changed 重设样式表）
        saved_theme = theme.load_theme_preference()
        if saved_theme != "dark":
            theme.apply_theme(saved_theme)

        # ── 顶部工具栏 ──
        toolbar = QToolBar("主工具栏")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))

        self._region_combo = QComboBox()
        self._region_combo.addItems(TRADE_HUBS + ["全部区域"])
        self._region_combo.setCurrentText("全部区域")
        self._region_combo.setFixedWidth(120)
        self._region_combo.currentTextChanged.connect(self._on_region_changed)
        toolbar.addWidget(QLabel("  区域: "))
        toolbar.addWidget(self._region_combo)
        toolbar.addSeparator()

        self._update_btn = QToolButton()
        self._update_btn.setText("↻ 更新价格")
        self._update_btn.setObjectName("toolbar_update_btn")
        self._update_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._update_btn.setMenu(self._build_update_menu())
        self._update_btn.clicked.connect(self._trigger_price_update)
        toolbar.addWidget(self._update_btn)

        self._price_age_label = QLabel("⏳ 价格: —")
        self._price_age_label.setObjectName("price_age_label")
        self._price_age_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: 0 8px;")
        toolbar.addWidget(self._price_age_label)

        toolbar.addSeparator()

        self._item_count_label = QLabel("物品: —")
        self._item_count_label.setObjectName("item_count_label")
        self._item_count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: 0 8px;")
        toolbar.addWidget(self._item_count_label)

        self.addToolBar(toolbar)

        # ── 状态栏（精简） ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("status_label")

        self._update_progress = QProgressBar()
        self._update_progress.setFixedWidth(160)
        self._update_progress.setFixedHeight(16)
        self._update_progress.setVisible(False)

        self._status_info_label = QLabel("")
        self._status_info_label.setObjectName("status_info_label")

        self.status_bar.addWidget(self._status_label, 1)
        self.status_bar.addWidget(self._update_progress)
        self.status_bar.addPermanentWidget(self._status_info_label)

        # ── 中央布局 ──
        central = QWidget()
        central.setObjectName("central_widget")
        self.setCentralWidget(central)

        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)

        # ── 左侧导航 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        nav_panel = self._build_nav_tree()
        nav_panel.setFixedWidth(160)
        splitter.addWidget(nav_panel)

        # ── 内容区 ──
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("content_stack")
        splitter.addWidget(self.content_stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        h_layout.addWidget(splitter)

        # ── 页面注册 ──
        self._pages = {}
        self._register_pages()

        # ── 默认显示查询页 ──
        self._nav_tree.setCurrentItem(self._nav_items[0])
        self.content_stack.setCurrentIndex(0)

        # ── 窗口位置恢复 ──
        theme.restore_window_geometry(self)

        # ── 初始化定时器：价格检查 ──
        self._price_worker: PriceUpdateWorker | None = None
        self._update_regions: list[str] = list(TRADE_HUBS)
        self._update_interval_minutes = self._load_interval()
        self._auto_update_enabled = self._load_auto_update()
        self._price_timer: QTimer | None = None
        self._init_price_check()

        # ── 启动周期性价格定时器 ──
        if self._auto_update_enabled and self._update_interval_minutes > 0:
            self._start_price_timer()

        # ── 主题切换监听 ──
        theme.add_theme_listener(self._on_theme_changed)

        # ── 首次启动检测 ──
        QTimer.singleShot(500, self._check_first_run)

    def show_progress(self, text: str = "", maximum: int = 0):
        """显示进度条（0=不确定模式）"""
        self._status_label.setText(text or "处理中...")
        self._update_progress.setVisible(True)
        if maximum > 0:
            self._update_progress.setRange(0, maximum)
            self._update_progress.setValue(0)
        else:
            self._update_progress.setRange(0, 0)

    def update_progress(self, value: int, text: str = ""):
        """更新进度条"""
        self._update_progress.setValue(value)
        if text:
            self._status_label.setText(text)

    def hide_progress(self, text: str = "就绪"):
        """隐藏进度条"""
        self._update_progress.setVisible(False)
        self._update_progress.setRange(0, 100)
        self._status_label.setText(text)

    def closeEvent(self, event):
        theme.remove_theme_listener(self._on_theme_changed)
        theme.save_window_geometry(self)
        # 关闭独立的全物品窗口
        for w in QApplication.topLevelWidgets():
            from ui_pyside6.views.all_items_view import AllItemsDialog

            if isinstance(w, AllItemsDialog) and w.isVisible():
                w.close()
        # 等待后台线程安全退出
        for attr in ("_check_worker", "_price_worker"):
            worker = getattr(self, attr, None)
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)

    # ═══════════════════════════════════════
    #  导航树
    # ═══════════════════════════════════════

    def _build_nav_tree(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("nav_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(0)

        tree = QTreeWidget()
        tree.setObjectName("nav_tree")
        tree.setHeaderHidden(True)
        tree.setIndentation(0)
        tree.setRootIsDecorated(False)

        self._nav_tree = tree
        self._nav_items: list[QTreeWidgetItem] = []

        # ── 标题 ──
        header = QTreeWidgetItem(["EVE 商人助手"])
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        font = header.font(0)
        font.setBold(True)
        font.setPointSize(12)
        header.setFont(0, font)
        header.setForeground(0, QColor(theme.PRIMARY))
        header.setSizeHint(0, QSize(header.sizeHint(0).width(), 32))
        tree.addTopLevelItem(header)

        spacer = QTreeWidgetItem([""])
        spacer.setFlags(Qt.ItemFlag.NoItemFlags)
        spacer.setSizeHint(0, QSize(spacer.sizeHint(0).width(), 8))
        tree.addTopLevelItem(spacer)

        for entry in NAV_TREE:
            if entry[0] == "__section__":
                # ── 分组标题 ──
                sec = QTreeWidgetItem([entry[1]])
                sec.setFlags(Qt.ItemFlag.NoItemFlags)
                sec.setForeground(0, QColor(theme.TEXT_SECONDARY))
                f = sec.font(0)
                f.setBold(True)
                f.setPointSize(10)
                sec.setFont(0, f)
                sec.setSizeHint(0, QSize(sec.sizeHint(0).width(), 24))
                tree.addTopLevelItem(sec)
            else:
                key, label, icon = entry[0], entry[1], entry[2]

                item = QTreeWidgetItem([f" {icon}  {label}"])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setSizeHint(0, QSize(item.sizeHint(0).width(), 28))
                self._nav_items.append(item)
                tree.addTopLevelItem(item)

        tree.currentItemChanged.connect(self._on_nav_changed)
        layout.addWidget(tree)

        # ── 底部设置按钮 ──
        layout.addStretch()

        bottom_btn_layout = QHBoxLayout()
        bottom_btn_layout.setContentsMargins(4, 4, 4, 4)
        bottom_btn_layout.setSpacing(6)

        self._char_settings_btn = QPushButton()
        self._char_settings_btn.setObjectName("char_settings_btn")
        self._char_settings_btn.setToolTip("人物设置")
        self._char_settings_btn.setFixedSize(36, 36)
        self._char_settings_btn.setIcon(self._create_person_icon())
        self._char_settings_btn.setIconSize(QSize(20, 20))
        self._char_settings_btn.clicked.connect(self._show_char_settings)

        self._sys_settings_btn = QPushButton()
        self._sys_settings_btn.setObjectName("sys_settings_btn")
        self._sys_settings_btn.setToolTip("系统设置")
        self._sys_settings_btn.setFixedSize(36, 36)
        self._sys_settings_btn.setIcon(self._create_settings_icon())
        self._sys_settings_btn.setIconSize(QSize(20, 20))
        self._sys_settings_btn.clicked.connect(self._show_sys_settings)

        bottom_btn_layout.addStretch()
        bottom_btn_layout.addWidget(self._char_settings_btn)
        bottom_btn_layout.addWidget(self._sys_settings_btn)

        layout.addLayout(bottom_btn_layout)

        return panel

    def _on_nav_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key is None:
            return

        page = self._pages.get(key)
        if page and self.content_stack.indexOf(page) >= 0:
            self.content_stack.setCurrentWidget(page)
            # 页面切换时更新状态栏
            if hasattr(page, "update_status_bar"):
                page.update_status_bar()

    # ═══════════════════════════════════════
    #  页面注册
    # ═══════════════════════════════════════

    def _register_pages(self):
        from ui_pyside6.views.contract_view import ContractPage
        from ui_pyside6.views.estimate_view import EstimatePage
        from ui_pyside6.views.industry_view import IndustryPage
        from ui_pyside6.views.inventory_view import InventoryPage
        from ui_pyside6.views.query_view import QueryPage
        from ui_pyside6.views.trade_view import TradePage
        from ui_pyside6.views.watchlist_view import WatchlistPage

        # 已实现的页面
        self._pages["estimate"] = EstimatePage(self)
        self._pages["query"] = QueryPage(self)
        self._pages["industry"] = IndustryPage(self)
        self._pages["trade"] = TradePage(self)
        self._pages["watchlist"] = WatchlistPage(self)
        self._pages["contract"] = ContractPage(self)
        self._pages["storage"] = InventoryPage(self)

        for key in ["estimate", "query", "industry", "trade", "watchlist", "contract", "storage"]:
            self.content_stack.addWidget(self._pages[key])

    # ═══════════════════════════════════════
    #  价格更新
    # ═══════════════════════════════════════

    def _init_price_check(self):
        self._check_worker = PriceCheckWorker(self._update_interval_minutes, self)
        self._check_worker.result.connect(self._on_price_check_done)
        self._check_worker.start()

    def _on_price_check_done(self, needs_update: bool, status_text: str):
        self._status_label.setText(status_text)
        self._refresh_price_age()
        self._refresh_item_count()
        if needs_update:
            if self._auto_update_enabled:
                self._status_label.setText("正在自动更新价格...")
                QTimer.singleShot(1000, self._trigger_price_update)
            else:
                self._status_label.setText("价格数据需要更新（自动更新已关闭）")

    def _trigger_price_update(self):
        if self._price_worker and self._price_worker.isRunning():
            self._status_label.setText("价格更新已在运行中")
            return

        self._update_progress.setVisible(True)
        self._update_progress.setRange(0, 0)  # indeterminate

        regions = None if set(self._update_regions) == set(TRADE_HUBS) else self._update_regions
        if regions:
            self._status_label.setText(f"正在更新 {', '.join(regions)}...")
        else:
            self._status_label.setText("正在从 ESI 获取市场价格...")

        self._price_worker = PriceUpdateWorker(regions, self)
        self._price_worker.finished_signal.connect(self._on_price_update_done)
        self._price_worker.start()

    def _build_update_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("sys_menu")
        self._region_actions = {}
        for name in TRADE_HUBS:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(lambda n=name: self._on_region_toggle(n))
            self._region_actions[name] = action
            menu.addAction(action)
        return menu

    def _on_region_toggle(self, name: str):
        action = self._region_actions.get(name)
        if not action:
            return
        if action.isChecked():
            if name not in self._update_regions:
                self._update_regions.append(name)
        elif name in self._update_regions:
            self._update_regions.remove(name)

        all_selected = set(self._update_regions) == set(TRADE_HUBS)
        if all_selected:
            self._update_btn.setText("更新价格")
        elif self._update_regions:
            self._update_btn.setText(f"更新 {', '.join(self._update_regions)}")
        else:
            self._update_btn.setText("更新价格（无选中）")

    def _on_price_update_done(self, success: bool, message: str):
        self._update_progress.setVisible(False)
        self._update_progress.setRange(0, 100)

        if success:
            self._status_info_label.setText("价格更新完成")
            self._refresh_price_age()
            self._refresh_item_count()
            page = self._pages.get("query")
            if page and hasattr(page, "refresh_display"):
                page.refresh_display()
        else:
            self._status_info_label.setText(f"价格更新失败: {message}")

    def _refresh_price_age(self):
        """刷新工具栏上的价格年龄标签 + 状态栏信息"""
        try:
            conn = get_container().db.direct_connect("mkt")
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                try:
                    dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    diff_sec = (now_utc - dt).total_seconds()
                    diff_min = int(diff_sec / 60)

                    if diff_min < 10:
                        color = theme.GREEN
                        age_text = f"🟢 {diff_min} 分钟前"
                    elif diff_min < 30:
                        color = theme.ACCENT_YELLOW
                        age_text = f"🟡 {diff_min} 分钟前"
                    else:
                        color = theme.ACCENT_RED
                        age_text = f"🔴 {diff_min} 分钟前"

                    bj_dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=8)
                    bj_str = bj_dt.strftime("%H:%M")
                    self._price_age_label.setText(f"⏳ 价格: {age_text} ({bj_str})")
                    self._price_age_label.setStyleSheet(f"color: {color}; padding: 0 8px;")
                    self._status_info_label.setText(f"价格: {bj_str} | {age_text}")
                except Exception:
                    self._price_age_label.setText("⏳ 价格: 解析异常")
            else:
                self._price_age_label.setText("⏳ 价格: 暂无数据")
                self._price_age_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: 0 8px;")
                self._status_info_label.setText("价格: 暂无数据")
        except Exception:
            self._price_age_label.setText("⏳ 价格: 数据库未就绪")

    def _refresh_item_count(self):
        """刷新工具栏上的物品总数"""
        try:
            conn = get_container().db.direct_connect("ref")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM item")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                count = row[0]
                if count >= 10000:
                    self._item_count_label.setText(f"物品: {count // 10000} 万+")
                else:
                    self._item_count_label.setText(f"物品: {count}")
        except Exception:
            self._item_count_label.setText("物品: —")

    def _on_region_changed(self, region: str):
        """工具栏区域选择变更"""
        if region == "全部区域":
            self._update_regions = ["Jita", "Amarr", "Dodixie", "Rens"]
            self._update_btn.setText("↻ 更新价格")
        else:
            self._update_regions = [region]
            self._update_btn.setText(f"↻ 更新 {region}")
        self._status_info_label.setText(f"区域: {region}")

    # ═══════════════════════════════════════
    #  其他事件
    # ═══════════════════════════════════════

    # ── 图标绘制 ──

    def _create_person_icon(self, size: int = 20) -> QIcon:
        """绘制人物剪影图标"""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.TEXT_SECONDARY))
        # 头（圆形）
        head_radius = size * 0.16
        cx, cy = size / 2, size * 0.28
        painter.drawEllipse(int(cx - head_radius), int(cy - head_radius), int(head_radius * 2), int(head_radius * 2))
        # 身体（梯形）
        body = QPainterPath()
        body_w = size * 0.3
        body_top_y = size * 0.44
        body_bot_y = size * 0.88
        body.moveTo(cx - body_w * 0.7, body_bot_y)
        body.lineTo(cx + body_w * 0.7, body_bot_y)
        body.lineTo(cx + body_w * 0.5, body_top_y)
        body.lineTo(cx - body_w * 0.5, body_top_y)
        body.closeSubpath()
        painter.drawPath(body)
        painter.end()
        return QIcon(pixmap)

    def _create_settings_icon(self, size: int = 20) -> QIcon:
        """绘制齿轮/设置图标"""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.TEXT_SECONDARY), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = size / 2, size / 2
        outer_r = size * 0.38
        inner_r = size * 0.22

        # 外圈 + 内圈
        painter.drawEllipse(int(cx - outer_r), int(cy - outer_r), int(outer_r * 2), int(outer_r * 2))
        painter.drawEllipse(int(cx - inner_r), int(cy - inner_r), int(inner_r * 2), int(inner_r * 2))

        # 4个辐条
        import math

        for angle_deg in (0, 45, 90, 135):
            rad = math.radians(angle_deg)
            x1 = cx + inner_r * math.cos(rad)
            y1 = cy + inner_r * math.sin(rad)
            x2 = cx + outer_r * math.cos(rad)
            y2 = cy + outer_r * math.sin(rad)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        painter.end()
        return QIcon(pixmap)

    # ── 主题切换 ──

    def _on_theme_changed(self):
        """主题切换后的 UI 刷新"""
        self.setStyleSheet(theme.get_stylesheet())
        # 非 QSS 项：图标颜色
        self._char_settings_btn.setIcon(self._create_person_icon())
        self._sys_settings_btn.setIcon(self._create_settings_icon())

    def _toggle_theme(self):
        """在暗色/亮色模式间切换"""
        new_theme = "light" if theme.current_theme() == "dark" else "dark"
        theme.apply_theme(new_theme)

    # ── 事件处理 ──

    def _show_char_settings(self):
        from ui_pyside6.views.char_settings_view import CharSettingsDialog

        dialog = CharSettingsDialog(self)
        dialog.exec()

    def _show_sys_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("系统设置")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # ── 主题切换 ──
        theme_group = QGroupBox("外观")
        tg = QVBoxLayout(theme_group)
        current = theme.current_theme()
        theme_btn = QPushButton("☀️ 切换到亮色模式" if current == "dark" else "🌙 切换到暗色模式")
        theme_btn.clicked.connect(lambda: (self._toggle_theme(), dlg.accept()))
        tg.addWidget(theme_btn)
        layout.addWidget(theme_group)

        # ── 价格自动更新 ──
        price_group = QGroupBox("价格更新")
        pg = QVBoxLayout(price_group)

        auto_row = QHBoxLayout()
        self._auto_update_cb = QCheckBox("启用自动更新")
        self._auto_update_cb.setChecked(self._auto_update_enabled)
        self._auto_update_cb.toggled.connect(self._on_auto_update_toggled)
        auto_row.addWidget(self._auto_update_cb)
        auto_row.addStretch()
        pg.addLayout(auto_row)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("更新间隔（分钟）:"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 1440)
        self._interval_spin.setValue(self._update_interval_minutes)
        self._interval_spin.setSingleStep(5)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.setSpecialValueText("关闭")
        interval_row.addWidget(self._interval_spin)
        pg.addLayout(interval_row)

        layout.addWidget(price_group)

        # ── 工具 ──
        tool_group = QGroupBox("工具")
        tgl = QVBoxLayout(tool_group)
        init_btn = QPushButton("📦 数据初始化")
        init_btn.clicked.connect(lambda: (dlg.accept(), self._show_init_wizard()))
        tgl.addWidget(init_btn)
        about_btn = QPushButton("ℹ️ 关于")
        about_btn.clicked.connect(lambda: (dlg.accept(), self._show_about()))
        tgl.addWidget(about_btn)
        layout.addWidget(tool_group)

        # ── 按钮 ──
        btn_bar = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_bar.accepted.connect(dlg.accept)
        btn_bar.accepted.connect(self._on_settings_saved)
        layout.addWidget(btn_bar)

        dlg.exec()

    def _on_auto_update_toggled(self, checked: bool):
        self._auto_update_enabled = checked
        if checked and self._update_interval_minutes > 0:
            self._start_price_timer()
        else:
            self._stop_price_timer()

    def _on_settings_saved(self):
        self._update_interval_minutes = self._interval_spin.value()
        self._auto_update_enabled = self._auto_update_cb.isChecked()
        self._save_settings()
        if self._auto_update_enabled:
            self._start_price_timer()
        else:
            self._stop_price_timer()
        self._status_label.setText(f"设置已保存（间隔: {self._update_interval_minutes} 分钟）")

    def _load_interval(self) -> int:
        try:
            p = search_history_file().replace("search_history", "settings")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    val = json.load(f).get("update_interval", 30)
                    return max(0, min(1440, int(val)))
        except Exception as e:
            self._status_label.setText(f"加载设置失败: {e}")
        return 30

    def _load_auto_update(self) -> bool:
        try:
            p = search_history_file().replace("search_history", "settings")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return json.load(f).get("auto_update_enabled", True)
        except Exception:
            pass
        return True

    def _save_settings(self):
        try:
            p = search_history_file().replace("search_history", "settings")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {}
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            data["update_interval"] = self._update_interval_minutes
            data["auto_update_enabled"] = self._auto_update_enabled
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._status_label.setText(f"保存设置失败: {e}")

    def _start_price_timer(self):
        if self._price_timer is not None:
            self._price_timer.stop()
        if self._update_interval_minutes <= 0:
            return
        self._price_timer = QTimer(self)
        self._price_timer.timeout.connect(self._init_price_check)
        self._price_timer.start(self._update_interval_minutes * 60 * 1000)

    def _stop_price_timer(self):
        if self._price_timer is not None:
            self._price_timer.stop()
            self._price_timer = None

    def _check_first_run(self):
        """首次启动检测：如果缺少关键数据，在状态栏提示"""
        from services.init_check import check_all

        status = check_all()
        has_items = status.get("items", False)
        missing = sum(1 for v in status.values() if not v)
        if not has_items:
            self._status_label.setText("⚠️ 首次使用？请打开 ⚙️ → 数据初始化")
        elif missing > 0:
            self._status_label.setText(f"⚠️ {missing} 项数据未初始化，点击 ⚙️ → 数据初始化")
        else:
            self._status_label.setText("就绪")

    def _show_settings(self):
        QMessageBox.information(self, "设置", "设置功能将在后续版本实现。\n\n可配置项：ESI 区域、字体大小、主题切换")

    def _show_init_wizard(self):
        from ui_pyside6.views.init_wizard import InitWizard

        try:
            if hasattr(self, "_init_wizard") and self._init_wizard and self._init_wizard.isVisible():
                self._init_wizard.raise_()
                return
        except RuntimeError:
            pass  # C++ 对象已被删除
        self._init_wizard = InitWizard(self, on_done=self._check_first_run)
        self._init_wizard.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._init_wizard.show()

    def _show_about(self):
        QMessageBox.about(
            self,
            "关于 EVE 商人助手",
            "EVE 商人助手 v2.0\n\n"
            "基于 PySide6 重构\n"
            "为 EVE Online 玩家提供工业制造、市场贸易辅助工具。\n\n"
            "数据来源: EVE Swagger Interface (ESI)\n"
            "© 2026",
        )

    def _refresh_current_page(self):
        current = self.content_stack.currentWidget()
        if current and hasattr(current, "refresh_display"):
            current.refresh_display()
            self._status_label.setText("页面已刷新")

    def _open_all_items(self):
        from ui_pyside6.views.all_items_view import AllItemsDialog

        if not hasattr(self, "_all_items_dialog") or self._all_items_dialog is None:
            self._all_items_dialog = AllItemsDialog(self)
        self._all_items_dialog.show()
        self._all_items_dialog.raise_()

    def refresh_price_time(self):
        self._refresh_price_age()

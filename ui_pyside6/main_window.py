"""
主窗口 — QMainWindow + 导航树 + 内容区 + 状态栏
"""
import sys
import os
import sqlite3
import asyncio
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTreeWidget, QTreeWidgetItem,
    QStackedWidget, QStatusBar, QLabel,
    QHBoxLayout, QVBoxLayout, QSplitter, QPushButton,
    QMessageBox, QProgressBar, QApplication, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtGui import QColor

from core.paths import (
    DB_PATH, ICON_DIR, ensure_dirs_exist,
    progress_file, window_geometry_file,
)
from ui_pyside6.theme import (
    get_stylesheet, save_window_geometry, restore_window_geometry,
    set_geometry_file, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY,
    BG_DARK, BORDER,
)

# ── 导航树节点定义 ──
NAV_TREE = [
    ("query",   "物品查询",   "🔍"),
    ("industry","工业制造",   "🏭"),
    ("trade",   "市场贸易",   "📊"),
    ("storage", "我的仓库",   "📦"),
]

SEPARATOR = object()


class PriceUpdateWorker(QThread):
    """后台线程执行价格更新"""
    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from services.workers.getprices import run_price_update
            run_price_update()
            self.finished_signal.emit(True, "价格更新完成")
        except Exception as ex:
            self.finished_signal.emit(False, str(ex))


class PriceCheckWorker(QThread):
    """后台线程检查价格数据时效"""
    result = Signal(bool, str)  # needs_update, status_text

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                diff = (now_utc - dt).total_seconds()
                if diff > 1800:
                    self.result.emit(True, f"价格数据已过期 {diff/60:.0f} 分钟，需要更新")
                else:
                    self.result.emit(False, f"价格数据 {(diff/60):.0f} 分钟前更新，无需更新")
            else:
                self.result.emit(True, "无价格数据，需要更新")
        except Exception as ex:
            self.result.emit(False, f"价格检查失败: {ex}")


class MainWindow(QMainWindow):
    """EVE 商人助手主窗口"""

    def __init__(self):
        super().__init__()

        set_geometry_file(window_geometry_file())
        ensure_dirs_exist()

        self.setWindowTitle("EVE 商人助手")
        self.setMinimumSize(1200, 700)

        # ── 主题 ──
        self.setStyleSheet(get_stylesheet())

        # ── 状态栏 ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._price_time_label = QLabel("价格更新时间: —")
        self._price_time_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; padding-right: 16px;")

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")

        self._update_progress = QProgressBar()
        self._update_progress.setFixedWidth(160)
        self._update_progress.setFixedHeight(4)
        self._update_progress.setVisible(False)

        self._update_btn = QPushButton("更新价格")
        self._update_btn.setFixedHeight(22)
        self._update_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                padding: 2px 10px;
            }}
            QPushButton:hover {{ background-color: #ff5a75; }}
            QPushButton:disabled {{ background-color: #555; }}
        """)
        self._update_btn.clicked.connect(self._trigger_price_update)

        self.status_bar.addWidget(self._price_time_label, 1)
        self.status_bar.addWidget(self._update_progress)
        self.status_bar.addPermanentWidget(self._update_btn)
        self.status_bar.addPermanentWidget(self._status_label)

        # ── 中央布局 ──
        central = QWidget()
        central.setStyleSheet(f"background-color: {BG_DARK};")
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
        self.content_stack.setStyleSheet(f"background-color: {BG_DARK};")
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
        restore_window_geometry(self)

        # ── 初始化定时器：价格检查 ──
        self._price_worker: PriceUpdateWorker | None = None
        self._init_price_check()

    def closeEvent(self, event):
        save_window_geometry(self)
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
        panel.setStyleSheet(f"background-color: {BG_SURFACE};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(0)

        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setIndentation(0)
        tree.setRootIsDecorated(False)
        tree.setIconSize(tree.iconSize().scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio))

        self._nav_tree = tree
        self._nav_items: list[QTreeWidgetItem] = []

        header_item = QTreeWidgetItem(["EVE 商人助手"])
        header_item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = header_item.font(0)
        font.setBold(True)
        font.setPointSize(12)
        header_item.setFont(0, font)
        header_item.setForeground(0, QColor(PRIMARY))
        header_item.setSizeHint(0, QSize(header_item.sizeHint(0).width(), 32))
        tree.addTopLevelItem(header_item)

        spacer = QTreeWidgetItem([""])
        spacer.setFlags(Qt.ItemFlag.NoItemFlags)
        spacer.setSizeHint(0, QSize(spacer.sizeHint(0).width(), 8))
        tree.addTopLevelItem(spacer)

        section_label = QTreeWidgetItem(["功能"])
        section_label.setFlags(Qt.ItemFlag.NoItemFlags)
        section_label.setForeground(0, QColor(TEXT_SECONDARY))
        f = section_label.font(0)
        f.setBold(True)
        f.setPointSize(10)
        section_label.setFont(0, f)
        section_label.setSizeHint(0, QSize(section_label.sizeHint(0).width(), 24))
        tree.addTopLevelItem(section_label)

        for key, label, icon in NAV_TREE:
            item = QTreeWidgetItem([f" {icon}  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setSizeHint(0, QSize(item.sizeHint(0).width(), 30))
            tree.addTopLevelItem(item)
            self._nav_items.append(item)

        tree.currentItemChanged.connect(self._on_nav_changed)
        layout.addWidget(tree)

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

    # ═══════════════════════════════════════
    #  页面注册
    # ═══════════════════════════════════════

    def _register_pages(self):
        from ui_pyside6.views.query_view import QueryPage
        from ui_pyside6.views.industry_view import IndustryPage
        from ui_pyside6.views.trade_view import TradePage
        from ui_pyside6.views.inventory_view import InventoryPage

        self._pages["query"] = QueryPage(self)
        self._pages["industry"] = IndustryPage(self)
        self._pages["trade"] = TradePage(self)
        self._pages["storage"] = InventoryPage(self)

        for key in ["query", "industry", "trade", "storage"]:
            self.content_stack.addWidget(self._pages[key])

    # ═══════════════════════════════════════
    #  价格更新
    # ═══════════════════════════════════════

    def _init_price_check(self):
        self._check_worker = PriceCheckWorker(self)
        self._check_worker.result.connect(self._on_price_check_done)
        self._check_worker.start()

    def _on_price_check_done(self, needs_update: bool, status_text: str):
        self._price_time_label.setText(status_text)
        self._refresh_price_time()
        if needs_update:
            self._status_label.setText("正在自动更新价格...")
            QTimer.singleShot(1000, self._trigger_price_update)

    def _trigger_price_update(self):
        if self._price_worker and self._price_worker.isRunning():
            self._status_label.setText("价格更新已在运行中")
            return

        self._update_progress.setVisible(True)
        self._update_progress.setRange(0, 0)  # indeterminate
        self._status_label.setText("正在从 ESI 获取市场价格...")

        self._price_worker = PriceUpdateWorker(self)
        self._price_worker.finished_signal.connect(self._on_price_update_done)
        self._price_worker.start()

    def _on_price_update_done(self, success: bool, message: str):
        self._update_progress.setVisible(False)
        self._update_progress.setRange(0, 100)

        if success:
            self._status_label.setText("价格更新完成")
            self._refresh_price_time()
            page = self._pages.get("query")
            if page and hasattr(page, "refresh_display"):
                page.refresh_display()
        else:
            self._status_label.setText(f"价格更新失败: {message}")

    def _refresh_price_time(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                try:
                    dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                    bj_dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=8)
                    bj_str = bj_dt.strftime("%Y-%m-%d %H:%M:%S")
                    self._price_time_label.setText(f"价格更新: {bj_str} (北京)")
                except Exception:
                    self._price_time_label.setText(f"价格更新: {utc_str} UTC")
            else:
                self._price_time_label.setText("价格更新: 暂无数据")
        except Exception:
            self._price_time_label.setText("价格更新: 数据库未就绪")

    # ═══════════════════════════════════════
    #  其他事件
    # ═══════════════════════════════════════

    def _show_settings(self):
        QMessageBox.information(self, "设置", "设置功能将在后续版本实现。\n\n可配置项：ESI 区域、字体大小、主题切换")

    def _show_about(self):
        QMessageBox.about(
            self, "关于 EVE 商人助手",
            "EVE 商人助手 v2.0\n\n"
            "基于 PySide6 重构\n"
            "为 EVE Online 玩家提供工业制造、市场贸易辅助工具。\n\n"
            "数据来源: EVE Swagger Interface (ESI)\n"
            "© 2026"
        )

    def _refresh_current_page(self):
        current = self.content_stack.currentWidget()
        if current and hasattr(current, "refresh_display"):
            current.refresh_display()
            self._status_label.setText("页面已刷新")

    def _open_all_items(self):
        from ui_pyside6.views.all_items_view import AllItemsDialog
        dialog = AllItemsDialog(self)
        dialog.exec()

    def refresh_price_time(self):
        self._refresh_price_time()

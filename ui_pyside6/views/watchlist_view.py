"""
关注列表页面 — 物品搜索 + 自动补全 + 关注列表表格 + 阈值设置
"""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from ui_qml.models.watchlist_models import COLUMNS as _COLUMNS
from ui_qml.models.watchlist_models import WatchlistTableModel
from ui_qml.workers.watchlist_workers import SuggestionWorker

# ── 表格列定义 ──


# ═══════════════════════════════════════
#  表格模型
# ═══════════════════════════════════════


class SuggestionPopup(QWidget):
    """悬浮候选列表"""

    item_selected = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._list = QListWidget()
        self._list.setObjectName("suggest_list")
        self._list.itemClicked.connect(self._on_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)
        self._list.installEventFilter(self)

    def show_suggestions(self, items: list, pos: QPoint, width: int):
        self._list.clear()
        for tid, display in items:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            self._list.addItem(item)
        h = min(len(items) * 28 + 8, 220)
        self._list.setFixedHeight(h)
        self.setFixedSize(width, h)
        self.move(pos)
        self.show()

    def _on_clicked(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        display = item.text()
        self.hide()
        self.item_selected.emit(tid, display)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and watched is self._list:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                current = self._list.currentItem()
                if current:
                    self._on_clicked(current)
                return True
            elif key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(watched, event)


# ═══════════════════════════════════════
#  主页面
# ═══════════════════════════════════════


class WatchlistPage(QWidget):
    """价格监控 — 关注列表"""

    def __init__(self, main_window):
        super().__init__()
        from services.watchlist_manager import init_db as _init_watchlist_db

        _init_watchlist_db()
        self._main = main_window
        self.setObjectName("watchlist_page")
        self._selected_type_id: int | None = None
        self._selected_name: str = ""
        self._suggest_worker: SuggestionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 顶部：添加关注物品 ──
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        top_layout.addWidget(QLabel("搜索物品:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入物品名称或 Type ID...")
        self._search_input.setMinimumWidth(250)
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.returnPressed.connect(self._on_search_return)
        top_layout.addWidget(self._search_input)

        self._selected_label = QLabel("")
        self._selected_label.setStyleSheet(f"color: {theme.PRIMARY}; font-weight: bold;")
        top_layout.addWidget(self._selected_label)

        top_layout.addWidget(QLabel("区域:"))
        self._region_combo = QComboBox()
        self._region_combo.setFixedWidth(100)
        for name in TRADE_HUB_IDS:
            self._region_combo.addItem(name, TRADE_HUB_IDS[name])
        top_layout.addWidget(self._region_combo)

        top_layout.addWidget(QLabel("备注:"))
        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText("可选")
        self._note_input.setMaximumWidth(150)
        top_layout.addWidget(self._note_input)

        self._add_btn = QPushButton("添加关注")
        self._add_btn.clicked.connect(self._on_add)
        top_layout.addWidget(self._add_btn)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # ── 中部：关注列表表格 ──
        self._model = WatchlistTableModel()
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        # 设置列宽
        header = self._table.horizontalHeader()
        for i, (_, width) in enumerate(_COLUMNS):
            if i == len(_COLUMNS) - 1:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._table.setColumnWidth(i, width)

        self._table.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self._table, 1)

        # ── 底部：操作栏 ──
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        self._refresh_btn = QPushButton()
        icons.set_button_icon(self._refresh_btn, "refresh", text="刷新价格")
        self._refresh_btn.clicked.connect(self._refresh_data)
        bottom_layout.addWidget(self._refresh_btn)

        self._remove_btn = QPushButton()
        icons.set_button_icon(self._remove_btn, "trash", text="删除选中")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        bottom_layout.addWidget(self._remove_btn)

        bottom_layout.addStretch()

        self._count_label = QLabel("共 0 项")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        bottom_layout.addWidget(self._count_label)

        layout.addLayout(bottom_layout)

        # ── 弹窗 ──
        self._popup = SuggestionPopup(self)
        self._popup.item_selected.connect(self._on_item_selected)

        # ── 主题 ──

        # ── 价格变化检测 ──
        self._price_changes: dict[int, dict] = {}
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._on_price_check_timer)
        self._check_timer.start(60000)  # 60秒
        theme.add_theme_listener(self._on_theme_changed)

    def showEvent(self, event):
        """显示时启动定时器"""
        super().showEvent(event)
        if not self._check_timer.isActive():
            self._check_timer.start(60000)

    def hideEvent(self, event):
        """隐藏时停止定时器"""
        super().hideEvent(event)
        self._check_timer.stop()

    def _on_price_check_timer(self):
        """定时检查价格变化"""
        try:
            from services.watchlist_manager import check_price_changes

            changes = check_price_changes()
            self._price_changes = {c["type_id"]: c for c in changes}
            self._model.set_price_changes(self._price_changes)
            self._refresh_data()
            self.update_status_bar()
        except Exception as ex:
            print(f"价格变化检测失败: {ex}")

    def trigger_price_check(self):
        """外部调用触发即时价格变化检查"""
        self._on_price_check_timer()

    def save_state(self) -> dict:
        data = {}
        header = self._table.horizontalHeader()
        if header and header.sortIndicatorSection() >= 0:
            data["sort_column"] = header.sortIndicatorSection()
            data["sort_order"] = 1 if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else 0
        vs = self._table.verticalScrollBar()
        if vs:
            data["v_scroll"] = vs.value()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        col = data.get("sort_column", -1)
        if col >= 0:
            order = Qt.SortOrder.AscendingOrder if data.get("sort_order", 1) == 1 else Qt.SortOrder.DescendingOrder
            self._table.sortByColumn(col, order)
        sv = data.get("v_scroll", 0)
        if sv:
            QTimer.singleShot(100, lambda: self._table.verticalScrollBar().setValue(sv))

    def _on_theme_changed(self):
        """主题切换时更新内联样式"""
        self._selected_label.setStyleSheet(f"color: {theme.PRIMARY}; font-weight: bold;")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._model.beginResetModel()
        self._model.endResetModel()

    # ── 搜索 & 自动补全 ──

    def _on_search_changed(self, text: str):
        if len(text) < 1:
            self._popup.hide()
            return
        if self._suggest_worker and self._suggest_worker.isRunning():
            self._suggest_worker.requestInterruption()
        self._suggest_worker = SuggestionWorker(text, self)
        self._suggest_worker.finished_signal.connect(self._on_suggestions)
        self._suggest_worker.start()

    def _on_suggestions(self, items: list):
        if not items:
            self._popup.hide()
            return
        pos = self._search_input.mapToGlobal(QPoint(0, self._search_input.height()))
        self._popup.show_suggestions(items, pos, self._search_input.width())

    def _on_search_return(self):
        """回车直接添加当前搜索框的物品（如果有选中）"""
        if self._selected_type_id:
            self._on_add()

    def _on_item_selected(self, type_id: int, display: str):
        self._selected_type_id = type_id
        self._selected_name = display
        self._selected_label.setText(display)
        self._search_input.setText(display)

    # ── 添加 / 删除 ──

    def _on_add(self):
        if not self._selected_type_id:
            QMessageBox.warning(self, "提示", "请先搜索并选择一个物品")
            return
        from services.watchlist_manager import add_to_watchlist

        region_id = self._region_combo.currentData()
        note = self._note_input.text().strip()
        result = add_to_watchlist(
            type_id=self._selected_type_id,
            region_id=region_id,
            note=note,
        )
        if result > 0:
            self._search_input.clear()
            self._selected_label.setText("")
            self._selected_type_id = None
            self._selected_name = ""
            self._note_input.clear()
            self._refresh_data()
        else:
            QMessageBox.warning(self, "提示", "添加失败")

    def _on_remove_selected(self):
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return
        reply = QMessageBox.question(
            self,
            "确认",
            f"确定删除选中的 {len(indexes)} 项?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from services.watchlist_manager import remove_from_watchlist

        for idx in indexes:
            row = idx.row()
            item = self._model._rows[row]
            remove_from_watchlist(item["id"])
        self._refresh_data()

    # ── 刷新 ──

    def _refresh_data(self):
        from services.watchlist_manager import get_watchlist

        items = get_watchlist()
        self._model.set_rows(items)
        self._count_label.setText(f"共 {len(items)} 项")
        self.update_status_bar()

    def refresh_display(self):
        """外部调用刷新"""
        self._refresh_data()

    def update_status_bar(self):
        """更新主窗口状态栏显示关注列表统计"""
        count = self._model.rowCount()
        # 计算有多少物品触发了阈值
        triggered = 0
        for row in range(count):
            row_data = self._model._rows[row]
            buy_thresh = row_data.get("buy_threshold")
            sell_thresh = row_data.get("sell_threshold")
            buy_price = row_data.get("buy_price")
            sell_price = row_data.get("sell_price")
            if buy_thresh is not None and buy_price and buy_price <= buy_thresh:
                triggered += 1
            elif sell_thresh is not None and sell_price and sell_price >= sell_thresh:
                triggered += 1
        if self._main and hasattr(self._main, "statusBar"):
            msg = f"关注列表: {count} 项"
            if triggered:
                msg += f", {triggered} 项触发提醒"
            change_count = len(self._price_changes)
            if change_count:
                msg += f", {change_count} 项价格变化"
            self._main.statusBar().showMessage(msg)

    # ── 右键菜单 ──

    def _on_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        row_data = self._model._rows[index.row()]

        self._create_context_menu(row_data, pos)

    def _create_context_menu(self, row_data: dict, pos):
        """创建右键菜单（依赖全局 QSS，无 inline setStyleSheet）"""
        menu = QMenu(self)
        menu.setObjectName("sys_menu")

        set_buy = menu.addAction("设置买价阈值")
        set_sell = menu.addAction("设置卖价阈值")
        menu.addSeparator()
        remove_action = menu.addAction("删除")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))  # type: ignore[union-attr]

        if action == set_buy:
            self._set_threshold(row_data, "buy")
        elif action == set_sell:
            self._set_threshold(row_data, "sell")
        elif action == remove_action:
            from services.watchlist_manager import remove_from_watchlist

            remove_from_watchlist(row_data["id"])
            self._refresh_data()

    def _set_threshold(self, row_data: dict, threshold_type: str):
        """设置阈值弹窗"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox

        dlg = QDialog(self)
        dlg.setWindowTitle(f"设置{'买价' if threshold_type == 'buy' else '卖价'}阈值")
        dlg_layout = QVBoxLayout(dlg)

        label = QLabel(
            f"当{'买价 ≤' if threshold_type == 'buy' else '卖价 ≥'} 此值时提醒:\n"
            f"物品: {row_data.get('zh_name', row_data.get('en_name', ''))}"
        )
        dlg_layout.addWidget(label)

        spinner = QDoubleSpinBox()
        spinner.setRange(0, 999999999)
        spinner.setDecimals(2)
        spinner.setPrefix("ISK ")
        current = row_data.get(f"{threshold_type}_threshold")
        if current:
            spinner.setValue(current)
        dlg_layout.addWidget(spinner)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btn_box)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            from services.watchlist_manager import update_watchlist_item

            value = spinner.value() if spinner.value() > 0 else None
            if threshold_type == "buy":
                update_watchlist_item(row_data["id"], buy_threshold=value)
            else:
                update_watchlist_item(row_data["id"], sell_threshold=value)
            self._refresh_data()

    # ── 双击编辑阈值 ──

    def _on_double_click(self, index: QModelIndex):
        col = index.column()
        row_data = self._model._rows[index.row()]
        if col == 7:  # 买价阈值
            self._set_threshold(row_data, "buy")
        elif col == 8:  # 卖价阈值
            self._set_threshold(row_data, "sell")

    def _get_row(self, row_idx: int) -> dict | None:
        if 0 <= row_idx < len(self._model._rows):
            return self._model._rows[row_idx]  # type: ignore[no-any-return]
        return None

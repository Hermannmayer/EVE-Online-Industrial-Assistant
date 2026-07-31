"""
物品查询页面 — QueryPage 主容器
"""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from ui_pyside6.views.query.query_order_popup import do_load_orders, hide_order_popup
from ui_pyside6.views.query.query_search import (
    _COLUMNS,
    DEFAULT_REGION_ID,
    GroupLoadWorker,
    SearchWorker,
    SuggestionPopup,
    SuggestionWorker,
    add_search_history,
    clear_search_history,
    format_search_rows,
    load_search_history,
    show_context_menu,
)
from ui_pyside6.views.query.query_search import QueryTableModel as _QueryTableModel


class QueryPage(QWidget):
    """物品查询页面"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("query_page")
        self._all_groups: list = []
        self._current_query: str = ""
        self._region_id = DEFAULT_REGION_ID
        self._current_order_type_id: int | None = None
        self._order_popup = None
        self._all_items_dialog = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._build_search_bar(layout)
        self._build_progress(layout)
        self._build_status_bar(layout)
        self._build_table(layout)

        # 候选弹窗
        self._suggest_popup = SuggestionPopup(self)
        self._suggest_popup.item_selected.connect(self._on_suggest_popup_selected)

        # 加载类别
        self._load_groups()

        # 搜索防抖
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._fetch_suggestions)

        # 事件过滤 (搜索框键盘)
        self._search_input.installEventFilter(self)

        # 主题监听
        theme.add_theme_listener(self._on_theme_changed)

    # ── 布局构建 ──

    def _build_search_bar(self, layout):
        search_bar = QWidget()
        search_bar.setObjectName("query_toolbar")
        sb_layout = QHBoxLayout(search_bar)
        sb_layout.setContentsMargins(12, 8, 12, 8)
        sb_layout.setSpacing(8)

        self._all_items_btn = QPushButton("📦 全物品")
        self._all_items_btn.setToolTip("打开全物品浏览器")
        self._style_toolbar_btn(self._all_items_btn)
        self._all_items_btn.clicked.connect(self._open_all_items)
        sb_layout.addWidget(self._all_items_btn)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入物品名称/ID/类别搜索...")
        self._search_input.textChanged.connect(self._on_input_changed)
        self._search_input.returnPressed.connect(self._do_search)
        self._search_input.setClearButtonEnabled(True)
        sb_layout.addWidget(self._search_input)

        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._do_search)
        sb_layout.addWidget(search_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_search)
        sb_layout.addWidget(clear_btn)

        batch_btn = QPushButton("批量查价")
        batch_btn.setObjectName("batch_price_btn")
        batch_btn.setToolTip("一次性查询多个物品的价格")
        self._style_toolbar_btn(batch_btn)
        batch_btn.clicked.connect(self._open_batch_price)
        sb_layout.addWidget(batch_btn)

        sb_layout.addStretch()
        sb_layout.addWidget(QLabel("区域:"))
        self._region_combo = QComboBox()
        from core.constants import TRADE_HUBS

        self._region_combo.addItems(list(TRADE_HUBS))
        self._region_combo.setCurrentText("Jita")
        self._region_combo.currentIndexChanged.connect(self._on_region_changed)
        sb_layout.addWidget(self._region_combo)

        layout.addWidget(search_bar)

    def _build_progress(self, layout):
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

    def _build_status_bar(self, layout):
        status_widget = QWidget()
        status_widget.setObjectName("query_status")
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 2, 0, 2)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        status_layout.addWidget(self._count_label)
        status_layout.addStretch()

        self._status_label = QLabel("输入物品名称/ID后搜索，双击行查看实时订单")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        status_layout.addWidget(self._status_label)

        layout.addWidget(status_widget)

    def _build_table(self, layout):
        self._table = QTableView()
        self._table.setAlternatingRowColors(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.doubleClicked.connect(self._on_row_double_click)
        self._table.horizontalHeader().setSectionsClickable(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(36)

        self._model = _QueryTableModel()
        self._table.setModel(self._model)

        for i, (_, w) in enumerate(_COLUMNS):
            self._table.setColumnWidth(i, w)

        layout.addWidget(self._table)

    def _style_toolbar_btn(self, btn):
        btn.setStyleSheet(
            f"QPushButton{{background:{theme.BG_SURFACE_LIGHT};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:6px;padding:6px 12px;font-size:12px;}}"
            f"QPushButton:hover{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
            f"border:1px solid {theme.PRIMARY};}}"
        )

    # ── 主题 ──

    def _on_theme_changed(self):
        self._style_toolbar_btn(self._all_items_btn)
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        batch_btn = self.findChild(QPushButton, "batch_price_btn")
        if batch_btn:
            self._style_toolbar_btn(batch_btn)

    # ── 类别加载 ──

    def _load_groups(self):
        worker = GroupLoadWorker(self)
        worker.finished_signal.connect(self._on_groups_loaded)
        worker.start()

    def _on_groups_loaded(self, groups: list):
        self._all_groups = groups

    # ── 搜索输入 ──

    def _on_input_changed(self, text: str):
        if len(text) >= 1:
            self._debounce_timer.start(200)
        else:
            self._suggest_popup.hide()
            self._show_search_history()

    def _fetch_suggestions(self):
        query = self._search_input.text().strip()
        if len(query) < 1:
            return
        worker = SuggestionWorker(query, self)
        worker.finished_signal.connect(self._show_suggestions)
        worker.start()

    def _show_suggestions(self, suggestions: list):
        if not suggestions:
            self._suggest_popup.hide()
            return
        pos = self._search_input.mapToGlobal(QPoint(0, self._search_input.height()))
        self._suggest_popup.show_suggestions(suggestions, pos, self._search_input.width())

    def _on_suggest_popup_selected(self, tid: int, name: str):
        self._search_input.setText(name or str(tid))
        self._do_search()

    # ── 搜索历史 ──

    def _add_search_history(self, query: str):
        add_search_history(query)

    def _load_search_history(self) -> list:
        return load_search_history()

    def _show_search_history(self):
        history = self._load_search_history()
        if not history:
            self._suggest_popup.hide()
            return
        pos = self._search_input.mapToGlobal(QPoint(0, self._search_input.height()))
        self._suggest_popup.show_history(history, pos, self._search_input.width())

    def _clear_search_history(self):
        clear_search_history()
        self._suggest_popup.hide()

    # ── 执行搜索 ──

    def _do_search(self):
        query = self._search_input.text().strip()
        self._suggest_popup.hide()
        if not query:
            self._status_label.setText("请输入物品名称或 ID")
            return

        self._current_query = query
        self._add_search_history(query)
        hide_order_popup(self)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # indeterminate

        worker = SearchWorker(query, self._all_groups, self._region_id, self)
        worker.finished_signal.connect(self._on_search_done)
        worker.error_signal.connect(self._on_search_error)
        worker.start()

    def _on_search_done(self, rows: list, is_fallback: bool):
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)

        if not rows:
            self._count_label.setText("")
            self._status_label.setText(f"未找到包含「{self._current_query}」的物品")
            self._model.set_rows([])
            return

        parsed = format_search_rows(rows, is_fallback)
        self._model.set_rows(parsed)
        self._count_label.setText(f"共 {len(rows)} 条结果" + (" (仅基本信息)" if is_fallback else ""))
        self._status_label.setText("就绪 — 右键行可查看操作菜单，双击查看实时订单")

        for i, (_, w) in enumerate(_COLUMNS):
            if self._table.columnWidth(i) < 20:
                self._table.setColumnWidth(i, w)

    def _on_search_error(self, error: str):
        self._progress.setVisible(False)
        self._status_label.setText(f"查询出错: {error}")

    def _clear_search(self):
        self._search_input.clear()
        self._current_query = ""
        self._model.set_rows([])
        self._count_label.setText("")
        self._status_label.setText("已清空")
        hide_order_popup(self)
        self._suggest_popup.hide()

    # ── 右键菜单 ──

    def _on_context_menu(self, pos: QPoint):
        show_context_menu(self, pos)

    # ── 订单弹窗 ──

    def _on_row_double_click(self, index):
        row_data = self._model.get_row(index.row())
        if not row_data:
            return
        do_load_orders(self, row_data["type_id"])

    # ── 区域切换 ──

    def _on_region_changed(self, index: int):
        from core.constants import TRADE_HUB_IDS

        hub = self._region_combo.currentText()
        self._region_id = TRADE_HUB_IDS.get(hub, 10000002)
        if self._current_query:
            self._do_search()

    # ── 子窗口 ──

    def _open_all_items(self):
        from ui_pyside6.views.all_items_view import AllItemsDialog

        if self._all_items_dialog is None:
            self._all_items_dialog = AllItemsDialog(self)
        self._all_items_dialog.show()
        self._all_items_dialog.raise_()

    def _open_batch_price(self):
        from ui_pyside6.views.batch_price_dialog import BatchPriceDialog

        dlg = BatchPriceDialog(self)
        dlg.exec()

    # ── 公共 API ──

    def save_state(self) -> dict:
        data = {"search_text": self._search_input.text()}
        header = self._table.horizontalHeader()
        if header.sortIndicatorSection() >= 0:
            data["sort_column"] = header.sortIndicatorSection()
            data["sort_order"] = 1 if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else 0
        vs = self._table.verticalScrollBar()
        if vs:
            data["v_scroll"] = vs.value()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        if data.get("search_text"):
            self._search_input.setText(data["search_text"])
        col = data.get("sort_column", -1)
        if col >= 0:
            order = Qt.SortOrder.AscendingOrder if data.get("sort_order", 1) == 1 else Qt.SortOrder.DescendingOrder
            self._table.sortByColumn(col, order)
        sv = data.get("v_scroll", 0)
        if sv:
            QTimer.singleShot(100, lambda: self._table.verticalScrollBar().setValue(sv))

    def eventFilter(self, obj, event):
        if obj is self._search_input:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Escape:
                    self._suggest_popup.hide()
                elif key == Qt.Key.Key_Down:
                    if self._suggest_popup.isVisible():
                        self._suggest_popup._list.setFocus()
                        if self._suggest_popup._list.count() > 0:
                            self._suggest_popup._list.setCurrentRow(0)
                        return True
        return super().eventFilter(obj, event)

    def refresh_display(self):
        if self._current_query:
            self._do_search()
        else:
            self._status_label.setText("就绪 — 价格数据已更新")

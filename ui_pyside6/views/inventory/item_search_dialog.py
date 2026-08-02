"""
仓库页面 — 可复用物品搜索对话框（ItemSearchDialog）

供库存修正/移库对话框处理「未匹配」行：搜索 item 表（含 terminology 基础矿物）
选择物品并返回 {type_id, zh_name, en_name}。双击/回车即选定。
"""

from PySide6.QtCore import QAbstractTableModel, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.terminology import term


class _SearchResultsModel(QAbstractTableModel):
    """物品搜索结果模型（type_id/中文/英文）"""

    _HEADERS = ["type_id", "中文", "英文"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return str(r["type_id"])
            if c == 1:
                return r.get("zh_name", "")
            if c == 2:
                return r.get("en_name", "")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def row_at(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None


class ItemSearchDialog(QDialog):
    """搜索物品（item 表模糊 + terminology 基础矿物反向）→ selected_item()"""

    def __init__(self, parent=None, title: str = "搜索匹配物品"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 420)
        self._selected: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("输入物品名称（中文/英文）...")
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)
        # 200ms 防抖：停止输入后再搜索
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._do_search)
        self._search.textChanged.connect(lambda: self._debounce.start())

        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(self._on_activate)
        self._search_model = _SearchResultsModel([])
        self._table.setModel(self._search_model)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in {0: 70, 1: 180, 2: 180}.items():
            self._table.setColumnWidth(col, w)
        layout.addWidget(self._table, 1)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("选定")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    # ── 搜索 ──

    def _set_results(self, rows: list[dict]):
        self._search_model = _SearchResultsModel(rows)
        self._table.setModel(self._search_model)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        if rows:
            self._table.selectRow(0)

    def _do_search(self):
        text = self._search.text().strip()
        if not text:
            self._set_results([])
            return
        self._set_results(self._search_items(text))

    def _search_items(self, text: str) -> list[dict]:
        """item 表模糊匹配 + terminology.item_overrides 反向匹配基础矿物"""
        results: list[dict] = []
        like = f"%{text}%"
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT type_id, zh_name, en_name FROM item "
                "WHERE (zh_name LIKE ? OR en_name LIKE ?) "
                "ORDER BY CASE WHEN en_name=? OR zh_name=? THEN 0 ELSE 1 END, "
                "LENGTH(en_name), type_id LIMIT 20",
                (like, like, text, text),
            )
            results = [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]
        # terminology.item_overrides 反向匹配（基础矿物 34-40 等不在 item 表，仅在此注册）
        term._ensure()
        overrides = term._data.get("item_overrides") or {}
        seen = {r["type_id"] for r in results}
        for tid_str, name in overrides.items():
            if text.lower() in str(name).lower() and int(tid_str) not in seen:
                results.append({"type_id": int(tid_str), "zh_name": name, "en_name": ""})
        return results

    def _on_row_selected(self, current, previous):
        if current.isValid():
            self._selected = self._search_model.row_at(current.row())

    def _on_activate(self, index):
        if index.isValid():
            self._selected = self._search_model.row_at(index.row())
            self.accept()

    def _on_accept(self):
        if not self._selected and self._search_model.rowCount() == 1:
            self._selected = self._search_model.row_at(0)
        if not self._selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果中选择物品")
            return
        self.accept()

    def selected_item(self) -> dict | None:
        """返回选中的 {type_id, zh_name, en_name} 或 None"""
        return self._selected

    def _on_theme_changed(self):
        self._table.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        self._search.setFocus()

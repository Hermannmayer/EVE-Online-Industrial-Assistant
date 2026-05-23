"""
仓库页面 — 物品清单管理
"""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableView, QHeaderView,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
from core.paths import DB_PATH
from ui_pyside6.theme import BG_DARK, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY


class InventoryPage(QWidget):
    """仓库页"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("inventory_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        toolbar = QWidget()
        toolbar.setObjectName("query_toolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 8, 12, 8)
        tb_layout.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索物品名称...")
        self._search.returnPressed.connect(self._do_search)
        tb_layout.addWidget(self._search)

        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._do_search)
        tb_layout.addWidget(search_btn)

        layout.addWidget(toolbar)

        # 表格
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table)

        # 初始加载
        self._do_search()

    def _do_search(self):
        keyword = self._search.text().strip()
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            if keyword:
                c.execute(
                    "SELECT type_id, zh_name, en_name, volume FROM item "
                    "WHERE zh_name LIKE ? OR en_name LIKE ? ORDER BY zh_name LIMIT 200",
                    (f"%{keyword}%", f"%{keyword}%"),
                )
            else:
                c.execute(
                    "SELECT type_id, zh_name, en_name, volume FROM item ORDER BY zh_name LIMIT 200"
                )
            rows = c.fetchall()
        finally:
            conn.close()

        model = InventoryModel(rows)
        self._table.setModel(model)
        self._table.setColumnWidth(0, 80)
        self._table.setColumnWidth(1, 180)
        self._table.setColumnWidth(2, 140)
        self._table.setColumnWidth(3, 80)

    def _on_context_menu(self, pos):
        index = self._table.currentIndex()
        if not index.isValid():
            return
        menu = QMenu(self)
        view_action = QAction("查看详情", self)
        menu.addAction(view_action)
        copy_action = QAction("复制名称", self)
        copy_action.triggered.connect(lambda: self._copy_cell(1))
        menu.addAction(copy_action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_cell(self, col: int):
        index = self._table.currentIndex()
        if index.isValid():
            from PySide6.QtWidgets import QApplication
            text = str(self._table.model().index(index.row(), col).data())
            QApplication.instance().clipboard().setText(text)

    def refresh_display(self):
        self._do_search()


class InventoryModel(QAbstractTableModel):
    _HEADERS = ["物品ID", "名称", "英文名", "体积 m³"]

    def __init__(self, data: list):
        super().__init__()
        self._data = data

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row[0])
            elif col == 1:
                return row[1] or ""
            elif col == 2:
                return row[2] or ""
            elif col == 3:
                return f"{row[3]:,.2f}" if row[3] else "—"
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

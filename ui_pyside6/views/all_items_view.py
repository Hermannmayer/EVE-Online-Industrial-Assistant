"""
全物品浏览器 — QDialog 弹窗
"""
import sqlite3
import os
import asyncio
import concurrent.futures
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QTableView, QHeaderView, QLineEdit, QLabel, QSplitter, QPushButton,
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal, QThread, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QMenu, QApplication
from core.paths import DB_PATH, ICON_DIR
from ui_pyside6.theme import BG_SURFACE, BG_DARK, PRIMARY, TEXT_SECONDARY


class AllItemsDialog(QDialog):
    """全物品查询弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全物品查询")
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 顶栏：搜索 + 置顶
        top_bar = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索物品名称...")
        self._search_input.textChanged.connect(self._on_search)
        top_bar.addWidget(self._search_input)

        self._pin_cb = QCheckBox("窗口置顶")
        self._pin_cb.toggled.connect(self._on_pin_toggled)
        top_bar.addWidget(self._pin_cb)
        layout.addLayout(top_bar)

        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # 左侧分类树
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFixedWidth(220)
        self._tree.itemClicked.connect(self._on_tree_clicked)
        splitter.addWidget(self._tree)

        # 右侧物品表格
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.doubleClicked.connect(self._on_row_double_click)
        self._table.verticalHeader().setDefaultSectionSize(36)
        splitter.addWidget(self._table)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # 加载分类树
        self._load_tree()

        # 默认加载全物品
        self._load_all_items()

    def _load_tree(self):
        worker = TreeLoadWorker(self)
        worker.finished_signal.connect(self._on_tree_loaded)
        worker.start()

    def _on_tree_loaded(self, items: list):
        root = self._tree.invisibleRootItem()
        root.takeChildren()
        # Two-pass: build dict first, then assemble tree
        node_map: dict[int, QTreeWidgetItem] = {}
        for item_data in items:
            node = QTreeWidgetItem([item_data["name"]])
            node.setData(0, Qt.ItemDataRole.UserRole, item_data["id"])
            node.setData(0, Qt.ItemDataRole.UserRole + 1, item_data.get("has_children", False))
            node_map[item_data["id"]] = node

        for item_data in items:
            node = node_map[item_data["id"]]
            parent_id = item_data.get("parent_id")
            if parent_id is not None and parent_id in node_map:
                node_map[parent_id].addChild(node)
            elif parent_id is not None:
                # orphan — attach to root
                root.addChild(node)
            else:
                root.addChild(node)

        self._tree.expandAll()

    def _on_tree_clicked(self, item: QTreeWidgetItem, column: int):
        mg_id = item.data(0, Qt.ItemDataRole.UserRole)
        if mg_id:
            self._load_items(mg_id)

    def _load_all_items(self):
        worker = AllItemsLoadWorker(self)
        worker.finished_signal.connect(self._on_items_loaded)
        worker.start()
        self._search_input.setText("")

    def _load_items(self, mg_id: int):
        worker = ItemsLoadWorker(mg_id, self)
        worker.finished_signal.connect(self._on_items_loaded)
        worker.start()
        self._search_input.setText("")

    def _on_items_loaded(self, rows):
        model = AllItemsModel(rows)
        self._table.setModel(model)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        widths = [40, 60, 140, 180, 100, 100, 90, 80]
        for i, w in enumerate(widths):
            self._table.setColumnWidth(i, w)

    def _on_pin_toggled(self, checked: bool):
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()  # re-show needed after setWindowFlags

    def _on_search(self, text: str):
        if not text.strip():
            return
        worker = ItemsSearchWorker(text, self)
        worker.finished_signal.connect(self._on_items_loaded)
        worker.start()

    def _on_context_menu(self, pos):
        index = self._table.currentIndex()
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_name = QAction("复制名称", self)
        copy_name.triggered.connect(lambda: self._copy_cell(2))
        menu.addAction(copy_name)

        copy_id = QAction("复制 Type ID", self)
        copy_id.triggered.connect(lambda: self._copy_cell(0))
        menu.addAction(copy_id)

        menu.addSeparator()
        view_detail = QAction("查看详情", self)
        view_detail.triggered.connect(lambda: self._on_row_double_click(index))
        menu.addAction(view_detail)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_cell(self, col: int):
        index = self._table.currentIndex()
        if index.isValid():
            model = self._table.model()
            text = str(model.index(index.row(), col).data())
            QApplication.instance().clipboard().setText(text)

    def _on_row_double_click(self, index: QModelIndex):
        type_id = int(self._table.model().index(index.row(), 0).data())
        QApplication.instance().clipboard().setText(str(type_id))


# ═══════════════════════════════════════
#  Workers
# ═══════════════════════════════════════

class TreeLoadWorker(QThread):
    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT market_group_id, parent_group_id, zh_name FROM market_group ORDER BY zh_name")
            rows = c.fetchall()
            result = []
            for mg_id, parent_id, zh_name in rows:
                result.append({
                    "id": mg_id,
                    "parent_id": parent_id,
                    "name": zh_name or f"Group {mg_id}",
                    "has_children": False,
                })
            self.finished_signal.emit(result)
        finally:
            conn.close()


class ItemsLoadWorker(QThread):
    finished_signal = Signal(list)

    def __init__(self, market_group_id: int, parent=None):
        super().__init__(parent)
        self._mg_id = market_group_id

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT i.type_id, i.zh_name, i.en_name,
                       mp.sell_price, mp.buy_price, i.volume
                FROM item i
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE i.market_group_id = ?
                ORDER BY i.zh_name, i.en_name
                LIMIT 500
            """, (self._mg_id,))
            rows = c.fetchall()
            self.finished_signal.emit(rows)
        finally:
            conn.close()


class ItemsSearchWorker(QThread):
    finished_signal = Signal(list)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            like = f"%{self._query}%"
            c.execute("""
                SELECT i.type_id, i.zh_name, i.en_name,
                       mp.sell_price, mp.buy_price, i.volume
                FROM item i
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE i.zh_name LIKE ? OR i.en_name LIKE ?
                ORDER BY i.zh_name LIMIT 200
            """, (like, like))
            rows = c.fetchall()
            self.finished_signal.emit(rows)
        finally:
            conn.close()


class AllItemsLoadWorker(QThread):
    """加载全物品（不限分类）"""
    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT i.type_id, i.zh_name, i.en_name,
                       mp.sell_price, mp.buy_price, i.volume
                FROM item i
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                ORDER BY i.zh_name, i.en_name
                LIMIT 1000
            """)
            rows = c.fetchall()
            self.finished_signal.emit(rows)
        finally:
            conn.close()


class AllItemsModel(QAbstractTableModel):
    _HEADERS = ["图标", "ID", "中文名称", "英文名称", "最高价", "最低价", "平均价", "体积 m³"]

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
                return ""
            elif col == 1:
                return str(row[0])
            elif col == 2:
                return row[1] or ""
            elif col == 3:
                return row[2] or ""
            elif col == 4:
                return f"{row[3]:,.2f}" if row[3] else "—"
            elif col == 5:
                return f"{row[4]:,.2f}" if row[4] else "—"
            elif col == 6:
                sell = row[3] or 0
                buy = row[4] or 0
                if sell and buy:
                    return f"{(sell + buy) / 2:,.2f}"
                return f"{sell:,.2f}" if sell else "—"
            elif col == 7:
                return f"{row[5]:,.2f}" if row[5] else "—"

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                type_id = row[0]
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 4, 5, 6, 7):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

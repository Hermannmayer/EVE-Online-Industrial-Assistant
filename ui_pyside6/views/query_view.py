"""
物品查询页面 — QTableView + 右键菜单 + 订单面板
"""
import asyncio
import json
import os
import sqlite3
import time as _time
from pathlib import Path

import aiohttp
from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPoint,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.paths import ICON_DIR, search_history_file
from services.database_manager import get_db as _get_db_view

_query_db = _get_db_view()
from ui_pyside6.theme import (
    BG_DARK,
    BG_SURFACE,
    BG_SURFACE_LIGHT,
    BORDER,
    GREEN,
    PRIMARY,
    RED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

ICON_SIZE = 32
HISTORY_FILE = Path(search_history_file())
MAX_HISTORY = 20
ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002

_station_name_cache: dict[int, str] = {}


# ═══════════════════════════════════════
#  Data model
# ═══════════════════════════════════════

_COLUMNS = [
    ("图标", 50),
    ("中文名", 140),
    ("英文名", 170),
    ("类别", 100),
    ("买单 ↓", 120),
    ("卖单 ↑", 120),
    ("均价", 90),
    ("体积 m³", 80),
]

_SORT_KEYS = [None, "zh", "en", "group", "buy_val", "sell_val", "avg_price_val", "vol_val"]


class QueryTableModel(QAbstractTableModel):
    """查询结果表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self._sort_col = -1
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return ""  # icon handled by DecorationRole
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                type_id = row.get("type_id")
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

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:
                return QColor(GREEN) if row.get("buy_str") != "—" else QColor(TEXT_SECONDARY)
            elif col == 5:
                return QColor(RED) if row.get("sell_str") != "—" else QColor(TEXT_SECONDARY)
            elif col == 6:
                return QColor(GREEN) if row.get("avg_price_str") != "—" else QColor(TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            if row.get("is_inverted"):
                return QColor("#1f1f3f")
            if index.row() % 2 == 0:
                return QColor(BG_SURFACE)
            return QColor(BG_DARK)

        elif role == Qt.ItemDataRole.FontRole:
            if col in (1, 4, 5, 6, 7):
                font = QFont("Consolas", 10)
                return font

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 1:
            return row.get("zh", "")
        elif col == 2:
            return row.get("en", "")
        elif col == 3:
            return row.get("group", "")
        elif col == 4:
            return row.get("buy_str", "—")
        elif col == 5:
            return row.get("sell_str", "—")
        elif col == 6:
            return row.get("avg_price_str", "—")
        elif col == 7:
            return row.get("vol_str", "—")
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = _COLUMNS[section][0]
            if section == self._sort_col:
                arrow = " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
                label = label.rstrip(" ↓↑") + arrow
            return label
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        sk = _SORT_KEYS[column] if column < len(_SORT_KEYS) else None
        if sk is None:
            return

        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        if sk in ("buy_val", "sell_val", "avg_price_val", "vol_val", "type_id"):
            self._rows.sort(key=lambda r: r.get(sk, 0) or 0, reverse=reverse)
        else:
            self._rows.sort(key=lambda r: (r.get(sk, "") or "").lower(), reverse=reverse)

        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    def get_row(self, row_idx: int) -> dict | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None


# ═══════════════════════════════════════
#  Workers
# ═══════════════════════════════════════

class SearchWorker(QThread):
    """后台数据库搜索"""
    finished_signal = Signal(list, bool)  # rows, is_fallback
    error_signal = Signal(str)

    def __init__(self, query: str, all_groups: list, parent=None):
        super().__init__(parent)
        self._query = query
        self._all_groups = all_groups

    def run(self):
        try:
            rows = self._db_search(self._query)
            self.finished_signal.emit(rows, False)
        except Exception as e:
            try:
                rows = self._db_search_basic(self._query)
                self.finished_signal.emit(rows, True)
            except Exception:
                self.error_signal.emit(str(e))

    def _db_search(self, query: str):
        with _query_db.connect('ref', 'mkt') as conn:
            c = conn.cursor()
            like = f"%{query}%"
            group_match = None
            for gid, en, zh in self._all_groups:
                if (zh and query in zh) or (en and query in en):
                    group_match = gid
                    break

            if query.isdigit():
                c.execute("""
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM item i
                    LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id)
                    WHERE i.type_id = ? OR i.en_name LIKE ? OR i.zh_name LIKE ?
                    ORDER BY i.type_id LIMIT 300
                """, (int(query), like, like))
            elif group_match is not None:
                c.execute("""
                    SELECT sub.type_id, sub.zh_name, sub.en_name, sub.en_group_name, sub.zh_group_name, sub.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM (
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i WHERE i.group_id = ?
                        UNION
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i WHERE (i.en_name LIKE ? OR i.zh_name LIKE ?)
                    ) sub
                    LEFT JOIN mkt.market_prices mp ON sub.type_id = mp.type_id
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = sub.type_id)
                    ORDER BY sub.type_id LIMIT 300
                """, (group_match, like, like))
            else:
                c.execute("""
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM item i
                    LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id)
                    WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
                    ORDER BY i.type_id LIMIT 300
                """, (like, like))
            return c.fetchall()

    def _db_search_basic(self, query: str):
        with _query_db.connect('ref') as conn:
            c = conn.cursor()
            if query.isdigit():
                c.execute("SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume FROM item WHERE type_id = ?", (int(query),))
            else:
                c.execute("SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 100",
                          (f"%{query}%", f"%{query}%"))
            return c.fetchall()


class SuggestionWorker(QThread):
    """后台候选搜索"""
    finished_signal = Signal(list)  # list of (type_id, display, zh_name)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        with _query_db.connect('ref') as conn:
            c = conn.cursor()
            q = self._query
            if q.isdigit():
                c.execute(
                    "SELECT type_id, en_name, zh_name FROM item "
                    "WHERE type_id = ? OR en_name LIKE ? OR zh_name LIKE ? "
                    "ORDER BY CASE WHEN type_id = ? THEN 0 ELSE 1 END, LENGTH(en_name), type_id LIMIT 10",
                    (int(q), f"%{q}%", f"%{q}%", int(q))
                )
            else:
                c.execute(
                    "SELECT type_id, en_name, zh_name FROM item "
                    "WHERE en_name LIKE ? OR zh_name LIKE ? "
                    "ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END, LENGTH(en_name), type_id LIMIT 10",
                    (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%")
                )
            result = []
            for tid, en, zh in c.fetchall():
                zh_name = zh or en or str(tid)
                display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or 'Unknown'}"
                result.append((tid, display, zh_name))
            self.finished_signal.emit(result)


class OrderFetchWorker(QThread):
    """后台获取 ESI 订单数据"""
    finished_signal = Signal(int, list, list)  # type_id, buy_orders, sell_orders
    error_signal = Signal(int, str)  # type_id, error

    def __init__(self, type_id: int, parent=None):
        super().__init__(parent)
        self._type_id = type_id

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            buy, sell = loop.run_until_complete(self._fetch())
            loop.close()
            self.finished_signal.emit(self._type_id, buy, sell)
        except Exception as e:
            self.error_signal.emit(self._type_id, str(e))

    async def _fetch(self):
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"},
            timeout=timeout
        ) as session:
            url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/"
            async with session.get(url, params={"type_id": self._type_id, "order_type": "buy"}) as resp:
                resp.raise_for_status()
                buy_data = await resp.json()
            async with session.get(url, params={"type_id": self._type_id, "order_type": "sell"}) as resp:
                resp.raise_for_status()
                sell_data = await resp.json()

        buy_orders = sorted(buy_data, key=lambda o: o["price"], reverse=True)[:5]
        sell_orders = sorted(sell_data, key=lambda o: o["price"])[:5]

        all_loc_ids = set()
        for o in buy_orders + sell_orders:
            all_loc_ids.add(o["location_id"])

        await self._resolve_names(list(all_loc_ids))
        return buy_orders, sell_orders

    async def _resolve_names(self, location_ids: list[int]):
        need = [lid for lid in location_ids if lid not in _station_name_cache]
        if not need:
            return
        url = f"{ESI_BASE_URL}/universe/names/"
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"},
            timeout=timeout
        ) as session:
            for i in range(0, len(need), 1000):
                chunk = need[i:i + 1000]
                try:
                    async with session.post(url, json=chunk) as resp:
                        if resp.status == 200:
                            for item in await resp.json():
                                _station_name_cache[item["id"]] = item.get("name", str(item["id"]))
                        else:
                            for lid in chunk:
                                _station_name_cache.setdefault(lid, str(lid))
                except Exception:
                    for lid in chunk:
                        _station_name_cache.setdefault(lid, str(lid))


class GroupLoadWorker(QThread):
    """加载类别列表"""
    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        with _query_db.connect('ref') as conn:
            c = conn.cursor()
            c.execute("SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name FROM item e WHERE e.group_id IS NOT NULL ORDER BY e.zh_group_name, e.en_group_name")
            result = c.fetchall()
            self.finished_signal.emit(result)


# ═══════════════════════════════════════
#  Popup dialogs
# ═══════════════════════════════════════

class SuggestionPopup(QDialog):
    """悬浮候选列表 — 出现在搜索框下方"""
    item_selected = Signal(int, str)  # type_id, zh_name

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
        for tid, display, zh_name in items:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setData(Qt.ItemDataRole.UserRole + 1, zh_name)
            self._list.addItem(item)
        h = min(len(items) * 28 + 8, 220)
        self._list.setFixedHeight(h)
        self.setFixedSize(width, h)
        self.move(pos)
        self.show()

    def show_history(self, history: list, pos: QPoint, width: int):
        self._list.clear()
        for h in history[:8]:
            q = h["query"]
            item = QListWidgetItem(f"🕐  {q}")
            item.setData(Qt.ItemDataRole.UserRole, q)
            self._list.addItem(item)
        h = min((len(history) + 2) * 28 + 8, 220)
        self._list.setFixedHeight(h)
        self.setFixedSize(width, h)
        self.move(pos)
        self.show()

    def _on_clicked(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        name = item.data(Qt.ItemDataRole.UserRole + 1) or item.data(Qt.ItemDataRole.UserRole) or ""
        self.hide()
        self.item_selected.emit(tid, name)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and obj is self._list:
            key = event.key()
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                current = self._list.currentItem()
                if current:
                    self._on_clicked(current)
                return True
            elif key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)


class OrderPopup(QDialog):
    """悬浮订单详情 — 双击物品行时弹出，点击外部自动关闭"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setMinimumSize(620, 480)
        self.setObjectName("order_popup")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self._title_label = QLabel("")
        self._title_label.setObjectName("order_title")
        layout.addWidget(self._title_label)

        # 买单 (上半区)
        buy_header = QLabel("买单 (Buy)")
        buy_header.setObjectName("buy_header")
        layout.addWidget(buy_header)
        self._buy_list = QListWidget()
        self._buy_list.setObjectName("buy_list")
        layout.addWidget(self._buy_list)

        # 卖单 (下半区)
        sell_header = QLabel("卖单 (Sell)")
        sell_header.setObjectName("sell_header")
        layout.addWidget(sell_header)
        self._sell_list = QListWidget()
        self._sell_list.setObjectName("sell_list")
        layout.addWidget(self._sell_list)

    def set_orders(self, type_id: int, name: str, buy_orders: list, sell_orders: list):
        self._title_label.setText(f"{name} (Type ID: {type_id})")

        self._buy_list.clear()
        if buy_orders:
            for i, order in enumerate(buy_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station = _station_name_cache.get(loc_id, str(loc_id))
                item = QListWidgetItem(f"#{i+1}  {price} ISK  ×{vol}   {station} [{loc_id}]")
                item.setForeground(QColor(GREEN))
                self._buy_list.addItem(item)
        else:
            item = QListWidgetItem("无买单数据")
            item.setForeground(QColor(TEXT_SECONDARY))
            self._buy_list.addItem(item)

        self._sell_list.clear()
        if sell_orders:
            for i, order in enumerate(sell_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station = _station_name_cache.get(loc_id, str(loc_id))
                item = QListWidgetItem(f"#{i+1}  {price} ISK  ×{vol}   {station} [{loc_id}]")
                item.setForeground(QColor(RED))
                self._sell_list.addItem(item)
        else:
            item = QListWidgetItem("无卖单数据")
            item.setForeground(QColor(TEXT_SECONDARY))
            self._sell_list.addItem(item)


# ═══════════════════════════════════════
#  Main Query Page
# ═══════════════════════════════════════

class QueryPage(QWidget):
    """物品查询页面"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("query_page")
        self._all_groups: list = []
        self._order_cache: dict[int, tuple] = {}
        self._current_query: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 搜索栏 ──
        search_bar = QWidget()
        search_bar.setObjectName("query_toolbar")
        sb_layout = QHBoxLayout(search_bar)
        sb_layout.setContentsMargins(12, 8, 12, 8)
        sb_layout.setSpacing(8)

        self._all_items_btn = QPushButton("📦 全物品")
        self._all_items_btn.setToolTip("打开全物品浏览器")
        self._all_items_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_SURFACE_LIGHT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {PRIMARY};
                color: white;
                border: 1px solid {PRIMARY};
            }}
        """)
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

        layout.addWidget(search_bar)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── 状态行 ──
        status_widget = QWidget()
        status_widget.setObjectName("query_status")
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 2, 0, 2)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        status_layout.addWidget(self._count_label)

        status_layout.addStretch()

        self._status_label = QLabel("输入物品名称/ID后搜索，双击行查看实时订单")
        self._status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        status_layout.addWidget(self._status_label)

        layout.addWidget(status_widget)

        # ── 表格 ──
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

        self._model = QueryTableModel()
        self._table.setModel(self._model)

        for i, (_, w) in enumerate(_COLUMNS):
            self._table.setColumnWidth(i, w)

        layout.addWidget(self._table)

        # ── 悬浮候选框 ──
        self._suggest_popup = SuggestionPopup(self)
        self._suggest_popup.item_selected.connect(self._on_suggest_popup_selected)

        # ── 悬浮订单框 ──
        self._order_popup: OrderPopup | None = None

        # ── 加载类别 ──
        self._load_groups()

        # ── 计时器：200ms 搜索防抖 ──
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._fetch_suggestions)

        # ── 当前订单类型ID ──
        self._current_order_type_id: int | None = None

        # ── 安装事件过滤器以隐藏弹出框 ──
        self._search_input.installEventFilter(self)

    # ═══════════════════════════════════════
    #  搜索
    # ═══════════════════════════════════════

    def _load_groups(self):
        worker = GroupLoadWorker(self)
        worker.finished_signal.connect(self._on_groups_loaded)
        worker.start()

    def _on_groups_loaded(self, groups: list):
        self._all_groups = groups

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

    # ─── 搜索历史 ───

    def _add_search_history(self, query: str):
        try:
            history = []
            if HISTORY_FILE.exists():
                history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            history = [h for h in history if h.get("query") != query]
            history.insert(0, {"query": query, "time": _time.time()})
            if len(history) > MAX_HISTORY:
                history = history[:MAX_HISTORY]
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_search_history(self) -> list:
        try:
            if HISTORY_FILE.exists():
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _show_search_history(self):
        history = self._load_search_history()
        if not history:
            self._suggest_popup.hide()
            return
        pos = self._search_input.mapToGlobal(QPoint(0, self._search_input.height()))
        self._suggest_popup.show_history(history, pos, self._search_input.width())

    def _clear_search_history(self):
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text("[]", encoding="utf-8")
        except Exception:
            pass
        self._suggest_popup.hide()

    # ─── 执行搜索 ───

    def _do_search(self):
        query = self._search_input.text().strip()
        self._suggest_popup.hide()
        if not query:
            self._status_label.setText("请输入物品名称或 ID")
            return

        self._current_query = query
        self._add_search_history(query)
        self._hide_order_popup()
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # indeterminate

        worker = SearchWorker(query, self._all_groups, self)
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

        parsed = []
        for row in rows:
            if is_fallback:
                tid, zh, en, zhg, eng, vol = row[:6]
                buy_p = sell_p = None
                buy_v = sell_v = 0
            else:
                tid, zh, en, en_group, zh_group, volume, buy_p, sell_p, buy_v, sell_v = row
                buy_v = buy_v or 0
                sell_v = sell_v or 0
                vol = volume or 0.0

            group = (zh_group or en_group or "—") if not is_fallback else (zhg or eng or "—")

            buy_str = "—"
            if buy_p is not None and buy_v > 0:
                buy_str = f"{buy_p:,.2f} ({buy_v:,})"
            elif buy_p is not None:
                buy_str = f"{buy_p:,.2f}"

            sell_str = "—"
            if sell_p is not None and sell_v > 0:
                sell_str = f"{sell_p:,.2f} ({sell_v:,})"
            elif sell_p is not None:
                sell_str = f"{sell_p:,.2f}"

            avg_price_str = "—"
            avg_price_val = 0.0
            if buy_p is not None and sell_p is not None:
                avg_price_val = (buy_p + sell_p) / 2
                avg_price_str = f"{avg_price_val:,.2f}"
            elif buy_p is not None:
                avg_price_val = buy_p
                avg_price_str = f"{buy_p:,.2f}"
            elif sell_p is not None:
                avg_price_val = sell_p
                avg_price_str = f"{sell_p:,.2f}"

            buy_val = buy_p if buy_p is not None else 0.0
            sell_val = sell_p if sell_p is not None else 0.0
            is_inverted = buy_p is not None and sell_p is not None and buy_p > sell_p

            parsed.append({
                "type_id": tid, "zh": zh or "", "en": en or "", "group": group,
                "buy_str": buy_str, "sell_str": sell_str,
                "buy_val": buy_val, "sell_val": sell_val,
                "avg_price_str": avg_price_str, "avg_price_val": avg_price_val,
                "vol_str": f"{vol:,.2f}" if vol > 0 else "—",
                "vol_val": vol, "is_inverted": is_inverted,
            })

        self._model.set_rows(parsed)
        self._count_label.setText(f"共 {len(rows)} 条结果" + (" (仅基本信息)" if is_fallback else ""))
        self._status_label.setText("就绪 — 右键行可查看操作菜单，双击查看实时订单")

        # Restore column widths
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
        self._hide_order_popup()
        self._suggest_popup.hide()

    # ═══════════════════════════════════════
    #  右键菜单
    # ═══════════════════════════════════════

    def _on_context_menu(self, pos: QPoint):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        row_data = self._model.get_row(index.row())
        if not row_data:
            return

        type_id = row_data["type_id"]
        zh_name = row_data.get("zh", "")
        en_name = row_data.get("en", "")
        buy_price = row_data.get("buy_str", "—")
        sell_price = row_data.get("sell_str", "—")

        menu = QMenu(self)
        menu.setObjectName("view_menu")

        # ── 复制组 ──
        copy_name = QAction(f"复制名称: {zh_name or en_name}", self)
        copy_name.triggered.connect(lambda: self._copy_to_clipboard(zh_name or en_name or str(type_id)))
        menu.addAction(copy_name)

        copy_id = QAction(f"复制 Type ID: {type_id}", self)
        copy_id.triggered.connect(lambda: self._copy_to_clipboard(str(type_id)))
        menu.addAction(copy_id)

        if buy_price != "—":
            copy_buy = QAction(f"复制买单价格: {buy_price.split(' (')[0]} ISK", self)
            copy_buy.triggered.connect(lambda: self._copy_to_clipboard(buy_price.split(" (")[0]))
            menu.addAction(copy_buy)

        if sell_price != "—":
            copy_sell = QAction(f"复制卖单价格: {sell_price.split(' (')[0]} ISK", self)
            copy_sell.triggered.connect(lambda: self._copy_to_clipboard(sell_price.split(" (")[0]))
            menu.addAction(copy_sell)

        menu.addSeparator()

        # ── 操作组 ──
        view_orders = QAction("查看实时订单", self)
        view_orders.triggered.connect(lambda: self._load_orders(type_id))
        menu.addAction(view_orders)

        view_manufacturing = QAction("查看制造配方", self)
        view_manufacturing.triggered.connect(lambda: self._view_manufacturing(type_id))
        menu.addAction(view_manufacturing)

        menu.addSeparator()

        # ── 快捷操作 ──
        copy_all = QAction("复制整行 (TSV)", self)
        copy_all.triggered.connect(lambda: self._copy_row_tsv(row_data))
        menu.addAction(copy_all)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_to_clipboard(self, text: str):
        QApplication.instance().clipboard().setText(text)
        self._status_label.setText(f"已复制: {text}")

    def _copy_row_tsv(self, row_data: dict):
        parts = [
            str(row_data.get("type_id", "")),
            row_data.get("zh", ""),
            row_data.get("en", ""),
            row_data.get("group", ""),
            row_data.get("buy_str", "—"),
            row_data.get("sell_str", "—"),
            row_data.get("avg_price_str", "—"),
            row_data.get("vol_str", "—"),
        ]
        text = "\t".join(parts)
        QApplication.instance().clipboard().setText(text)
        self._status_label.setText("已复制整行数据 (TSV 格式)")

    def _view_manufacturing(self, type_id: int):
        # Switch to industry page
        self._main._nav_tree.setCurrentItem(self._main._nav_items[1])  # industry
        self._status_label.setText(f"切换到工业页查看 Type ID: {type_id}")

    # ═══════════════════════════════════════
    #  订单弹窗（浮窗）
    # ═══════════════════════════════════════

    def _on_row_double_click(self, index: QModelIndex):
        row_data = self._model.get_row(index.row())
        if not row_data:
            return
        type_id = row_data["type_id"]
        self._load_orders(type_id)

    def _load_orders(self, type_id: int):
        self._current_order_type_id = type_id

        name = str(type_id)
        for i in range(self._model.rowCount()):
            row = self._model.get_row(i)
            if row and row["type_id"] == type_id:
                name = f"{row['zh']} ({row['en']})" if row['zh'] and row['en'] else (row['zh'] or row['en'] or str(type_id))
                break

        # 显示弹窗并立即展示缓存数据（如有）
        self._show_order_popup(type_id, name)

        cached = self._order_cache.get(type_id)
        if cached:
            buy_orders, sell_orders, fetch_time = cached
            if _time.time() - fetch_time < 300:
                self._order_popup.set_orders(type_id, name, buy_orders, sell_orders)
                self._status_label.setText("订单数据已加载（缓存）")
                return

        self._status_label.setText("正在从 ESI 获取实时订单...")
        worker = OrderFetchWorker(type_id, self)
        worker.finished_signal.connect(self._on_orders_fetched)
        worker.error_signal.connect(self._on_order_error)
        worker.start()

    def _show_order_popup(self, type_id: int, name: str):
        if self._order_popup:
            self._order_popup.hide()
            self._order_popup.deleteLater()
        self._order_popup = OrderPopup(self)
        self._order_popup.set_orders(type_id, name, [], [])
        # Position near center of this page
        center = self.mapToGlobal(self.rect().center())
        self._order_popup.move(center.x() - 275, center.y() - 200)
        self._order_popup.show()

    def _on_orders_fetched(self, type_id: int, buy_orders: list, sell_orders: list):
        self._order_cache[type_id] = (buy_orders, sell_orders, _time.time())
        if type_id == self._current_order_type_id and self._order_popup and self._order_popup.isVisible():
            name = str(type_id)
            for i in range(self._model.rowCount()):
                row = self._model.get_row(i)
                if row and row["type_id"] == type_id:
                    name = f"{row['zh']} ({row['en']})" if row['zh'] and row['en'] else (row['zh'] or row['en'] or str(type_id))
                    break
            self._order_popup.set_orders(type_id, name, buy_orders, sell_orders)
            self._status_label.setText("实时订单数据已加载")

    def _on_order_error(self, type_id: int, error: str):
        if type_id == self._current_order_type_id:
            self._status_label.setText(f"获取订单失败: {error}")

    def _hide_order_popup(self):
        if self._order_popup:
            self._order_popup.hide()
            self._order_popup.deleteLater()
            self._order_popup = None
        self._current_order_type_id = None

    # ═══════════════════════════════════════
    #  Public API
    # ═══════════════════════════════════════

    def _open_all_items(self):
        from ui_pyside6.views.all_items_view import AllItemsDialog
        if not hasattr(self, '_all_items_dialog') or self._all_items_dialog is None:
            self._all_items_dialog = AllItemsDialog(self)
        self._all_items_dialog.show()
        self._all_items_dialog.raise_()

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

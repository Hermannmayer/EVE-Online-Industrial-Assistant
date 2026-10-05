"""全物品市场 — 后台 Worker（市场树 / 物品列表 / 搜索）"""

from PySide6.QtCore import QThread, Signal

from core.constants import TRADE_HUB_IDS
from services.market_browser_service import fetch_items, fetch_market_tree, search_items

JITA_RID = TRADE_HUB_IDS["Jita"]


class TreeW(QThread):
    done = Signal(list)

    def run(self):
        self.done.emit(fetch_market_tree())


class ItemsW(QThread):
    done = Signal(list)

    def __init__(self, ids=None, rid: int = 0, parent=None, manufacturable_only: bool = False):
        super().__init__(parent)
        self._ids = ids
        self._rid = rid
        #: 「可制造物品」窗口传 True → 过滤下推到 SQL（见 `fetch_items`）；
        #: 全物品窗口保持默认 False，行为不变。
        self._manufacturable_only = bool(manufacturable_only)

    def run(self):
        self.done.emit(fetch_items(self._ids, self._rid or JITA_RID, self._manufacturable_only))


class SearchItemsW(QThread):
    """按名称/ID 搜索物品"""

    done = Signal(list)

    def __init__(self, query: str, rid: int, parent=None):
        super().__init__(parent)
        self._query = query
        self._rid = rid

    def run(self):
        self.done.emit(search_items(self._query, self._rid or JITA_RID))

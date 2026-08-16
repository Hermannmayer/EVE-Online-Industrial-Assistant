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

    def __init__(self, ids=None, rid: int = 0, parent=None):
        super().__init__(parent)
        self._ids = ids
        self._rid = rid

    def run(self):
        self.done.emit(fetch_items(self._ids, self._rid or JITA_RID))


class SearchItemsW(QThread):
    """按名称/ID 搜索物品"""

    done = Signal(list)

    def __init__(self, query: str, rid: int, parent=None):
        super().__init__(parent)
        self._query = query
        self._rid = rid

    def run(self):
        self.done.emit(search_items(self._query, self._rid or JITA_RID))

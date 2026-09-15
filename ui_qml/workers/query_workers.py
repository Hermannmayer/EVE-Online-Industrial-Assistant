"""查询页的取数线程（搜索 / 候选 / 类别树）。

原先在 `ui_pyside6/views/query/query_search.py`，QML 侧要用同一份，故拆出来。
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from services.ui_data_service import (
    load_item_groups,
    query_search_items,
    query_search_items_basic,
    query_suggest_items,
)


class SearchWorker(QThread):
    """后台数据库搜索"""

    finished_signal = Signal(list, bool)  # rows, is_fallback
    error_signal = Signal(str)

    def __init__(self, query: str, all_groups: list, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._query = query
        self._region_id = region_id
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
        return query_search_items(query, self._all_groups, self._region_id, db=get_container().db)

    def _db_search_basic(self, query: str):
        return query_search_items_basic(query, db=get_container().db)


class SuggestionWorker(QThread):
    """后台候选搜索"""

    finished_signal = Signal(list)  # list of (type_id, display, zh_name)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        rows = query_suggest_items(self._query, db=get_container().db)
        result = []
        for tid, en, zh in rows:
            zh_name = zh or en or str(tid)
            display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or 'Unknown'}"
            result.append((tid, display, zh_name))
        self.finished_signal.emit(result)


class GroupLoadWorker(QThread):
    """加载类别列表"""

    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            self.finished_signal.emit(load_item_groups(db=get_container().db))
        except Exception:
            self.finished_signal.emit([])

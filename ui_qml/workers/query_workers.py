"""查询页的取数线程（搜索 / 候选）。

原先在 `ui_pyside6/views/query/query_search.py`，QML 侧要用同一份，故拆出来。
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from services.ui_data_service import (
    query_search_items,
    query_search_items_basic,
    query_suggest_items,
)


class SearchWorker(QThread):
    """后台数据库搜索"""

    finished_signal = Signal(list, bool)  # rows, is_fallback
    error_signal = Signal(str)

    def __init__(self, query: str, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._query = query
        self._region_id = region_id

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
        return query_search_items(query, self._region_id, db=get_container().db)

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
            #: 展示串就用**物品名**（中文优先 → 英文 → ID）。原先拼的是 `[17715] 毒蜥级 (Gila)`，
            #: 一行里塞了 Type ID 与中英双名，候选列表读起来很杂；英文名对中文用户也没用处。
            name = zh or en or str(tid)
            #: 第二项是展示串、第三项是**可搜的查询串**。两者现在同值，但接口不合并 ——
            #: 展示串以后怎么改都不该动到拿去 `LIKE` 匹配的那串（见 `QueryBridge.pickSuggestion`）。
            result.append((tid, name, name))
        self.finished_signal.emit(result)

"""查询页的取数线程（候选）。

原先在 `ui_pyside6/views/query/query_search.py`，QML 侧要用同一份，故拆出来。

**只剩候选一条**：结果表已按用户要求删除，页面形态变成「输入即出全部匹配，点一条出详情」，
所以按名字跑整表搜索的 `SearchWorker` 也随之删除（它连带让
`ui_data_service.query_search_items` / `_basic` 变成死代码，一并清掉）。
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from services.ui_data_service import query_suggest_items


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

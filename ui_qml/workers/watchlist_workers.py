"""关注列表的候选搜索线程（原先在 `ui_pyside6/views/watchlist_view.py`）。"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class SuggestionWorker(QThread):
    """后台候选搜索"""

    finished_signal = Signal(list)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        q = self._query.strip()
        if not q:
            self.finished_signal.emit([])
            return
        repo = get_container().item_repo
        if q.isdigit():
            item = repo.get_by_id(int(q))
            items = [item] if item else repo.search_by_name(q, limit=10)
        else:
            items = repo.search_by_name(q, limit=10)
        result = []
        for it in items:
            tid = it["type_id"]
            zh = it["zh_name"] or ""
            en = it["en_name"] or ""
            display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or str(tid)}"
            result.append((tid, display))
        self.finished_signal.emit(result)


# ═══════════════════════════════════════
#  候选列表弹窗
# ═══════════════════════════════════════

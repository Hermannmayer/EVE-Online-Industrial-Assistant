"""
评分 Worker 基类 — 统一 QThread 模板，消除重复代码

用法:
    class MyScoreWorker(BaseScoreWorker):
        def _compute(self) -> dict:
            return calc_xxx_score(type_id=self._type_id, ...)
"""

from PySide6.QtCore import QThread, Signal

from services.char_config_resolver import resolve_char_config


class BaseScoreWorker(QThread):
    """单物品评分 Worker 基类 — 子类实现 _compute() → dict"""

    finished = Signal(dict)

    def __init__(self, type_id: int, *, char_config=None, char_name=None, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._char_config = resolve_char_config(char_name=char_name, char_data=char_config)

    def run(self):
        try:
            result = self._compute()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({"status": f"error: {e}"})

    def _compute(self) -> dict:
        raise NotImplementedError


class BaseBatchScoreWorker(QThread):
    """批量评分 Worker 基类 — 子类实现 _batch_calc(item) → dict"""

    progress = Signal(int, int)
    result = Signal(list)
    done = Signal(float)

    def __init__(self, items: list, *, char_config=None, char_name=None, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._char_config = resolve_char_config(char_name=char_name, char_data=char_config)

    def run(self):
        import time

        started = time.time()
        results = []
        total = len(self._items)
        for i, item in enumerate(self._items):
            if self.isInterruptionRequested():
                return
            try:
                r = self._calc_item(item)
                results.append(r)
            except Exception:
                results.append(None)
            if (i + 1) % 50 == 0 or i == total - 1:
                self.progress.emit(i + 1, total)
        self.result.emit(results)
        self.done.emit(time.time() - started)

    def _calc_item(self, item) -> dict:
        raise NotImplementedError

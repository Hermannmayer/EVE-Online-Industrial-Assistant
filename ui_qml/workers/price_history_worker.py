"""价格历史取数线程（原先在 `ui_pyside6/views/price_chart.py`）。"""

import asyncio

from PySide6.QtCore import QThread, Signal

from services.price_history import fetch_history, get_cached_history, save_cache


class PriceHistoryWorker(QThread):
    """后台线程：获取价格历史数据"""

    finished_signal = Signal(int, list)  # type_id, data
    error_signal = Signal(int, str)  # type_id, error

    def __init__(self, type_id: int, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._region_id = region_id

    def run(self):
        try:
            # Try cache first
            data = get_cached_history(self._type_id, self._region_id)
            if data is not None:
                self.finished_signal.emit(self._type_id, data)
                return

            # Fetch from ESI
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                data = loop.run_until_complete(fetch_history(self._type_id, self._region_id))
            finally:
                loop.close()

            if data is None:
                self.error_signal.emit(self._type_id, "无历史数据")
                return

            save_cache(self._type_id, self._region_id, data)
            self.finished_signal.emit(self._type_id, data)
        except Exception as e:
            self.error_signal.emit(self._type_id, str(e))

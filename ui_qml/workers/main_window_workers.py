"""主窗口后台 Worker — 价格更新与价格时效检查。

从 ui_pyside6/main_window.py 拆出，降低主窗口上帝类体积。
"""

from datetime import UTC, datetime

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from core.logger import log


def needs_price_update(diff_seconds: float, interval_minutes: int) -> bool:
    """价格是否过期需要更新（纯函数）。

    diff_seconds: 距上次成功更新的秒数；interval_minutes: 更新间隔（分钟）。
    带 60s 容差：旧实现用严格 `> interval`，更新后下一次 tick 的 diff≈interval 必然被跳过，
    导致实际 ~2×interval 才更新。加容差后固定网格定时器每次 tick 都能稳定触发。
    """
    return diff_seconds >= interval_minutes * 60 - 60


class PriceUpdateWorker(QThread):
    """后台线程执行价格更新"""

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, regions: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._regions = regions

    def run(self):
        try:
            from services.importers.getprices import run_price_update

            run_price_update(self._regions)
            self.finished_signal.emit(True, "价格更新完成")
        except Exception as e:
            log.exception("价格更新数据一致性检查失败: %s", e)
            self.finished_signal.emit(False, str(e))


class PriceCheckWorker(QThread):
    """后台线程检查价格数据时效"""

    result = Signal(bool, str)  # needs_update, status_text

    def __init__(self, interval_minutes: int = 30, parent=None):
        super().__init__(parent)
        self._interval = interval_minutes * 60

    def run(self):
        try:
            latest = get_container().market_repo.get_latest_fetch_time()
            if latest:
                utc_str = latest
                dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(UTC).replace(tzinfo=None)
                diff = (now_utc - dt).total_seconds()
                if needs_price_update(diff, self._interval // 60):
                    self.result.emit(True, f"价格数据已过期 {diff / 60:.0f} 分钟，需要更新")
                else:
                    self.result.emit(False, f"价格数据 {(diff / 60):.0f} 分钟前更新，无需更新")
            else:
                self.result.emit(True, "无价格数据，需要更新")
        except Exception as ex:
            log.exception("价格数据时效性检查失败: %s", ex)
            self.result.emit(False, f"价格检查失败: {ex}")

"""贸易页面 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from core.logger import log
from services.market_browser_service import fetch_cross_region_spread, fetch_hub_order_change

_LIVE_WORKERS: set[QThread] = set()


def spawn(worker: QThread) -> QThread:
    """保活运行中的排行线程，避免桥替换引用时 QThread 被提前析构。"""
    _LIVE_WORKERS.add(worker)
    worker.finished.connect(lambda: _LIVE_WORKERS.discard(worker))
    worker.start()
    return worker


class CrossRegionRankWorker(QThread):
    """A → B 全品类价差排行（含 B 侧挂单变化 + 两端的日成交量）。"""

    finished_signal = Signal(list)
    failed_signal = Signal(str)

    def __init__(
        self,
        region_a: int,
        region_b: int,
        side_a: str = "sell",
        side_b: str = "buy",
        group_ids: list[int] | None = None,
        change_days: int = 7,
        parent=None,
    ):
        super().__init__(parent)
        self._region_a = region_a
        self._region_b = region_b
        self._side_a = side_a
        self._side_b = side_b
        self._group_ids = group_ids
        self._change_days = change_days

    def run(self):
        try:
            rows = fetch_cross_region_spread(
                self._region_a,
                self._region_b,
                side_a=self._side_a,
                side_b=self._side_b,
                group_ids=self._group_ids,
            )
            # 挂单变化只算目的中心：要回答的是「挂上去之后卖不卖得动」。
            change = fetch_hub_order_change(self._region_b, days=self._change_days)
            for row in rows:
                info = change.get(row["id"])
                row["chg"] = info["per_day"] if info else None
                row["chg_days"] = info["days"] if info else 0
            self._attach_volumes(rows)
            self.finished_signal.emit(rows)
        except Exception as ex:
            log.exception("跨区域价差排行失败")
            self.failed_signal.emit(str(ex))

    def _attach_volumes(self, rows: list[dict]) -> None:
        """两端各自的近 7 日平均成交量 —— **只读本地 `price_history`，零 ESI 请求**。

        数据由主界面「更新价格」按**它同步的那些中心**统一拉取（`fetch_and_save_histories`），
        本页只按当前选的起点/终点区域取缓存；缺数据或本地历史过期 → `None` → 表格 `—`。
        """
        if not rows:
            return
        from services.price_history import get_history_summary

        ids = [row["id"] for row in rows]
        for key, region_id in (("vola", self._region_a), ("volb", self._region_b)):
            summary = get_history_summary(ids, region_id=region_id, days=self._change_days)
            for row in rows:
                item = summary.get(row["id"])
                row[key] = item["vol"] if item else None

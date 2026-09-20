"""贸易页面 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from services.market_browser_service import fetch_cross_region_spread, fetch_hub_order_change


class CrossRegionRankWorker(QThread):
    """A → B 全品类价差排行（含 B 侧挂单变化）。"""

    finished_signal = Signal(list)

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
        self.finished_signal.emit(rows)

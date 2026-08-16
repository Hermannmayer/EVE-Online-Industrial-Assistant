"""工业页专用后台 Worker 与初始化辅助。"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from core.logger import log


class IndustryDataWorker(QThread):
    """后台线程拉取工业系统成本指数 + 设施数据"""

    finished = Signal(bool, str)  # success, message

    def run(self):
        try:
            from services.importers.getindustry import run_industry_update

            asyncio.run(run_industry_update())
            self.finished.emit(True, "工业数据拉取完成")
        except Exception as e:
            log.exception("工业数据拉取失败: %s", e)
            self.finished.emit(False, str(e))


def init_plan_db():
    """初始化 production_plans 表。

    production_plans 的 schema 单一来源是 PlanRepository.SCHEMA；
    price_snapshots 已由 schema_migrations user v10→v11 统一管理，不再在 UI 层建表。
    """
    try:
        get_container().plan_repo.ensure_table()
    except Exception:
        log.exception("初始化生产计划数据库失败")


class PlanPriceRefreshWorker(QThread):
    """定向拉取计划涉及物品的 ESI 市场价格——带 5 分钟缓存"""

    finished = Signal(bool, str)  # success, message

    def __init__(self, type_ids: set[int], parent=None):
        super().__init__(parent)
        self._type_ids = type_ids

    def run(self):
        try:
            count = asyncio.run(self._fetch_and_save())
            if count == 0:
                self.finished.emit(True, "价格数据在缓存有效期内（5分钟），直接使用缓存数据")
            else:
                self.finished.emit(True, f"已刷新 {count} 个物品的价格")
        except Exception as e:
            log.exception("定向价格刷新失败")
            self.finished.emit(False, str(e))

    async def _fetch_and_save(self) -> int:
        """异步拉取 ESI + 写入 market.db（仅拉取缓存过期的物品）"""
        from services.client import APIClient
        from services.price_refresh_service import check_stale_type_ids, save_refreshed_prices

        stale_ids = await check_stale_type_ids(self._type_ids)

        if not stale_ids:
            log.info("定向价格: 所有物品均在缓存有效期内，跳过刷新")
            return 0

        ESI_BASE = "https://esi.evetech.net/latest"
        REGION_JITA = 10000002

        type_orders: dict[int, dict] = {}

        async with APIClient(timeout=180, concurrency=50) as client:
            async def fetch_item_orders(tid: int) -> tuple[int, dict]:
                url = f"{ESI_BASE}/markets/{REGION_JITA}/orders/"
                result: dict = {"buy_price": 0.0, "sell_price": float("inf"), "buy_volume": 0, "sell_volume": 0}

                async def fetch_one(order_type: str) -> list[dict]:
                    try:
                        data = await client.fetch_raw(f"{url}?type_id={tid}&order_type={order_type}")
                        return data if isinstance(data, list) else []
                    except Exception:
                        log.warning("拉取 %s type_id=%s 失败", order_type, tid)
                        return []

                buy_data, sell_data = await asyncio.gather(fetch_one("buy"), fetch_one("sell"))

                for o in buy_data:
                    if o["price"] > result["buy_price"]:
                        result["buy_price"] = o["price"]
                    result["buy_volume"] += o.get("volume_remain", 0)

                for o in sell_data:
                    if o["price"] < result["sell_price"]:
                        result["sell_price"] = o["price"]
                    result["sell_volume"] += o.get("volume_remain", 0)

                if result["sell_price"] == float("inf"):
                    result["sell_price"] = 0.0

                return tid, result

            tasks = [fetch_item_orders(tid) for tid in stale_ids]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)

            for g in gathered:
                if isinstance(g, Exception):
                    log.warning("物品订单拉取异常: %s", g)
                    continue
                tid, result = g  # type: ignore[misc]
                type_orders[tid] = result

        count = await save_refreshed_prices(type_orders, REGION_JITA)
        log.info("定向价格刷新完成: %s 个物品（缓存跳过 %s 个）", count, len(self._type_ids) - len(stale_ids))
        return count

"""工业页专用后台 Worker 与初始化辅助。"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from core.logger import log
from domain.market_depth import BUY, SELL, depth_price


class IndustryDataWorker(QThread):
    """后台线程拉取工业系统成本指数 + 设施数据"""

    finished_signal = Signal(bool, str)  # success, message

    def run(self):
        try:
            from services.importers.getindustry import run_industry_update

            asyncio.run(run_industry_update())
            self.finished_signal.emit(True, "工业数据拉取完成")
        except Exception as e:
            log.exception("工业数据拉取失败: %s", e)
            self.finished_signal.emit(False, str(e))


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

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, type_ids: set[int], parent=None):
        super().__init__(parent)
        self._type_ids = type_ids
        self._failed_count = 0

    def run(self):
        try:
            count = asyncio.run(self._fetch_and_save())
            if count == 0 and not self._failed_count:
                self.finished_signal.emit(True, "价格数据在缓存有效期内（5分钟），直接使用缓存数据")
            elif self._failed_count:
                # 02-08：部分物品拉取失败必须可见，不能把失败混成「已刷新 N 个」的绿色状态
                self.finished_signal.emit(
                    False, f"已刷新 {count} 个物品；{self._failed_count} 个拉取失败（网络/限流），稍后重试"
                )
            else:
                self.finished_signal.emit(True, f"已刷新 {count} 个物品的价格")
        except Exception as e:
            log.exception("定向价格刷新失败")
            self.finished_signal.emit(False, str(e))

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
        orders_url = f"{ESI_BASE}/markets/{REGION_JITA}/orders/"

        type_orders: dict[int, dict] = {}
        failed: list[int] = []

        async with APIClient(timeout=180, concurrency=50) as client:

            async def fetch_side(tid: int, order_type: str) -> list[dict] | None:
                """一个方向的全部页；None = 拉取失败（02-08），[] = 合法空（02-11 分页）。"""
                base = f"{orders_url}?type_id={tid}&order_type={order_type}"
                status, first, headers = await client.fetch_state(f"{base}&page=1")
                if status is None:
                    log.warning("拉取 %s type_id=%s 失败（网络/限流）", order_type, tid)
                    return None
                if status == 404:
                    return []
                try:
                    pages = min(int(headers.get("X-Pages", 1)), 20)
                except (TypeError, ValueError):
                    pages = 1
                rows = list(first or [])
                for page in range(2, pages + 1):
                    st, chunk, _ = await client.fetch_state(f"{base}&page={page}")
                    if st is None:
                        log.warning("拉取 %s type_id=%s 第 %s 页失败", order_type, tid, page)
                        return None
                    rows.extend(chunk or [])
                return rows

            async def fetch_item_orders(tid: int) -> tuple[int, dict] | None:
                buy_data, sell_data = await asyncio.gather(fetch_side(tid, "buy"), fetch_side(tid, "sell"))
                if buy_data is None or sell_data is None:
                    return None
                # 与全量更新同一套深度取价（domain/market_depth.py），
                # 否则本路径会把深度价打回最低价
                buy_levels = [(o["price"], o.get("volume_remain", 0)) for o in buy_data]
                sell_levels = [(o["price"], o.get("volume_remain", 0)) for o in sell_data]
                return tid, {
                    "buy_price": depth_price(buy_levels, BUY) or 0.0,
                    "sell_price": depth_price(sell_levels, SELL) or 0.0,
                    "buy_volume": sum(v for _, v in buy_levels),
                    "sell_volume": sum(v for _, v in sell_levels),
                }

            tasks = [fetch_item_orders(tid) for tid in stale_ids]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)

            for tid, g in zip(sorted(stale_ids), gathered, strict=True):
                if isinstance(g, Exception):
                    log.warning("物品订单拉取异常: %s", g)
                    failed.append(tid)
                    continue
                if g is None:
                    failed.append(tid)
                    continue
                _tid, result = g  # type: ignore[misc]
                type_orders[_tid] = result

        self._failed_count = len(failed)
        count = await save_refreshed_prices(type_orders, REGION_JITA)
        log.info(
            "定向价格刷新完成: %s 个物品（缓存跳过 %s 个，失败 %s 个）",
            count,
            len(self._type_ids) - len(stale_ids),
            len(failed),
        )
        return count

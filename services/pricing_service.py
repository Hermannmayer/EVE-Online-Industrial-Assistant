"""
统一定价查询服务 — 市场价格 + 成交量 + 系统成本指数 + adjusted price

数据来源：market.db（market_prices 单张表含价格/成交量/adjusted price）、
reference.db（industry_system_costs 系统成本指数）。
被 UI 财务/运费/精炼/BOM 展开消费（经 bootstrap 容器 get_container().pricing_service）。
注意：评分链路不经过本服务（走 scoring_service 模块级 get_price），改价需两边同步。
"""

from core.constants import TRADE_HUB_SYSTEM_IDS
from services.database_manager import DatabaseManager
from services.repositories.market_repository import MarketRepository


def trade_hub_to_system_id(hub: str) -> int | None:
    """将贸易中心名称映射为太阳系 ID。"""
    return TRADE_HUB_SYSTEM_IDS.get(hub)


class PricingService:
    """统一定价查询"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._market_repo = MarketRepository(db)

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        return self._market_repo.get_price(type_id, price_type, hub)

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
        return self._market_repo.get_volume(type_id, vol_type, hub)

    def get_system_cost_index(self, system_id: int | None, activity: str = "manufacturing", hub: str = "Jita") -> float:
        """获取系统成本指数。system_id=None 时从 hub 名称推断，查无/未知统一用默认 SCI。"""
        from core.constants import DEFAULT_SYSTEM_COST_INDEX

        if system_id is None:
            system_id = trade_hub_to_system_id(hub)
        if system_id is None:
            return DEFAULT_SYSTEM_COST_INDEX
        with self._db.connect("ref") as conn:
            r = conn.execute(
                "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
                (system_id, activity),
            ).fetchone()
            return float(r[0]) if r else DEFAULT_SYSTEM_COST_INDEX

    def get_adjusted_price(self, type_id: int) -> float | None:
        """获取 ESI adjusted price（EIV 计算用）"""
        return self._market_repo.get_adjusted_price(type_id)

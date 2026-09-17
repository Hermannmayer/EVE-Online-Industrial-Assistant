"""
统一定价查询服务 — 市场价格 + 成交量 + 系统成本指数 + adjusted price

数据来源：market.db（market_prices 单张表含价格/成交量/adjusted price）、
reference.db（industry_system_costs 系统成本指数）。
被 UI 财务/运费/精炼/BOM 展开消费（经 bootstrap 容器 get_container().pricing_service）。

**取价的单一定义处**在 `services/repositories/market_repository.py`，本类只做转发。
评分链路（`scoring_service` 的模块级同名函数）也已合流到同一份实现 ——
原先两处各有一份等价 SQL，那条注释「改价需两边同步」记的就是这个分裂，
它已实际导致过缓存串值缺陷（见 `scoring_service._batch_materials` 的注释）。
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
        return self._market_repo.get_system_cost_index(system_id, activity, hub)

    def get_adjusted_price(self, type_id: int) -> float | None:
        """获取 ESI adjusted price（EIV 计算用）"""
        return self._market_repo.get_adjusted_price(type_id)

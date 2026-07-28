"""
定价查询服务 — 市场价格 + 成交量 + 系统成本指数

替代 scoring_service.py 中的模块级 get_price/get_volume/get_system_cost_index。
"""

from services.database_manager import DatabaseManager
from services.repositories.market_repository import MarketRepository

# 贸易中心 → 太阳系 ID 映射（用于 SCI 查询）
_TRADE_HUB_SYSTEM_IDS: dict[str, int] = {
    "Jita": 30000142,
    "Amarr": 30002187,
    "Dodixie": 30002659,
    "Rens": 30002510,
    "Hek": 30002070,
}


def trade_hub_to_system_id(hub: str) -> int | None:
    """将贸易中心名称映射为太阳系 ID。"""
    return _TRADE_HUB_SYSTEM_IDS.get(hub)


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
        """获取系统成本指数。system_id=None 时从 hub 名称推断。"""
        if system_id is None:
            system_id = trade_hub_to_system_id(hub)
        if system_id is None:
            return 0.05  # 兜底 5%
        with self._db.connect("ref") as conn:
            r = conn.execute(
                "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
                (system_id, activity),
            ).fetchone()
            return float(r[0]) if r else 1.0

    def get_adjusted_price(self, type_id: int) -> float | None:
        """获取 ESI adjusted price（EIV 计算用）"""
        return self._market_repo.get_adjusted_price(type_id)

"""市场价格数据查询仓库"""

from __future__ import annotations

from core.constants import TRADE_HUB_IDS


class MarketRepository:
    """市场价格只读查询"""

    def __init__(self, db):
        self._db = db

    VALID_PRICE_COLS = {"buy": "buy_price", "sell": "sell_price"}

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        """获取指定区域的价格。price_type: 'buy' / 'sell'"""
        col = self.VALID_PRICE_COLS.get(price_type)
        if col is None:
            return None
        with self._db.connect("mkt") as conn:
            if hub:
                rid = TRADE_HUB_IDS.get(hub, TRADE_HUB_IDS["Jita"])
                r = conn.execute(
                    f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                    (type_id, rid),
                ).fetchone()
                if r and r[0] is not None:
                    return float(r[0])
                # 降级：该区域无数据，尝试其他区域
                r = conn.execute(
                    f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                    (type_id,),
                ).fetchone()
            else:
                r = conn.execute(
                    f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                    (type_id,),
                ).fetchone()
            return float(r[0]) if r and r[0] is not None else None

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
        """获取成交量。vol_type: 'buy' / 'sell' / 'total'"""
        with self._db.connect("mkt") as conn:
            if hub:
                rid = TRADE_HUB_IDS.get(hub, TRADE_HUB_IDS["Jita"])
                r = conn.execute(
                    "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                    (type_id, rid),
                ).fetchone()
                if r and (r[0] or r[1]):
                    if vol_type == "total":
                        return int(r[0] + r[1])
                    return int(r[0] if vol_type == "buy" else r[1])
                r = conn.execute(
                    "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                    (type_id,),
                ).fetchone()
            else:
                r = conn.execute(
                    "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                    (type_id,),
                ).fetchone()
            if not r:
                return 0
            if vol_type == "buy":
                return r[0] or 0
            elif vol_type == "sell":
                return r[1] or 0
            return (r[0] or 0) + (r[1] or 0)

    def get_item_with_price(self, type_id: int) -> dict | None:
        """获取物品信息及其市场价格（跨库 JOIN）"""
        with self._db.connect("ref", "mkt") as conn:
            row = conn.execute(
                "SELECT i.type_id, i.name, i.group_id, mp.average_price "
                "FROM ref.item i LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id "
                "WHERE i.type_id = ?",
                (type_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_fetch_time(self) -> str | None:
        with self._db.connect("mkt") as conn:
            r = conn.execute("SELECT MAX(fetch_time) FROM market_prices").fetchone()
            return r[0] if r else None

    def get_adjusted_price(self, type_id: int) -> float | None:
        """获取 ESI adjusted_price（EIV 计算用）。列不存在时回退 sell_price。"""
        with self._db.connect("mkt") as conn:
            try:
                r = conn.execute(
                    "SELECT adjusted_price FROM market_prices WHERE type_id = ? AND adjusted_price > 0 LIMIT 1",
                    (type_id,),
                ).fetchone()
                return float(r[0]) if r else None
            except Exception:
                # 列不存在（旧数据库）→ 回退 sell_price
                r = conn.execute(
                    "SELECT sell_price FROM market_prices WHERE type_id = ? AND sell_price > 0 LIMIT 1",
                    (type_id,),
                ).fetchone()
                return float(r[0]) if r else None

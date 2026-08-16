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

    def get_latest_fetch_time(self) -> str | None:
        with self._db.connect("mkt") as conn:
            r = conn.execute("SELECT MAX(fetch_time) FROM market_prices").fetchone()
            return r[0] if r else None

    def get_prices_by_region(
        self, type_ids: list[int], region_id: int, price_type: str
    ) -> dict[int, float]:
        """批量获取指定区域价格（buy/sell/avg）。"""
        if not type_ids:
            return {}
        tids = list(dict.fromkeys(type_ids))
        ph = ",".join("?" * len(tids))
        result: dict[int, float] = {}
        with self._db.connect("mkt") as conn:
            if price_type == "avg":
                rows = conn.execute(
                    f"SELECT type_id, sell_price, buy_price FROM market_prices"
                    f" WHERE type_id IN ({ph}) AND region_id = ?",
                    (*tids, region_id),
                ).fetchall()
                for tid, sell, buy in rows:
                    if sell and buy:
                        result[int(tid)] = (sell + buy) / 2
                    elif sell or buy:
                        result[int(tid)] = sell or buy
            else:
                col = "sell_price" if price_type == "sell" else "buy_price"
                rows = conn.execute(
                    f"SELECT type_id, {col} FROM market_prices"
                    f" WHERE type_id IN ({ph}) AND region_id = ?",
                    (*tids, region_id),
                ).fetchall()
                for tid, price in rows:
                    if price is not None:
                        result[int(tid)] = float(price)
        return result

    def get_sell_prices(self, type_ids: list[int], region_id: int) -> dict[int, float]:
        """批量获取指定区域卖单价。"""
        if not type_ids:
            return {}
        with self._db.connect("mkt") as conn:
            ph = ",".join("?" * len(type_ids))
            rows = conn.execute(
                f"SELECT type_id, sell_price FROM market_prices "
                f"WHERE type_id IN ({ph}) AND region_id = ?",
                (*type_ids, region_id),
            ).fetchall()
            return {int(r[0]): float(r[1]) for r in rows if r[1]}

    def get_price_by_region(self, type_id: int, price_type: str, region_id: int) -> float | None:
        """获取指定区域的价格；price_type: 'buy' / 'sell' / 'avg'。"""
        with self._db.connect("mkt") as conn:
            if price_type == "avg":
                r = conn.execute(
                    "SELECT buy_price, sell_price FROM market_prices WHERE type_id=? AND region_id=? LIMIT 1",
                    (type_id, region_id),
                ).fetchone()
                if not r:
                    return None
                vals = [v for v in (r[0], r[1]) if v is not None]
                return float(sum(vals) / len(vals)) if vals else None
            col = self.VALID_PRICE_COLS.get(price_type)
            if col is None:
                return None
            r = conn.execute(
                f"SELECT {col} FROM market_prices WHERE type_id=? AND region_id=? LIMIT 1",
                (type_id, region_id),
            ).fetchone()
            return float(r[0]) if r and r[0] is not None else None

    def get_latest_price(self, type_id: int) -> tuple[float | None, float | None, int, int] | None:
        """获取指定物品最新一条价格记录 (buy_price, sell_price, buy_volume, sell_volume)。"""
        with self._db.connect("mkt") as conn:
            r = conn.execute(
                """
                SELECT buy_price, sell_price, buy_volume, sell_volume
                FROM market_prices
                WHERE type_id = ?
                ORDER BY fetch_time DESC
                LIMIT 1
                """,
                (type_id,),
            ).fetchone()
            if not r:
                return None
            return (r[0], r[1], int(r[2] or 0), int(r[3] or 0))

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

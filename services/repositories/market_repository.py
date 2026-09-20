"""市场价格数据查询仓库"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from core.constants import TRADE_HUB_IDS

#: SQLite 的绑定变量上限（`MAX_VARIABLE_NUMBER`，本机 32766）。`get_*_prices` 的
#: `IN (?)` 是按 type_id 个数拼的问号，合同页一次要几百上千个 —— 不分块会直接抛
#: `too many SQL variables`（实测 3.4 万个 type_id 必炸）。
_SQL_VAR_CHUNK = 500


def _chunked(ids: list[int]) -> Iterator[list[int]]:
    """按绑定变量上限切批，供批量查询的 `IN (?)` 使用。"""
    for i in range(0, len(ids), _SQL_VAR_CHUNK):
        yield ids[i : i + _SQL_VAR_CHUNK]


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

    def has_any_prices(self) -> bool:
        """市场价表是否已有任意价格数据。"""
        with self._db.connect("mkt") as conn:
            r = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()
            return bool(r and r[0] > 0)

    def get_batch_market_snapshot(
        self, type_ids: list[int], region_id: int
    ) -> dict[int, dict[str, float | int | None]]:
        """批量获取指定区域的市场价/量快照。

        返回 {type_id: {"bp": buy_price, "sp": sell_price, "bv": buy_volume, "sv": sell_volume}}。
        """
        if not type_ids:
            return {}
        ph = ",".join("?" * len(type_ids))
        result: dict[int, dict[str, float | int | None]] = {}
        with self._db.connect("mkt") as conn:
            rows = conn.execute(
                f"SELECT type_id, buy_price, sell_price, buy_volume, sell_volume "
                f"FROM market_prices WHERE region_id=? AND type_id IN ({ph})",
                (region_id, *type_ids),
            ).fetchall()
            for r in rows:
                result[int(r[0])] = {
                    "bp": r[1],
                    "sp": r[2],
                    "bv": r[3] or 0,
                    "sv": r[4] or 0,
                }
        return result

    def get_prices_by_region(self, type_ids: list[int], region_id: int, price_type: str) -> dict[int, float]:
        """批量获取指定区域价格（buy/sell/avg）。"""
        if not type_ids:
            return {}
        tids = list(dict.fromkeys(type_ids))
        result: dict[int, float] = {}
        avg = price_type == "avg"
        col = "sell_price" if price_type == "sell" else "buy_price"
        with self._db.connect("mkt") as conn:
            for chunk in _chunked(tids):
                ph = ",".join("?" * len(chunk))
                if avg:
                    rows = conn.execute(
                        f"SELECT type_id, sell_price, buy_price FROM market_prices"
                        f" WHERE type_id IN ({ph}) AND region_id = ?",
                        (*chunk, region_id),
                    ).fetchall()
                    for tid, sell, buy in rows:
                        if sell and buy:
                            result[int(tid)] = (sell + buy) / 2
                        elif sell or buy:
                            result[int(tid)] = sell or buy
                else:
                    rows = conn.execute(
                        f"SELECT type_id, {col} FROM market_prices WHERE type_id IN ({ph}) AND region_id = ?",
                        (*chunk, region_id),
                    ).fetchall()
                    for tid, price in rows:
                        if price is not None:
                            result[int(tid)] = float(price)
        return result

    def get_sell_prices(self, type_ids: list[int], region_id: int) -> dict[int, float]:
        """批量获取指定区域卖单价。"""
        if not type_ids:
            return {}
        tids = list(dict.fromkeys(type_ids))
        result: dict[int, float] = {}
        with self._db.connect("mkt") as conn:
            for chunk in _chunked(tids):
                ph = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT type_id, sell_price FROM market_prices WHERE type_id IN ({ph}) AND region_id = ?",
                    (*chunk, region_id),
                ).fetchall()
                result.update({int(r[0]): float(r[1]) for r in rows if r[1]})
        return result

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

    def get_adjusted_prices(self, type_ids: list[int]) -> dict[int, float] | None:
        """批量获取 adjusted price（EIV 用），只返回 > 0 的行 —— 与 get_adjusted_price 同口径。

        返回 ``None`` 表示**该库没有 adjusted_price 列**（旧库）：调用方必须回落单条查询，
        由后者按「列不存在 → 回退 sell_price」的既有语义处理。
        返回空 dict 表示「列在，但这些 type 都没有可用值」—— 那是有结论的答案，
        调用方不必再逐条查一遍。
        """
        if not type_ids:
            return {}
        tids = list(dict.fromkeys(type_ids))
        ph = ",".join("?" * len(tids))
        with self._db.connect("mkt") as conn:
            try:
                rows = conn.execute(
                    f"SELECT type_id, adjusted_price FROM market_prices WHERE type_id IN ({ph}) AND adjusted_price > 0",
                    tuple(tids),
                ).fetchall()
            except sqlite3.OperationalError:
                return None
        return {int(tid): float(price) for tid, price in rows if price}

    def get_system_cost_index(
        self,
        system_id: int | None,
        activity: str = "manufacturing",
        hub: str = "Jita",
    ) -> float:
        """星系的制造成本指数（SCI）。`system_id=None` 时从 hub 名称推断，查无统一用默认值。

        数据在 `reference.db` 而非 `market.db`（唯一一个跨库的方法）。
        """
        from core.constants import DEFAULT_SYSTEM_COST_INDEX, TRADE_HUB_SYSTEM_IDS

        if system_id is None:
            system_id = TRADE_HUB_SYSTEM_IDS.get(hub)
        if system_id is None:
            return DEFAULT_SYSTEM_COST_INDEX
        with self._db.connect("ref") as conn:
            r = conn.execute(
                "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
                (system_id, activity),
            ).fetchone()
            return float(r[0]) if r else DEFAULT_SYSTEM_COST_INDEX

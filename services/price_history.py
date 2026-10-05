"""
Market price history — ESI /markets/{region_id}/history/
Cache in market.db price_history table
"""

from datetime import UTC, datetime

import aiohttp

from services.database_manager import get_db

ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002  # The Forge

# Cache TTL: 1 hour (ESI history updates daily, 1h is conservative)
CACHE_TTL_SECONDS = 3600

#: `price_history` 的建表语句 —— **单一来源**。
#: 除了这里的 `_ensure_table`，「更新价格」流程（`services/importers/getprices.py`）也会
#: 用 aiosqlite 直接写这张表，两边必须完全一致，所以 DDL 只留这一份。
#: market.db 是可重建缓存，故不走 `schema_migrations`（克制条款第 3 条）。
PRICE_HISTORY_DDL = """
    CREATE TABLE IF NOT EXISTS price_history (
        type_id INTEGER NOT NULL,
        region_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        average REAL NOT NULL,
        highest REAL NOT NULL DEFAULT 0,
        lowest REAL NOT NULL DEFAULT 0,
        volume INTEGER NOT NULL DEFAULT 0,
        order_count INTEGER NOT NULL DEFAULT 0,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (type_id, region_id, date)
    )
"""


def _ensure_table(db=None) -> None:
    """Ensure price_history table exists in market.db"""
    conn_mgr = db or get_db()
    with conn_mgr.connect("mkt") as conn:
        conn.execute(PRICE_HISTORY_DDL)


async def fetch_history(
    type_id: int,
    region_id: int = REGION_ID,
    session: aiohttp.ClientSession | None = None,
) -> list[dict] | None:
    """Fetch price history from ESI /markets/{region_id}/history/

    Returns list of {date, average, highest, lowest, volume, order_count}
    None on 404 or error.
    """
    url = f"{ESI_BASE_URL}/markets/{region_id}/history/"
    params = {"type_id": type_id}

    async def _do(s: aiohttp.ClientSession) -> list[dict] | None:
        async with s.get(url, params=params) as resp:
            if resp.status == 404:
                return None
            if not resp.ok:
                resp.raise_for_status()
            return await resp.json()  # type: ignore[no-any-return]

    if session is not None:
        return await _do(session)

    from services.client import APIClient

    query = "&".join(f"{k}={v}" for k, v in params.items())
    async with APIClient(timeout=30) as client:
        return await client.fetch_raw(f"{url}?{query}")  # type: ignore[no-any-return]


def get_cached_history(type_id: int, region_id: int = REGION_ID, _db=None) -> list[dict] | None:
    """Read cached history from market.db

    Returns cached data if fresh (within CACHE_TTL), None otherwise.
    """
    conn_mgr = _db or get_db()
    _ensure_table(conn_mgr)
    with conn_mgr.connect("mkt") as conn:
        row = conn.execute(
            "SELECT MAX(fetched_at) as latest FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        ).fetchone()
        if row and row["latest"]:
            fetched = datetime.fromisoformat(row["latest"])
            now = datetime.now(UTC).replace(tzinfo=None)
            if fetched.tzinfo:
                fetched = fetched.replace(tzinfo=None)
            if (now - fetched).total_seconds() < CACHE_TTL_SECONDS:
                rows = conn.execute(
                    "SELECT date, average, highest, lowest, volume, order_count "
                    "FROM price_history WHERE type_id=? AND region_id=? "
                    "ORDER BY date ASC",
                    (type_id, region_id),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
    return None


def save_cache(type_id: int, region_id: int, data: list[dict], _db=None) -> None:
    """Save price history to market.db cache"""
    conn_mgr = _db or get_db()
    _ensure_table(conn_mgr)
    with conn_mgr.connect("mkt") as conn:
        conn.execute(
            "DELETE FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        )
        now = datetime.now(UTC).isoformat()
        for entry in data:
            conn.execute(
                "INSERT INTO price_history "
                "  (type_id, region_id, date, average, highest, lowest, "
                "  volume, order_count, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    type_id,
                    region_id,
                    entry["date"],
                    entry["average"],
                    entry.get("highest", entry["average"]),
                    entry.get("lowest", entry["average"]),
                    entry["volume"],
                    entry.get("order_count", 0),
                    now,
                ),
            )


#: 「日订单量 / 日成交量」两列默认的聚合窗口（天）。
#: 与 `CACHE_TTL_SECONDS` 无关：那个管「多久算过期」，这个管「平均几天」。
SUMMARY_DAYS = 7

#: 一次 SQL 里 `IN (...)` 的参数个数上限（SQLite 变量上限的保守取值，与 blueprint_repository 同口径）
_SQL_PARAM_CHUNK = 900


def get_history_summary(
    type_ids,
    region_id: int = REGION_ID,
    days: int = SUMMARY_DAYS,
    _db=None,
) -> dict[int, dict]:
    """读本地缓存，算出「近 `days` 天平均订单量 / 成交量」→ `{type_id: {...}}`。

    载荷：`{"oc": 平均 order_count | None, "vol": 平均 volume | None,
    "days": 参与平均的天数, "last": 最新一条历史的日期}`。

    **窗口按「最近 `days` 条记录」取，不是「最近 days 个日历天」**：历史是按天入库的，
    但某个 type 可能只在打开价格走势图时被拉过一次，日期停在几个月前 —— 按日历窗口会让
    整列变空，而「最近 7 条」总能回答「上次有数据时一天卖多少」。

    查不到的 type **不出现在返回值里**（调用方 `.get(id)` 即得 `None` → 表格显示 `—`）：
    这里**不用 0 冒充「查不到」**，0 是「确实没人下单」。
    """
    ids = [int(t) for t in type_ids if t]
    if not ids:
        return {}

    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt") as conn:
        # 只读路径不做 DDL：表还没建（从没打开过价格走势图、也从没更新过价格）就是没有数据
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_history'").fetchone():
            return {}

        out: dict[int, dict] = {}
        for start in range(0, len(ids), _SQL_PARAM_CHUNK):
            chunk = ids[start : start + _SQL_PARAM_CHUNK]
            ph = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"""
                SELECT type_id, AVG(order_count) AS oc, AVG(volume) AS vol,
                       COUNT(*) AS n, MAX(date) AS last
                FROM (
                    SELECT type_id, order_count, volume, date,
                           ROW_NUMBER() OVER (PARTITION BY type_id ORDER BY date DESC) AS rn
                    FROM price_history
                    WHERE region_id = ? AND type_id IN ({ph})
                )
                WHERE rn <= ?
                GROUP BY type_id
                """,
                (region_id, *chunk, days),
            ).fetchall()
            for tid, oc, vol, n, last in rows:
                out[int(tid)] = {
                    "oc": float(oc) if oc is not None else None,
                    "vol": float(vol) if vol is not None else None,
                    "days": int(n),
                    "last": last,
                }
        return out


class PriceHistoryService:
    """价格历史服务 — 容器注入 DatabaseManager（替代模块级 get_db 单例）"""

    def __init__(self, db):
        self._db = db

    async def fetch(self, type_id: int, region_id: int = REGION_ID, session=None) -> list[dict] | None:
        """拉取 ESI 历史价格（失败返回 None）"""
        return await fetch_history(type_id, region_id, session)

    def get_cached(self, type_id: int, region_id: int = REGION_ID) -> list[dict] | None:
        """读取缓存历史价格（TTL 内命中，否则 None）"""
        return get_cached_history(type_id, region_id, _db=self._db)

    def save(self, type_id: int, region_id: int, data: list[dict]) -> None:
        """写入缓存历史价格"""
        save_cache(type_id, region_id, data, _db=self._db)

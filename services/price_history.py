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


def _ensure_table(db=None) -> None:
    """Ensure price_history table exists in market.db"""
    conn_mgr = db or get_db()
    with conn_mgr.connect("mkt") as conn:
        conn.execute("""
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
        """)


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
        return await client.fetch_raw(f"{url}?{query}")


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

"""
Market price history — ESI /markets/{region_id}/history/
Cache in market.db price_history table
"""

from datetime import datetime, timezone

import aiohttp

from services.database_manager import get_db

ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002  # The Forge

# Cache TTL: 1 hour (ESI history updates daily, 1h is conservative)
CACHE_TTL_SECONDS = 3600


def _ensure_table() -> None:
    """Ensure price_history table exists in market.db"""
    db = get_db()
    with db.connect("mkt") as conn:
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
            return await resp.json()

    if session is not None:
        return await _do(session)

    headers = {"Accept": "application/json", "User-Agent": "EveApp/1.0"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as sess:
        return await _do(sess)


def get_cached_history(type_id: int, region_id: int = REGION_ID) -> list[dict] | None:
    """Read cached history from market.db

    Returns cached data if fresh (within CACHE_TTL), None otherwise.
    """
    _ensure_table()
    db = get_db()
    with db.connect("mkt") as conn:
        row = conn.execute(
            "SELECT MAX(fetched_at) as latest FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        ).fetchone()
        if row and row["latest"]:
            fetched = datetime.fromisoformat(row["latest"])
            now = datetime.now(timezone.utc).replace(tzinfo=None)
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


def save_cache(type_id: int, region_id: int, data: list[dict]) -> None:
    """Save price history to market.db cache"""
    _ensure_table()
    db = get_db()
    with db.connect("mkt") as conn:
        conn.execute(
            "DELETE FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        )
        now = datetime.now(timezone.utc).isoformat()
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

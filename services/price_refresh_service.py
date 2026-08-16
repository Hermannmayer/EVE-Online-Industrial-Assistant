"""定向价格刷新服务 — 缓存检查与价格落库。"""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from core.paths import market_db_path

MKT_DB = market_db_path()
CACHE_TTL_SECONDS = 300


async def check_stale_type_ids(type_ids: set[int]) -> set[int]:
    """返回需要刷新的 type_id（无数据或超过 TTL）。"""
    if not type_ids:
        return set()
    stale: set[int] = set()
    async with aiosqlite.connect(MKT_DB) as db:
        ph = ",".join("?" for _ in type_ids)
        cursor = await db.execute(
            f"SELECT type_id, fetch_time FROM market_prices WHERE type_id IN ({ph}) AND region_id=10000002",
            list(type_ids),
        )
        rows = await cursor.fetchall()
    fetched = {r[0] for r in rows}
    stale.update(type_ids - fetched)
    now = datetime.now(UTC)
    for tid, ft_str in rows:
        try:
            ft = datetime.strptime(ft_str, "%Y-%m-%d %H:%M:%S")
            ft = ft.replace(tzinfo=UTC)
            if (now - ft).total_seconds() > CACHE_TTL_SECONDS:
                stale.add(tid)
        except (ValueError, TypeError):
            stale.add(tid)
    return stale


async def save_refreshed_prices(type_orders: dict[int, dict], region_id: int = 10000002) -> int:
    """把拉取到的价格写入 market_prices，保留 adjusted_price。返回写入条数。"""
    count = 0
    async with aiosqlite.connect(MKT_DB) as db:
        for tid, p in type_orders.items():
            cur = await db.execute(
                """UPDATE market_prices
                   SET buy_price=?, sell_price=?, buy_volume=?, sell_volume=?,
                       fetch_time=datetime('now')
                   WHERE type_id=? AND region_id=?""",
                (
                    p["buy_price"],
                    p["sell_price"],
                    int(p["buy_volume"]),
                    int(p["sell_volume"]),
                    tid,
                    region_id,
                ),
            )
            if cur.rowcount == 0:
                await db.execute(
                    """INSERT INTO market_prices
                       (type_id, region_id, buy_price, sell_price, adjusted_price,
                        buy_volume, sell_volume, fetch_time)
                       VALUES (?, ?, ?, ?, 0.0, ?, ?, datetime('now'))""",
                    (
                        tid,
                        region_id,
                        p["buy_price"],
                        p["sell_price"],
                        int(p["buy_volume"]),
                        int(p["sell_volume"]),
                    ),
                )
            count += 1
        await db.commit()
    return count

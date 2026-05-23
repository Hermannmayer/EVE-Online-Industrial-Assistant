"""
市场价格拉取 — 4 大贸易中心订单簿 + 成交量历史

两阶段：
  1. 先拉 /markets/prices/（1次请求，极快）做兜底
  2. 并发拉取 4 区域订单，用真实买卖价覆盖
"""
import asyncio
import aiohttp
import aiosqlite
import json
import os
from datetime import datetime, timezone
from core.paths import database_path, progress_file

DATABASE_PATH = database_path()
ESI_BASE_URL = "https://esi.evetech.net/latest"

TRADE_REGIONS = [
    ("Jita",    10000002),
    ("Amarr",   10000043),
    ("Dodixie", 10000032),
    ("Rens",    10000030),
]

# 缓存已知页数，下次跳过 page-1 发现环节
_PAGE_CACHE: dict[str, int] = {}


def write_progress(cur: int, total: int, phase: str = ""):
    try:
        fp = progress_file()
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as f:
            json.dump({"current": cur, "total": total, "phase": phase}, f)
    except Exception:
        pass


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                buy_price REAL,
                sell_price REAL,
                buy_volume BIGINT DEFAULT 0,
                sell_volume BIGINT DEFAULT 0,
                fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mp_type_time ON market_prices(type_id, fetch_time)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market_volume_snapshots (
                type_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                buy_price REAL DEFAULT 0,
                sell_price REAL DEFAULT 0,
                buy_volume BIGINT DEFAULT 0,
                sell_volume BIGINT DEFAULT 0,
                PRIMARY KEY (type_id, date)
            )
        """)
        await db.commit()


async def fetch_baseline_prices() -> dict[int, dict]:
    """/markets/prices/ — 1次请求，极快"""
    async with aiohttp.ClientSession(headers={"User-Agent": "EveDataCrawler/1.0"}) as s:
        async with s.get(f"{ESI_BASE_URL}/markets/prices/") as resp:
            data = await resp.json()
    result = {}
    for item in data:
        result[item["type_id"]] = {
            "buy_price": item.get("average_price"),
            "sell_price": item.get("adjusted_price"),
            "buy_volume": 0,
            "sell_volume": 0,
        }
    return result


async def fetch_order_pages(session, region_id: int, order_type: str, total_pages: int) -> list:
    """并发拉取一个区域指定方向的所有订单页"""
    all_data = []
    sem = asyncio.Semaphore(50)

    async def get_page(p: int):
        url = f"{ESI_BASE_URL}/markets/{region_id}/orders/?order_type={order_type}&page={p}"
        async with sem:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        return []

    # 拉取全部页面
    pages = list(range(1, total_pages + 1))
    for i in range(0, len(pages), 50):
        batch = pages[i:i + 50]
        results = await asyncio.gather(*[get_page(p) for p in batch])
        for r in results:
            all_data.extend(r)
    return all_data


async def discover_pages(session) -> dict:
    """并发获取所有流的总页数（8次请求）"""
    keys = {}
    tasks = []

    async def discover(rid: int, ot: str):
        cache_key = f"{rid}_{ot}"
        if cache_key in _PAGE_CACHE:
            keys[cache_key] = _PAGE_CACHE[cache_key]
            return
        url = f"{ESI_BASE_URL}/markets/{rid}/orders/?order_type={ot}&page=1"
        async with session.get(url) as resp:
            if resp.status == 200:
                pages = int(resp.headers.get("X-Pages", 1))
                _PAGE_CACHE[cache_key] = pages
                keys[cache_key] = pages

    for _, rid in TRADE_REGIONS:
        for ot in ("sell", "buy"):
            tasks.append(discover(rid, ot))

    await asyncio.gather(*tasks)
    return keys


async def fetch_orders() -> dict[int, dict]:
    """4 区域实时订单，按 type_id 聚合"""
    print("  发现订单页数...")
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(
        headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"},
        timeout=timeout,
    ) as session:
        page_map = await discover_pages(session)

        total_reqs = sum(page_map.values())
        print(f"  共 {total_reqs} 页，开始拉取...")

        all_orders = []
        done = 0
        for name, rid in TRADE_REGIONS:
            for ot in ("sell", "buy"):
                key = f"{rid}_{ot}"
                pages = page_map.get(key, 0)
                if not pages:
                    continue
                data = await fetch_order_pages(session, rid, ot, pages)
                all_orders.extend(data)
                done += pages

    print(f"  获取 {len(all_orders)} 条订单")

    # 聚合
    agg = {}
    for o in all_orders:
        tid = o["type_id"]
        price = o["price"]
        vol = o.get("volume_remain", 0)
        is_buy = o.get("is_buy_order", False)

        if tid not in agg:
            agg[tid] = {"buy_price": 0.0, "sell_price": float("inf"),
                        "buy_volume": 0, "sell_volume": 0}

        if is_buy:
            if price > agg[tid]["buy_price"]:
                agg[tid]["buy_price"] = price
            agg[tid]["buy_volume"] += vol
        else:
            if price < agg[tid]["sell_price"]:
                agg[tid]["sell_price"] = price
            agg[tid]["sell_volume"] += vol

    for tid in agg:
        if agg[tid]["sell_price"] == float("inf"):
            agg[tid]["sell_price"] = 0.0

    return agg


async def save_snapshot(agg: dict):
    """保存当日成交量快照，日积月累后可用于计算 7 日平均"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        records = [(tid, today, p["buy_price"], p["sell_price"],
                    int(p["buy_volume"]), int(p["sell_volume"]))
                   for tid, p in agg.items()]
        await db.executemany("""
            INSERT OR REPLACE INTO market_volume_snapshots
            (type_id, date, buy_price, sell_price, buy_volume, sell_volume)
            VALUES (?, ?, ?, ?, ?, ?)
        """, records)
        await db.commit()
    print(f"  快照已保存: {len(records)} 条")


async def save_prices(merged: dict) -> int:
    """清空旧价格数据，写入新快照"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM market_prices")
        records = [(tid, p["buy_price"], p["sell_price"],
                    int(p["buy_volume"]), int(p["sell_volume"]))
                   for tid, p in merged.items()
                   if p["buy_price"] or p["sell_price"]]
        for i in range(0, len(records), 500):
            await db.executemany("""
                INSERT INTO market_prices (type_id, buy_price, sell_price, buy_volume, sell_volume)
                VALUES (?, ?, ?, ?, ?)
            """, records[i:i + 500])
        await db.commit()
    return len(records)


async def main():
    t0 = datetime.now()
    print("=== 四大贸易中心价格拉取 ===")
    write_progress(0, 4, "初始化数据库...")
    await init_db()

    write_progress(1, 4, "获取基准价格(/markets/prices/)...")
    baseline = await fetch_baseline_prices()
    print(f"  基准价格: {len(baseline)} 个物品")

    write_progress(2, 4, "拉取实时订单簿...")
    order_prices = await fetch_orders()
    print(f"  实时订单: {len(order_prices)} 个物品")

    # 合并：订单数据优先，无订单的用基准价格兜底
    merged = dict(baseline)
    for tid, prices in order_prices.items():
        merged[tid] = prices

    write_progress(3, 4, "写入数据库...")
    cnt = await save_prices(merged)
    print(f"  写入 {cnt} 条")

    # 保存当日快照（轻量，不触发额外网络请求）
    if order_prices:
        await save_snapshot(order_prices)

    elapsed = (datetime.now() - t0).total_seconds()
    write_progress(4, 4, "完成")
    print(f"\nDone! {elapsed:.0f} seconds")
    print(f"   baseline: {len(baseline)} items")
    print(f"   realtime: {len(order_prices)} items (4 trade hubs)")


def run_price_update():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")


if __name__ == "__main__":
    run_price_update()

"""
市场价格拉取 — 4 大贸易中心订单簿 + 成交量历史

两阶段：
  1. 先拉 /markets/prices/（1次请求，极快）做兜底
  2. 并发拉取 4 区域订单，用真实买卖价覆盖
"""

import asyncio
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime

import aiosqlite

from core.constants import TRADE_HUB_IDS
from core.logger import log
from core.paths import market_db_path, progress_file
from services.client import APIClient, RateLimiter

DATABASE_PATH = market_db_path()
ESI_BASE_URL = "https://esi.evetech.net/latest"

TRADE_REGIONS = list(TRADE_HUB_IDS.items())

# 缓存已知页数，下次跳过 page-1 发现环节
_PAGE_CACHE: dict[str, int] = {}

# ESI 全局限流（20 req/s）— 与 APIClient 内部限流器独立，直接保护裸请求
_rate_limiter = RateLimiter(rate=20.0, burst=40)


def write_progress(cur: int, total: int, phase: str = ""):
    try:
        fp = progress_file()
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as f:
            json.dump({"current": cur, "total": total, "phase": phase}, f)
    except Exception:
        log.exception("写进度文件失败")


async def init_db():
    """确保 market_prices 和 market_volume_snapshots 表存在（幂等）

    不再 DROP TABLE — 改用 CREATE TABLE IF NOT EXISTS + ALTER ADD COLUMN
    保留已有价格数据。列缺失由 schema_migrations 或此处 ALTER TABLE 兜底。
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market_prices (
                type_id INTEGER NOT NULL,
                region_id INTEGER NOT NULL,
                buy_price REAL,
                sell_price REAL,
                adjusted_price REAL DEFAULT 0.0,
                buy_volume BIGINT DEFAULT 0,
                sell_volume BIGINT DEFAULT 0,
                fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (type_id, region_id)
            )
        """)
        # 兼容旧库：补加 adjusted_price 列（schema_migrations v1→v2 已注册，此处兜底旧版流程）
        try:
            await db.execute("ALTER TABLE market_prices ADD COLUMN adjusted_price REAL DEFAULT 0.0")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market_volume_snapshots (
                type_id INTEGER NOT NULL,
                region_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                buy_price REAL DEFAULT 0,
                sell_price REAL DEFAULT 0,
                buy_volume BIGINT DEFAULT 0,
                sell_volume BIGINT DEFAULT 0,
                PRIMARY KEY (type_id, region_id, date)
            )
        """)
        await db.commit()


async def fetch_baseline_prices() -> dict[int, dict]:
    """/markets/prices/ — 1次请求，极快"""
    async with APIClient(timeout=60) as client:
        data = await client.fetch_raw(f"{ESI_BASE_URL}/markets/prices/")
    if data is None:
        log.warning("基准价格拉取失败（网络/限流），本次价格更新将缺少兜底数据")
        return {}
    result = {}
    for item in data:
        result[item["type_id"]] = {
            "buy_price": item.get("average_price"),
            "sell_price": item.get("adjusted_price"),
            "adjusted_price": item.get("adjusted_price"),
            "buy_volume": 0,
            "sell_volume": 0,
        }
    return result


async def fetch_order_pages(client: APIClient, region_id: int, order_type: str, total_pages: int) -> list:
    """并发拉取一个区域指定方向的所有订单页（全局限流 ≤20 req/s）"""
    all_data = []
    sem = asyncio.Semaphore(8)

    async def get_page(p: int):
        url = f"{ESI_BASE_URL}/markets/{region_id}/orders/?order_type={order_type}&page={p}"
        async with sem:
            try:
                data = await client.fetch_raw(url)
            except Exception:
                log.exception("订单页拉取异常: %s", url)
                return []
            if data is None:
                log.warning("订单页拉取失败（非 200/限流/超时）: %s", url)
                return []
            return data

    # 拉取全部页面
    pages = list(range(1, total_pages + 1))
    for i in range(0, len(pages), 8):
        batch = pages[i : i + 8]
        results = await asyncio.gather(*[get_page(p) for p in batch])
        for r in results:
            all_data.extend(r)
    return all_data


async def discover_pages(client: APIClient, targets: list[tuple[str, int]] | None = None) -> dict:
    """并发获取所有流的总页数（8次请求）"""
    targets = targets or TRADE_REGIONS
    keys = {}
    tasks = []

    async def discover(rid: int, ot: str):
        cache_key = f"{rid}_{ot}"
        if cache_key in _PAGE_CACHE:
            keys[cache_key] = _PAGE_CACHE[cache_key]
            return
        url = f"{ESI_BASE_URL}/markets/{rid}/orders/?order_type={ot}&page=1"
        headers = await client.get_headers(url)
        if headers is None:
            log.warning("页数发现失败（非 200/限流）: %s", url)
            return
        pages = int(headers.get("X-Pages", 1))
        _PAGE_CACHE[cache_key] = pages
        keys[cache_key] = pages

    for _, rid in targets:
        for ot in ("sell", "buy"):
            tasks.append(discover(rid, ot))

    await asyncio.gather(*tasks)
    return keys


async def fetch_orders(regions: list[tuple[str, int]] | None = None) -> dict[int, dict[int, dict]]:
    """4 区域实时订单，按 region_id → type_id 组织

    Args:
        regions: 要拉取的区域列表 [(name, id), ...]，None 表示拉取全部

    Returns:
        {region_id: {type_id: {buy_price, sell_price, buy_volume, sell_volume}}}
    """
    targets = regions or TRADE_REGIONS
    log.info("发现订单页数...")
    async with APIClient(timeout=120) as client:
        page_map = await discover_pages(client)

        total_reqs = sum(page_map.values())
        log.info("  共 %s 页，开始拉取...", total_reqs)

        result = {}
        for _name, rid in targets:
            region_data = {}
            for ot in ("sell", "buy"):
                key = f"{rid}_{ot}"
                pages = page_map.get(key, 0)
                if not pages:
                    continue
                data = await fetch_order_pages(client, rid, ot, pages)

                for o in data:
                    tid = o["type_id"]
                    price = o["price"]
                    vol = o.get("volume_remain", 0)
                    is_buy = o.get("is_buy_order", False)

                    if tid not in region_data:
                        region_data[tid] = {
                            "buy_price": 0.0,
                            "sell_price": float("inf"),
                            "buy_volume": 0,
                            "sell_volume": 0,
                        }

                    if is_buy:
                        if price > region_data[tid]["buy_price"]:
                            region_data[tid]["buy_price"] = price
                        region_data[tid]["buy_volume"] += vol
                    else:
                        if price < region_data[tid]["sell_price"]:
                            region_data[tid]["sell_price"] = price
                        region_data[tid]["sell_volume"] += vol

            # 修复无卖单的物品
            for tid in region_data:
                if region_data[tid]["sell_price"] == float("inf"):
                    region_data[tid]["sell_price"] = 0.0

            result[rid] = region_data

    total_items = sum(len(d) for d in result.values())
    log.info("  获取 %s 条聚合记录（%s 个区域）", total_items, len(result))
    return result


async def save_snapshot(all_regions: dict[int, dict[int, dict]]):
    """保存各区域当日成交量快照"""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        records = []
        for region_id, items in all_regions.items():
            for tid, p in items.items():
                records.append(
                    (
                        tid,
                        region_id,
                        today,
                        p["buy_price"],
                        p["sell_price"],
                        int(p["buy_volume"]),
                        int(p["sell_volume"]),
                    )
                )
        await db.executemany(
            """
            INSERT OR REPLACE INTO market_volume_snapshots
            (type_id, region_id, date, buy_price, sell_price, buy_volume, sell_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            records,
        )
        await db.commit()
    log.info(f"  快照已保存: {len(records)} 条（{len(all_regions)} 个区域）")


async def save_prices(
    baseline: dict[int, dict],
    order_prices: dict[int, dict[int, dict]],
    region_ids: list[int] | None = None,
) -> int:
    """写入各区域价格（仅覆盖指定区域）。

    失败保护：拉取失败的区域（order_prices 中无该 region 或为空 dict）跳过
    删除与插入，保留该区域旧价格 —— 避免「先 DELETE 后 INSERT」在拉取失败时
    清空整区数据。
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 确定本次实际成功的区域（order_prices 中存在且有数据）
        target_regions = region_ids or list(order_prices.keys())
        succeeded = [rid for rid in target_regions if order_prices.get(rid)]
        failed = [rid for rid in target_regions if rid not in succeeded]
        if failed:
            log.warning("  以下区域拉取失败，保留旧价格: %s", failed)

        records = []
        for region_id in succeeded:
            await db.execute("DELETE FROM market_prices WHERE region_id = ?", (region_id,))
            items = order_prices[region_id]
            merged = dict(baseline)
            for tid, prices in items.items():
                merged[tid] = prices
            for tid, p in merged.items():
                if p["buy_price"] or p["sell_price"]:
                    records.append(
                        (
                            tid,
                            region_id,
                            p["buy_price"],
                            p["sell_price"],
                            p.get("adjusted_price", 0.0),
                            int(p["buy_volume"]),
                            int(p["sell_volume"]),
                        )
                    )
        for i in range(0, len(records), 500):
            await db.executemany(
                """
                INSERT INTO market_prices (type_id, region_id, buy_price, sell_price, adjusted_price, buy_volume, sell_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                records[i : i + 500],
            )
        await db.commit()
    return len(records)


async def main(regions: list[tuple[str, int]] | None = None, progress_cb: Callable[[int, str], None] | None = None):
    t0 = datetime.now()
    regions = regions or TRADE_REGIONS
    region_names = [n for n, _ in regions]
    log.info(f"=== 价格拉取: {', '.join(region_names)} ===")
    write_progress(0, 4, pm := "初始化数据库...")
    if progress_cb:
        progress_cb(0, pm)
    await init_db()

    write_progress(1, 4, pm := "获取基准价格(/markets/prices/)...")
    if progress_cb:
        progress_cb(10, pm)
    baseline = await fetch_baseline_prices()
    log.info(f"  基准价格: {len(baseline)} 个物品")

    write_progress(2, 4, pm := "拉取实时订单簿...")
    if progress_cb:
        progress_cb(30, pm)
    order_prices = await fetch_orders(regions)

    write_progress(3, 4, pm := "写入数据库...")
    if progress_cb:
        progress_cb(70, pm)
    cnt = await save_prices(baseline, order_prices, [rid for _, rid in regions])
    log.info(f"  写入 {cnt} 条")

    # 保存当日快照
    if order_prices:
        await save_snapshot(order_prices)

    elapsed = (datetime.now() - t0).total_seconds()
    write_progress(4, 4, "完成")
    log.info(f"Done! {elapsed:.0f} seconds")
    for rid, items in sorted(order_prices.items()):
        name = {v: k for k, v in TRADE_REGIONS}.get(rid, str(rid))
        log.info(f"  {name} (id={rid}): {len(items)} items")


def run_price_update(regions: list[str] | None = None):
    """
    运行价格更新。

    Args:
        regions: 要更新的区域名称列表，如 ['Jita', 'Amarr']
                 None 或空列表则更新全部四大贸易中心
    """
    try:
        target_regions = [(name, rid) for name, rid in TRADE_REGIONS if not regions or name in regions]
        asyncio.run(main(target_regions))
    except KeyboardInterrupt:
        log.warning("用户中断")


if __name__ == "__main__":
    run_price_update()

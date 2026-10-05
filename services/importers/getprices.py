"""
市场价格拉取 — 4 大贸易中心订单簿 + 成交量历史

两阶段：
  1. 先拉 /markets/prices/（1次请求，极快）做兜底
  2. 并发拉取 4 区域订单，用真实买卖价覆盖
"""

import asyncio
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import aiosqlite

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from core.paths import market_db_path, progress_file
from domain.market_depth import BUY, SELL, depth_price
from services.client import APIClient
from services.price_history import PRICE_HISTORY_DDL, fetch_history

DATABASE_PATH = market_db_path()
ESI_BASE_URL = "https://esi.evetech.net/latest"

TRADE_REGIONS = list(TRADE_HUB_IDS.items())

#: 市场历史（ESI `/markets/{region_id}/history/`）的增量 TTL。
#: ESI 历史按天更新，12 小时足够新。**没有这个 TTL 就会每轮把 4908 个可制造/反应产物
#: 全拉一遍**（20 req/s 限流下约 4 分钟纯等待）；TTL 命中时本轮 **0 请求**。
HISTORY_TTL_SECONDS = 12 * 3600

#: `price_history` 里每个 `(type_id, region_id)` 最多保留的天数。
#: 「可制造物品」窗口的日订单量/日成交量只聚合最近 7 条记录，不裁剪会让 market.db
#: 多出约 200 万行（4908 产物 × 约 400 天 × 每区域一行）。
HISTORY_KEEP_DAYS = 180

#: 市场历史的分批大小（照 `services/importers/getitems.py` 的 ESI 补拉骨架）
_HISTORY_BATCH = 100

#: 「可制造物品」窗口读历史时用的**缺省区域**（Jita）。历史本身按「本次更新勾了哪些中心」
#: 全拉（见 `fetch_and_save_histories`）：贸易页要显示两端各自的日成交量，读端会显式传
#: 它当前选的起点/终点区域；这里只给「没有区域语境的读端」一个默认值
#: （`manufacturable_items_bridge` 显式传 JITA_RID，其实也不依赖这个默认）。
HISTORY_REGION_ID = TRADE_HUB_IDS["Jita"]

# 缓存已知页数，下次跳过 page-1 发现环节；带时间戳以便 TTL 失效
_PAGE_CACHE: dict[str, int] = {}
_PAGE_CACHE_TIME: dict[str, float] = {}
_PAGE_CACHE_TTL_SECONDS = 1800


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

    不再 DROP TABLE — 改用 CREATE TABLE IF NOT EXISTS 保留已有价格数据。
    建表语句已含全部列；老库缺列由 schema_migrations 的 mkt 迁移补（v1→v2 即
    adjusted_price）。此处不做 ALTER 兜底 —— 业务代码里的 DDL 会让 schema
    版本记录与真实表结构分叉，且失败时会被宽泛异常吞掉。
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


async def _fetch_order_pages_detailed(
    client: APIClient, region_id: int, order_type: str, total_pages: int
) -> tuple[list, bool]:
    """并发拉取一个区域指定方向的所有订单页（全局限流 ≤20 req/s）。

    Returns:
        (all_data, complete)：complete=False 表示存在页面失败，调用方不应替换旧数据。
    """
    all_data = []
    failed = False
    sem = asyncio.Semaphore(8)

    async def get_page(p: int):
        nonlocal failed
        url = f"{ESI_BASE_URL}/markets/{region_id}/orders/?order_type={order_type}&page={p}"
        async with sem:
            try:
                data = await client.fetch_raw(url)
            except Exception:
                log.exception("订单页拉取异常: %s", url)
                failed = True
                return []
            if data is None:
                log.warning("订单页拉取失败（非 200/限流/超时）: %s", url)
                failed = True
                return []
            return data

    # 拉取全部页面
    pages = list(range(1, total_pages + 1))
    for i in range(0, len(pages), 8):
        batch = pages[i : i + 8]
        results = await asyncio.gather(*[get_page(p) for p in batch])
        for r in results:
            all_data.extend(r)
    return all_data, not failed


async def fetch_order_pages(client: APIClient, region_id: int, order_type: str, total_pages: int) -> list:
    """并发拉取一个区域指定方向的所有订单页（兼容旧签名，只返回数据）。"""
    data, _complete = await _fetch_order_pages_detailed(client, region_id, order_type, total_pages)
    return data


async def discover_pages(client: APIClient, targets: list[tuple[str, int]] | None = None) -> dict:
    """并发获取所有流的总页数（8次请求）"""
    targets = targets or TRADE_REGIONS
    keys = {}
    tasks = []

    async def discover(rid: int, ot: str):
        cache_key = f"{rid}_{ot}"
        cached_ts = _PAGE_CACHE_TIME.get(cache_key)
        if cache_key in _PAGE_CACHE and (cached_ts is None or time.time() - cached_ts < _PAGE_CACHE_TTL_SECONDS):
            keys[cache_key] = _PAGE_CACHE[cache_key]
            return
        url = f"{ESI_BASE_URL}/markets/{rid}/orders/?order_type={ot}&page=1"
        headers = await client.get_headers(url)
        if headers is None:
            log.warning("页数发现失败（非 200/限流）: %s", url)
            return
        pages = int(headers.get("X-Pages", 1))
        _PAGE_CACHE[cache_key] = pages
        _PAGE_CACHE_TIME[cache_key] = time.time()
        keys[cache_key] = pages

    for _, rid in targets:
        for ot in ("sell", "buy"):
            tasks.append(discover(rid, ot))

    await asyncio.gather(*tasks, return_exceptions=True)
    return keys


async def fetch_orders_detailed(
    regions: list[tuple[str, int]] | None = None,
) -> tuple[dict[int, dict[int, dict]], set[int]]:
    """4 区域实时订单，按 region_id → type_id 组织，并返回完整拉取成功的区域。

    Returns:
        ({region_id: {type_id: {...}}}, complete_regions)
        complete_regions 仅包含买卖两个方向所有页面都成功的区域。
    """
    targets = regions or TRADE_REGIONS
    log.info("发现订单页数...")
    async with APIClient(timeout=120) as client:
        page_map = await discover_pages(client)

        total_reqs = sum(page_map.values())
        log.info("  共 %s 页，开始拉取...", total_reqs)

        result = {}
        complete_regions: set[int] = set()
        for _name, rid in targets:
            # 先按物品收集挂单档位，再统一算深度价（见 domain/market_depth.py）。
            # 直接取 min/max 会被只有一两个单位的凑数挂单带偏。
            levels: dict[int, dict[str, list[tuple[float, int]]]] = {}
            region_complete = True
            for ot in ("sell", "buy"):
                key = f"{rid}_{ot}"
                pages = page_map.get(key, 0)
                if not pages:
                    continue
                data, ok = await _fetch_order_pages_detailed(client, rid, ot, pages)
                if not ok:
                    region_complete = False

                for o in data:
                    tid = o["type_id"]
                    side = BUY if o.get("is_buy_order", False) else SELL
                    sides = levels.setdefault(tid, {SELL: [], BUY: []})
                    sides[side].append((o["price"], o.get("volume_remain", 0)))

            region_data = {}
            for tid, sides in levels.items():
                buy_levels, sell_levels = sides[BUY], sides[SELL]
                region_data[tid] = {
                    "buy_price": depth_price(buy_levels, BUY) or 0.0,
                    "sell_price": depth_price(sell_levels, SELL) or 0.0,
                    "buy_volume": sum(v for _, v in buy_levels),
                    "sell_volume": sum(v for _, v in sell_levels),
                }

            result[rid] = region_data
            if region_complete:
                complete_regions.add(rid)

    total_items = sum(len(d) for d in result.values())
    log.info("  获取 %s 条聚合记录（%s 个区域）", total_items, len(result))
    return result, complete_regions


async def fetch_orders(regions: list[tuple[str, int]] | None = None) -> dict[int, dict[int, dict]]:
    """兼容旧签名：只返回 {region_id: {type_id: {...}}}。"""
    result, _complete = await fetch_orders_detailed(regions)
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
        # 保留最近 90 天，避免快照无限增长
        await db.execute("DELETE FROM market_volume_snapshots WHERE date < date('now', '-90 days')")
        await db.commit()
    log.info(f"  快照已保存: {len(records)} 条（{len(all_regions)} 个区域）")


async def save_prices(
    baseline: dict[int, dict],
    order_prices: dict[int, dict[int, dict]],
    region_ids: list[int] | None = None,
    complete_regions: set[int] | None = None,
) -> int:
    """写入各区域价格（仅覆盖指定区域）。

    失败保护：只有完整拉取成功（complete_regions）的区域才允许替换旧数据；
    拉取失败/部分失败的区域跳过删除与插入，保留旧价格。
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 确定本次实际成功的区域（order_prices 中存在且有数据）
        target_regions = region_ids or list(order_prices.keys())
        if complete_regions is None:
            succeeded = [rid for rid in target_regions if order_prices.get(rid)]
        else:
            succeeded = [rid for rid in target_regions if order_prices.get(rid) and rid in complete_regions]
        failed = [rid for rid in target_regions if rid not in succeeded]
        if failed:
            log.warning("  以下区域拉取失败/不完整，保留旧价格: %s", failed)

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


def _history_is_fresh(fetched_at: str | None, cutoff: datetime) -> bool:
    """`fetched_at` 是否落在 TTL 内（缺失/解析失败一律当作过期 → 重拉）。"""
    if not fetched_at:
        return False
    try:
        ts = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts >= cutoff


async def _pending_history_tasks(region_ids: list[int], type_ids: set[int], cutoff: datetime) -> list[tuple[int, int]]:
    """算出本轮要拉的 `(region_id, type_id)`：没有记录、或记录早于 TTL 的才算。

    每个区域一条 `GROUP BY` 读最新 `fetched_at`（不是 4908 条单查）。
    表不存在时先按 `PRICE_HISTORY_DDL` 建表（与 `services/price_history.py` 同一份 DDL）
    —— 没建表就等于全部待拉。
    """
    pending: list[tuple[int, int]] = []
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(PRICE_HISTORY_DDL)
        await db.commit()
        for rid in region_ids:
            cursor = await db.execute(
                "SELECT type_id, MAX(fetched_at) FROM price_history WHERE region_id = ? GROUP BY type_id",
                (rid,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            fresh = {int(t) for t, ts in rows if _history_is_fresh(ts, cutoff)}
            pending.extend((rid, tid) for tid in sorted(type_ids - fresh))
    return pending


async def _fetch_history_with_limit(client: APIClient, region_id: int, type_id: int) -> list[dict] | None:
    """经 `GLOBAL_ESI_LIMITER` 拉单条市场历史。

    `price_history.fetch_history(session=…)` 走的是 APIClient 的底层 session，**本身不过限流器**，
    所以这里显式 `limiter.acquire()`，并复用 `APIClient(concurrency=…)` 的并发闸。
    """
    await client.limiter.acquire()
    async with client.semaphore:  # type: ignore[union-attr]
        return await fetch_history(type_id, region_id, session=client.session)


async def _save_histories(entries: dict[tuple[int, int], list[tuple]], date_cutoff: str) -> int:
    """批量写入历史：先按 `(type_id, region_id)` 裁掉 `date_cutoff` 之前的行，再 `INSERT OR REPLACE`。

    裁剪放在插入前（`date < ?` 严格小于），把每个产物的历史限制在 `HISTORY_KEEP_DAYS` 窗口内。
    """
    if not entries:
        return 0
    written = 0
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for (type_id, region_id), rows in entries.items():
            await db.execute(
                "DELETE FROM price_history WHERE type_id = ? AND region_id = ? AND date < ?",
                (type_id, region_id, date_cutoff),
            )
            await db.executemany(
                """
                INSERT OR REPLACE INTO price_history
                (type_id, region_id, date, average, highest, lowest, volume, order_count, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            written += len(rows)
        await db.commit()
    return written


async def fetch_and_save_histories(
    regions: list[tuple[str, int]],
    progress_cb: Callable[[int, str], None] | None = None,
) -> int:
    """按 TTL 增量拉取可制造/反应产物的市场历史，写入 market.db.price_history。

    「日订单量 / 日成交量」两列的数据从这条通道来 —— 与实时订单同属**唯一**的
    「更新价格」入口（`main`），页面不自己拉 ESI：

    - 候选 type_id：blueprint.db 的 manufacturing | reaction 全部产物（实测 4797 + 111 = 4908）
    - 区域：**本次更新勾了哪些中心就拉哪些**（用户口径：「同步哪些市场的数据，就自动把
      成交量一块拉过来」）。读端各自显式传 `region_id`：可制造物品窗口按 Jita
      （`HISTORY_REGION_ID`）、贸易页按它当前选的起点/终点。
    - 增量过滤：`(type_id, region_id)` 的最新 `fetched_at` 在 `HISTORY_TTL_SECONDS` 内就跳过，
      TTL 全命中时本轮 0 请求
    - 失败隔离：单条 404/超时/异常只 `log.warning` 跳过，不写缓存，既不中断本批也不影响整次价格更新

    ⚠️ 请求量 = 产物数 × 勾选的中心数（4908 × N）：一个中心约 4 分钟（全局限流 20 req/s），
    5 个中心齐勾就是一小时量级 —— 靠 12h TTL 增量摊平，但用户该知道这个代价。

    Returns:
        实际写入的历史行数。
    """
    region_ids = [rid for _, rid in regions]
    if not region_ids:
        log.info("本次没有要更新的区域，跳过市场历史拉取")
        return 0

    repo = get_container().blueprint_repo
    type_ids = set(repo.get_all_product_ids("manufacturing"))
    type_ids |= set(repo.get_all_product_ids("reaction"))
    if not type_ids:
        log.warning("蓝图库里没有可制造/反应产物，跳过市场历史拉取")
        return 0

    now = datetime.now(UTC)
    pending = await _pending_history_tasks(region_ids, type_ids, now - timedelta(seconds=HISTORY_TTL_SECONDS))
    if not pending:
        log.info(
            "市场历史均在 TTL（%s 小时）内，本轮 0 请求（%s 个产物 × %s 个区域）",
            HISTORY_TTL_SECONDS // 3600,
            len(type_ids),
            len(region_ids),
        )
        if progress_cb:
            progress_cb(100, "市场历史已是最新")
        return 0

    total = len(pending)
    log.info(
        "市场历史待拉取 %s 条（%s 个产物 × %s 个区域，TTL 内跳过 %s 条）",
        total,
        len(type_ids),
        len(region_ids),
        len(type_ids) * len(region_ids) - total,
    )
    fetched_at = now.isoformat()
    date_cutoff = (now - timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    written = 0
    done = 0
    # APIClient 自带全局限流（GLOBAL_ESI_LIMITER，20 req/s）+ 并发闸 + 429 重试
    async with APIClient(concurrency=10, timeout=30) as client:
        for start in range(0, total, _HISTORY_BATCH):
            batch = pending[start : start + _HISTORY_BATCH]
            results = await asyncio.gather(
                *[_fetch_history_with_limit(client, rid, tid) for rid, tid in batch],
                return_exceptions=True,
            )
            entries: dict[tuple[int, int], list[tuple]] = {}
            for (rid, tid), result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    log.warning("市场历史拉取异常，跳过 type=%s region=%s: %s", tid, rid, result)
                    continue
                if not result:
                    log.warning("市场历史为空/404，跳过 type=%s region=%s", tid, rid)
                    continue
                try:
                    # 只有「这条载荷本身坏掉」（缺 date/average 等）才跳过，不牵连同批其余条目
                    entries[(tid, rid)] = [
                        (
                            tid,
                            rid,
                            e["date"],
                            e["average"],
                            e.get("highest", e["average"]),
                            e.get("lowest", e["average"]),
                            int(e.get("volume", 0)),
                            int(e.get("order_count", 0)),
                            fetched_at,
                        )
                        for e in result
                    ]
                except (KeyError, TypeError, ValueError):
                    log.warning("市场历史数据格式异常，跳过 type=%s region=%s", tid, rid)
                    continue
            written += await _save_histories(entries, date_cutoff)
            done += len(batch)
            if progress_cb:
                progress_cb(min(100, int(done / total * 100)), f"拉取市场历史 {done}/{total}")
    log.info("市场历史写入 %s 行（本轮请求 %s 条）", written, total)
    return written


async def main(regions: list[tuple[str, int]] | None = None, progress_cb: Callable[[int, str], None] | None = None):
    t0 = datetime.now()
    regions = regions or TRADE_REGIONS
    region_names = [n for n, _ in regions]
    log.info(f"=== 价格拉取: {', '.join(region_names)} ===")
    write_progress(0, 5, pm := "初始化数据库...")
    if progress_cb:
        progress_cb(0, pm)
    await init_db()

    write_progress(1, 5, pm := "获取基准价格(/markets/prices/)...")
    if progress_cb:
        progress_cb(10, pm)
    baseline = await fetch_baseline_prices()
    log.info(f"  基准价格: {len(baseline)} 个物品")

    write_progress(2, 5, pm := "拉取实时订单簿...")
    if progress_cb:
        progress_cb(30, pm)
    order_prices, complete_regions = await fetch_orders_detailed(regions)

    write_progress(3, 5, pm := "写入数据库...")
    if progress_cb:
        progress_cb(70, pm)
    cnt = await save_prices(baseline, order_prices, [rid for _, rid in regions], complete_regions)
    log.info(f"  写入 {cnt} 条")

    # 保存当日快照
    if order_prices:
        await save_snapshot(order_prices)

    # 市场历史（日订单量/日成交量）—— 独立一步，**失败绝不能让整次价格更新失败**：
    # 它只是个可有可无的附加数据源，而订单簿价格已经写完了。
    write_progress(4, 5, "拉取市场历史...")
    try:
        await fetch_and_save_histories(regions, progress_cb)
    except Exception:
        # 吞的是「历史这一步的任何异常」——蓝图库缺失、TTL 查询失败、磁盘错误都算：
        # 订单簿价格已经写完了，历史只是附加数据源（日订单量/日成交量），不能连累整次更新
        log.exception("市场历史拉取失败（不影响本次价格更新）")

    elapsed = (datetime.now() - t0).total_seconds()
    write_progress(5, 5, "完成")
    log.info(f"Done! {elapsed:.0f} seconds")
    for rid, items in sorted(order_prices.items()):
        name = {v: k for k, v in TRADE_REGIONS}.get(rid, str(rid))
        log.info(f"  {name} (id={rid}): {len(items)} items")


async def fetch_baseline_only(progress_cb: Callable[[int, str], None] | None = None):
    """快速基础价格兜底 — 仅拉 /markets/prices/（1 次请求）。

    完整订单簿由主窗口后台更新（PriceUpdateWorker）负责；初始化只在全新安装
    （market_prices 为空）时调用本函数，让用户先有兜底价格数据。
    baseline 为空（网络失败）时仅告警返回——价格仍由后台更新补全。
    """
    t0 = datetime.now()
    if progress_cb:
        progress_cb(0, "获取基准价格...")
    await init_db()
    baseline = await fetch_baseline_prices()
    if not baseline:
        log.warning("基准价格拉取失败，跳过（后台价格更新会补全）")
        return
    order_prices = {rid: baseline for _, rid in TRADE_REGIONS}
    cnt = await save_prices(baseline, order_prices, [rid for _, rid in TRADE_REGIONS])
    if progress_cb:
        progress_cb(100, f"基准价格已写入 {cnt} 条")
    log.info(f"基础价格兜底完成: {cnt} 条（{(datetime.now() - t0).total_seconds():.0f}s）")


def run_price_update(
    regions: list[str] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
):
    """
    运行价格更新。

    Args:
        regions: 要更新的区域名称列表，如 ['Jita', 'Amarr']
                 None 或空列表则更新全部四大贸易中心
        progress_cb: 可选进度回调 `(pct, 文案)`，pct 为 0-100 的整数。
                     默认 None —— 既有调用方（初始化向导、CLI）不受影响
    """
    try:
        target_regions = [(name, rid) for name, rid in TRADE_REGIONS if not regions or name in regions]
        asyncio.run(main(target_regions, progress_cb))
    except KeyboardInterrupt:
        log.warning("用户中断")


if __name__ == "__main__":
    run_price_update()

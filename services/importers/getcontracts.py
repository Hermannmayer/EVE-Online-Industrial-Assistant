"""
公开合同拉取 — 4 大贸易中心公开合同 + 合同内物品

ESI 端点：
  GET /contracts/public/{region_id}/  — 分页，每页 500 条
  GET /contracts/public/items/{contract_id}/  — 合同内物品详情

两阶段：
  1. 并发拉取各区域的合同列表（分页）
  2. 对每个合同并发拉取其物品列表
  3. 批量写入数据库
"""

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

import aiohttp
import aiosqlite

from core.constants import TRADE_HUB_IDS
from core.logger import log
from core.paths import market_db_path
from services.client import GLOBAL_ESI_LIMITER, APIClient

DATABASE_PATH = market_db_path()
ESI_BASE_URL = "https://esi.evetech.net/latest"

TRADE_REGIONS = list(TRADE_HUB_IDS.items())

# 合同类型映射
CONTRACT_TYPE_MAP = {
    "item_exchange": "物品交换",
    "auction": "拍卖",
    "courier": "运输",
}


async def init_db():
    """初始化合同相关数据库表。

    合同表是 market.db 里的**可重建缓存**（全部字段都能按星域从 ESI 重新拉回来，无任何
    用户产生数据），所以按克制条款第 3 条不进 `schema_migrations.py`，表结构变了直接重建。

    旧结构（含 `status`/`availability` 两个死列、`days_completed`、`run`）与现结构不兼容，
    而 `CREATE TABLE IF NOT EXISTS` 改不了已存在的表 —— 判到旧结构就整表重建。
    **守卫是条件式而非无条件 DROP**：`init_db()` 每次拉取都会调，无条件 DROP 会把刚拉到的
    列表和物品一并抹掉。
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if await _contract_tables_are_stale(db):
            log.info("  合同表为旧结构，重建")
            await db.execute("DROP TABLE IF EXISTS contract_items")
            await db.execute("DROP TABLE IF EXISTS public_contracts")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS public_contracts (
                contract_id INTEGER PRIMARY KEY,
                region_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT,
                price REAL DEFAULT 0,
                buyout REAL DEFAULT 0,
                reward REAL DEFAULT 0,
                collateral REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                days_to_complete INTEGER DEFAULT 0,
                issuer_id INTEGER,
                issuer_corporation_id INTEGER,
                date_issued TEXT,
                date_expired TEXT,
                start_location_id INTEGER,
                end_location_id INTEGER,
                for_corporation INTEGER DEFAULT 0,
                fetch_time TEXT NOT NULL,
                items_fetched_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contract_items (
                contract_id INTEGER NOT NULL,
                record_id INTEGER NOT NULL,
                item_id INTEGER,
                type_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                is_blueprint_copy INTEGER DEFAULT 0,
                is_included INTEGER DEFAULT 1,
                material_efficiency INTEGER DEFAULT 0,
                time_efficiency INTEGER DEFAULT 0,
                runs INTEGER DEFAULT 1,
                PRIMARY KEY (contract_id, record_id)
            )
        """)
        # 索引
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_region ON public_contracts(region_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_type ON public_contracts(type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_expired ON public_contracts(date_expired)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_fetched ON public_contracts(items_fetched_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_items_type ON contract_items(type_id)")
        await db.commit()
    log.info("  合同数据库表已就绪")


#: 现结构独有的列 —— 旧表缺它，用作「该重建」的判据。
_SCHEMA_MARKER_COLUMN = "buyout"


async def _contract_tables_are_stale(db: aiosqlite.Connection) -> bool:
    """已有 public_contracts 表但缺现结构标记列 → 是旧结构，需要重建。"""
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='public_contracts'")
    if await cur.fetchone() is None:
        return False  # 表不存在，直接建新的
    cur = await db.execute("PRAGMA table_info(public_contracts)")
    cols = {row[1] for row in await cur.fetchall()}
    return _SCHEMA_MARKER_COLUMN not in cols


async def _fetch_contract_pages_detailed(session, region_id: int) -> tuple[list[dict], bool]:
    """拉取一个区域的全部公开合同（分页）。

    兼容 aiohttp.ClientSession 与 services.client.APIClient。
    Returns:
        (contracts, complete)：complete=False 表示列表拉取不完整。
    """
    all_contracts: list[dict] = []
    complete = True
    url = f"{ESI_BASE_URL}/contracts/public/{region_id}/"
    is_api_client = hasattr(session, "fetch_raw")

    if is_api_client:
        headers = await session.get_headers(f"{url}?page=1")
        if headers is None:
            log.warning(f"  区域 {region_id} 合同请求失败: 页数探测失败")
            return [], False
        total_pages = int(headers.get("X-Pages", 1))
        data = await session.fetch_raw(f"{url}?page=1") or []
        all_contracts.extend(data)
    else:
        await GLOBAL_ESI_LIMITER.acquire()
        async with session.get(url, params={"page": 1}) as resp:
            if resp.status != 200:
                log.warning(f"  区域 {region_id} 合同请求失败: HTTP {resp.status}")
                return [], False
            total_pages = int(resp.headers.get("X-Pages", 1))
            data = await resp.json()
            all_contracts.extend(data)

    if total_pages <= 1:
        return all_contracts, complete

    # 并发拉取剩余页面
    sem = asyncio.Semaphore(10)

    async def get_page(p: int):
        nonlocal complete
        async with sem:
            try:
                if is_api_client:
                    data = await session.fetch_raw(f"{url}?page={p}")
                    if data is None:
                        complete = False
                        return []
                    return data
                await GLOBAL_ESI_LIMITER.acquire()
                async with session.get(url, params={"page": p}) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    complete = False
            except Exception:
                log.exception("拉取合同页 %d 失败", p)
                complete = False
        return []

    # 分批拉取，每批 10 页
    for batch_start in range(2, total_pages + 1, 10):
        batch_end = min(batch_start + 10, total_pages + 1)
        pages = list(range(batch_start, batch_end))
        results = await asyncio.gather(*[get_page(p) for p in pages])
        for r in results:
            if r:
                all_contracts.extend(r)

    return all_contracts, complete


async def fetch_contract_pages(session: aiohttp.ClientSession, region_id: int) -> list[dict]:
    """拉取一个区域的全部公开合同（兼容旧签名，只返回列表）。"""
    contracts, _complete = await _fetch_contract_pages_detailed(session, region_id)
    return contracts


async def _fetch_contract_items_detailed(session, contract_ids: list[int]) -> tuple[dict[int, list[dict]], set[int]]:
    """并发拉取多个合同的物品列表。

    兼容 aiohttp.ClientSession 与 services.client.APIClient。
    Returns:
        (items, failed_ids)：failed_ids 为拉取失败的 contract_id。
    """
    is_api_client = hasattr(session, "fetch_raw")
    sem = asyncio.Semaphore(10)
    result: dict[int, list[dict]] = {}
    failed_ids: set[int] = set()

    async def get_items(cid: int):
        url = f"{ESI_BASE_URL}/contracts/public/items/{cid}/"
        async with sem:
            try:
                if is_api_client:
                    data = await session.fetch_raw(url)
                    if data is None:
                        result[cid] = []
                        failed_ids.add(cid)
                    else:
                        result[cid] = data
                    return
                await GLOBAL_ESI_LIMITER.acquire()
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result[cid] = data
                    else:
                        result[cid] = []
                        failed_ids.add(cid)
            except Exception:
                log.exception("拉取合同物品失败, contract_id=%d", cid)
                result[cid] = []
                failed_ids.add(cid)

    # 分批拉取，避免同时发起太多请求
    for i in range(0, len(contract_ids), 50):
        batch = contract_ids[i : i + 50]
        await asyncio.gather(*[get_items(cid) for cid in batch])

    return result, failed_ids


async def fetch_contract_items(session: aiohttp.ClientSession, contract_ids: list[int]) -> dict[int, list[dict]]:
    """并发拉取多个合同的物品列表（兼容旧签名，只返回 dict）。"""
    items, _failed = await _fetch_contract_items_detailed(session, contract_ids)
    return items


async def save_contract_list(region_id: int, contracts: list[dict], complete: bool, fetch_time: str) -> int:
    """写入一个星域的合同列表 —— 拉完立刻落库，不等物品。

    `fetch_time` 兼作**本轮标记**（带微秒，同一秒内两次拉取也不会撞），据此删掉「本轮没再见到」
    的合同（已过期 / 被撤单）。这比「先整区删表再插」安全：后者会连 `contract_items` 与
    `items_fetched_at` 一起抹掉，于是每次重拉都要重跑几万次物品请求。

    先插后删：插入的行盖上本轮标记，旧标记的行即「本轮未出现」，顺序反了会把整区删空。
    """
    if not complete:
        log.warning("  区域 %s 合同拉取不完整，保留旧数据", region_id)
        return 0

    records = [
        (
            c["contract_id"],
            region_id,
            c.get("type", ""),
            c.get("title", ""),
            c.get("price", 0),
            c.get("buyout", 0),
            c.get("reward", 0),
            c.get("collateral", 0),
            c.get("volume", 0),
            c.get("days_to_complete", 0),
            c.get("issuer_id"),
            c.get("issuer_corporation_id"),
            c.get("date_issued", ""),
            c.get("date_expired", ""),
            c.get("start_location_id"),
            c.get("end_location_id"),
            1 if c.get("for_corporation", False) else 0,
            fetch_time,
        )
        for c in contracts
    ]

    async with aiosqlite.connect(DATABASE_PATH) as db:
        for i in range(0, len(records), 500):
            await db.executemany(
                """
                INSERT INTO public_contracts
                (contract_id, region_id, type, title, price, buyout, reward, collateral,
                 volume, days_to_complete, issuer_id, issuer_corporation_id,
                 date_issued, date_expired, start_location_id, end_location_id,
                 for_corporation, fetch_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contract_id) DO UPDATE SET
                    region_id = excluded.region_id,
                    type = excluded.type,
                    title = excluded.title,
                    price = excluded.price,
                    buyout = excluded.buyout,
                    reward = excluded.reward,
                    collateral = excluded.collateral,
                    volume = excluded.volume,
                    days_to_complete = excluded.days_to_complete,
                    issuer_id = excluded.issuer_id,
                    issuer_corporation_id = excluded.issuer_corporation_id,
                    date_issued = excluded.date_issued,
                    date_expired = excluded.date_expired,
                    start_location_id = excluded.start_location_id,
                    end_location_id = excluded.end_location_id,
                    for_corporation = excluded.for_corporation,
                    fetch_time = excluded.fetch_time
                """,
                records[i : i + 500],
            )

        # 本轮未再出现的合同（已过期/被撤单）连同其物品一起清掉。先子表后主表：
        # 先删主表的话子查询恒为空，contract_items 会残留成孤儿。
        await db.execute(
            """
            DELETE FROM contract_items WHERE contract_id IN (
                SELECT contract_id FROM public_contracts WHERE region_id = ? AND fetch_time <> ?
            )
            """,
            (region_id, fetch_time),
        )
        await db.execute(
            "DELETE FROM public_contracts WHERE region_id = ? AND fetch_time <> ?",
            (region_id, fetch_time),
        )
        await db.commit()

    return len(records)


async def save_items_batch(items: dict[int, list[dict]], fetched_at: str) -> int:
    """写入一批合同的物品，并回填 `items_fetched_at`。

    `runs` 是 ESI 的键（**不是 `run`**）—— 写错会让蓝图复制品的可运行数恒为 1。
    拉取失败/无物品的合同不写 `items_fetched_at`，留给下一轮重试。
    """
    item_records = [
        (
            cid,
            it.get("record_id", 0),
            it.get("item_id"),
            it.get("type_id", 0),
            it.get("quantity", 0),
            1 if it.get("is_blueprint_copy", False) else 0,
            1 if it.get("is_included", True) else 0,
            it.get("material_efficiency", 0),
            it.get("time_efficiency", 0),
            it.get("runs", 1),
        )
        for cid, items_of in items.items()
        for it in items_of
    ]
    done_ids = list(items.keys())

    async with aiosqlite.connect(DATABASE_PATH) as db:
        for i in range(0, len(item_records), 500):
            await db.executemany(
                """
                INSERT OR REPLACE INTO contract_items
                (contract_id, record_id, item_id, type_id, quantity, is_blueprint_copy,
                 is_included, material_efficiency, time_efficiency, runs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item_records[i : i + 500],
            )
        for i in range(0, len(done_ids), 500):
            await db.executemany(
                "UPDATE public_contracts SET items_fetched_at = ? WHERE contract_id = ?",
                [(fetched_at, cid) for cid in done_ids[i : i + 500]],
            )
        await db.commit()

    return len(item_records)


#: courier 合同的 items 端点实测返回 HTTP 400，永远不要为它拉物品。
_TYPES_WITH_ITEMS = ("item_exchange", "auction")


def list_contracts_needing_items(region_id: int, contract_type: str, limit: int = 500) -> list[int]:
    """待取物品的合同，按合同价降序（贵的先补，先看到有价值的行）。

    只认 `item_exchange` / `auction` —— courier 的 items 端点实测返回 HTTP 400。
    """
    if contract_type not in _TYPES_WITH_ITEMS:
        return []
    with sqlite3.connect(DATABASE_PATH) as conn:
        rows = conn.execute(
            """
            SELECT contract_id FROM public_contracts
            WHERE region_id = ? AND type = ? AND items_fetched_at IS NULL
            ORDER BY COALESCE(NULLIF(buyout, 0), price) DESC
            LIMIT ?
            """,
            (region_id, contract_type, limit),
        ).fetchall()
    return [int(r[0]) for r in rows]


async def _fill_items_async(
    contract_ids: list[int],
    progress_cb: Callable[[int, int], None] | None,
    should_stop: Callable[[], bool] | None,
) -> int:
    """分批拉物品 + **分批回写**（不是最后一次性写）。返回写入的物品行数。"""
    if not contract_ids:
        return 0

    await init_db()
    written = 0
    total = len(contract_ids)
    done = 0

    async with APIClient(timeout=60) as session:
        for i in range(0, total, 50):
            if should_stop is not None and should_stop():
                log.info("  物品补齐被用户中断，已完成 %d/%d", done, total)
                break
            batch = contract_ids[i : i + 50]
            items, failed = await _fetch_contract_items_detailed(session, batch)
            # 拉取失败的合同不写标记，留待下轮重试
            ok_items = {cid: its for cid, its in items.items() if cid not in failed}
            if ok_items:
                written += await save_items_batch(ok_items, datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))
            done += len(batch)
            if progress_cb is not None:
                progress_cb(done, total)

    return written


def run_items_fill(
    contract_ids: list[int],
    progress_cb: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """同步入口（供 QThread worker 调用）。"""
    try:
        return asyncio.run(_fill_items_async(contract_ids, progress_cb, should_stop))
    except KeyboardInterrupt:
        log.warning("物品补齐被中断")
        return 0


async def _fetch_and_save_list(
    region_ids: list[int],
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[int, int]:
    """阶段 A：只拉合同列表，**每个星域拉完立刻落库**，不等物品。

    上一版把列表 + 全部物品拉完才一次性写库，一个星域几万次请求跑几十分钟，
    中途失败或关窗就一行都不落 —— 这是「点了刷新却什么都没有」的真因。
    """
    await init_db()
    # 带微秒：本值兼作「本轮标记」，同一秒内两次拉取也不能撞
    fetch_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    counts: dict[int, int] = {}

    async with APIClient(timeout=120) as session:
        for idx, rid in enumerate(region_ids):
            if progress_cb is not None:
                progress_cb(idx, f"拉取星域 {rid} 的合同列表...")
            log.info("  拉取星域 %s 的公开合同...", rid)
            contracts, ok = await _fetch_contract_pages_detailed(session, rid)
            counts[rid] = await save_contract_list(rid, contracts, ok, fetch_time)
            log.info("    星域 %s: 落库 %d 条", rid, counts[rid])
            if progress_cb is not None:
                progress_cb(idx + 1, f"星域 {rid} 完成")

    return counts


def run_contract_update(
    region_ids: list[int] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[int, int]:
    """拉取合同**列表**（不含物品）—— UI 的「拉取合同」按钮走这条。

    Args:
        region_ids: 要拉取的星域 id 列表；None 则拉全部贸易中心。
        progress_cb: `(已完成的星域数, 阶段文案)`
    """
    ids = region_ids or [rid for _, rid in TRADE_REGIONS]
    try:
        return asyncio.run(_fetch_and_save_list(ids, progress_cb))
    except KeyboardInterrupt:
        log.warning("用户中断")
        return {}


async def main(regions: list[tuple[str, int]] | None = None):
    """CLI 主流程：拉列表 → 落库（不含物品；物品用 `run_items_fill` 单独补）。"""
    targets = regions or TRADE_REGIONS
    log.info("=== 合同拉取: %s ===", ", ".join(n for n, _ in targets))
    t0 = datetime.now()
    counts = await _fetch_and_save_list([rid for _, rid in targets])
    log.info(
        "合同列表拉取完成! 耗时 %.0f 秒，共落库 %d 条", (datetime.now() - t0).total_seconds(), sum(counts.values())
    )


if __name__ == "__main__":
    asyncio.run(main())

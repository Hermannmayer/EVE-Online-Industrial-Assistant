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
import json
import os
from datetime import UTC, datetime

import aiohttp
import aiosqlite

from core.constants import TRADE_HUB_IDS
from core.logger import log
from core.paths import market_db_path, progress_file
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

# 合同状态映射
CONTRACT_STATUS_MAP = {
    "outstanding": "进行中",
    "in_progress": "已接受",
    "finished_issuer": "已完成",
    "finished_contractor": "已完成",
    "cancelled": "已取消",
    "expired": "已过期",
    "deleted": "已删除",
    "reversed": "已逆转",
}


def write_progress(cur: int, total: int, phase: str = ""):
    """写入进度文件供 UI 读取"""
    try:
        fp = progress_file()
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as f:
            json.dump({"current": cur, "total": total, "phase": phase}, f)
    except Exception:
        log.exception("写进度文件失败")


async def init_db():
    """初始化合同相关数据库表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS public_contracts (
                contract_id INTEGER PRIMARY KEY,
                region_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT,
                price REAL DEFAULT 0,
                reward REAL DEFAULT 0,
                collateral REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                days_completed INTEGER DEFAULT 0,
                issuer_id INTEGER,
                assignee_id INTEGER,
                availability TEXT,
                date_issued TEXT,
                date_expired TEXT,
                start_location_id INTEGER,
                end_location_id INTEGER,
                for_corporation INTEGER DEFAULT 0,
                fetch_time TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contract_items (
                contract_id INTEGER NOT NULL,
                record_id INTEGER NOT NULL,
                type_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                is_blueprint_copy INTEGER DEFAULT 0,
                is_included INTEGER DEFAULT 1,
                material_efficiency INTEGER DEFAULT 0,
                time_efficiency INTEGER DEFAULT 0,
                run INTEGER DEFAULT 1,
                PRIMARY KEY (contract_id, record_id)
            )
        """)
        # 索引
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_region ON public_contracts(region_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_type ON public_contracts(type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contracts_status ON public_contracts(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_items_type ON contract_items(type_id)")
        await db.commit()
    log.info("  合同数据库表已就绪")


async def _fetch_contract_pages_detailed(
    session, region_id: int
) -> tuple[list[dict], bool]:
    """拉取一个区域的全部公开合同（分页）。

    兼容 aiohttp.ClientSession 与 services.client.APIClient。
    Returns:
        (contracts, complete)：complete=False 表示列表拉取不完整。
    """
    all_contracts = []
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


async def _fetch_contract_items_detailed(
    session, contract_ids: list[int]
) -> tuple[dict[int, list[dict]], set[int]]:
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


async def save_contracts(
    all_contracts: dict[int, list[dict]],
    all_items: dict[int, list[dict]],
    region_ids: list[int],
    complete_regions: set[int] | None = None,
) -> tuple[int, int]:
    """批量写入合同和物品数据。

    只有 complete_regions（默认全部 region_ids）中的区域才允许替换旧数据。
    """
    fetch_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    target_region_ids = [rid for rid in region_ids if complete_regions is None or rid in complete_regions]
    if complete_regions is not None:
        skipped = [rid for rid in region_ids if rid not in complete_regions]
        if skipped:
            log.warning("  以下区域合同拉取不完整，保留旧数据: %s", skipped)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 清除被更新区域的旧数据。注意顺序：必须先删 contract_items 再删
        # public_contracts——若先删主表，子查询 SELECT contract_id FROM
        # public_contracts 恒为空，contract_items 永远清不掉（孤儿残留）。
        if target_region_ids:
            placeholders = ",".join("?" for _ in target_region_ids)
            await db.execute(
                f"""
                DELETE FROM contract_items WHERE contract_id IN (
                    SELECT contract_id FROM public_contracts WHERE region_id IN ({placeholders})
                )
            """,
                target_region_ids,
            )
        for rid in target_region_ids:
            await db.execute("DELETE FROM public_contracts WHERE region_id = ?", (rid,))

        # 写入合同（只写完整区域）
        complete_contract_ids: set[int] = set()
        contract_records = []
        for region_id, contracts in all_contracts.items():
            if region_id not in target_region_ids:
                continue
            for c in contracts:
                complete_contract_ids.add(c["contract_id"])
                contract_records.append(
                    (
                        c["contract_id"],
                        region_id,
                        c.get("type", ""),
                        c.get("status", ""),
                        c.get("title", ""),
                        c.get("price", 0),
                        c.get("reward", 0),
                        c.get("collateral", 0),
                        c.get("volume", 0),
                        c.get("days_to_complete", 0),
                        c.get("issuer_id"),
                        c.get("assignee_id"),
                        c.get("availability", ""),
                        c.get("date_issued", ""),
                        c.get("date_expired", ""),
                        c.get("start_location_id"),
                        c.get("end_location_id"),
                        1 if c.get("for_corporation", False) else 0,
                        fetch_time,
                    )
                )

        for i in range(0, len(contract_records), 500):
            await db.executemany(
                """
                INSERT OR REPLACE INTO public_contracts
                (contract_id, region_id, type, status, title, price, reward, collateral,
                 volume, days_completed, issuer_id, assignee_id, availability,
                 date_issued, date_expired, start_location_id, end_location_id,
                 for_corporation, fetch_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                contract_records[i : i + 500],
            )

        # 写入物品（只写完整区域的合同物品）
        item_records = []
        for cid, items in all_items.items():
            if cid not in complete_contract_ids:
                continue
            for it in items:
                item_records.append(
                    (
                        cid,
                        it.get("record_id", 0),
                        it.get("type_id", 0),
                        it.get("quantity", 0),
                        1 if it.get("is_blueprint_copy", False) else 0,
                        1 if it.get("is_included", True) else 0,
                        it.get("material_efficiency", 0),
                        it.get("time_efficiency", 0),
                        it.get("run", 1),
                    )
                )

        for i in range(0, len(item_records), 500):
            await db.executemany(
                """
                INSERT OR REPLACE INTO contract_items
                (contract_id, record_id, type_id, quantity, is_blueprint_copy,
                 is_included, material_efficiency, time_efficiency, run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                item_records[i : i + 500],
            )

        await db.commit()

    return len(contract_records), len(item_records)


async def main(regions: list[tuple[str, int]] | None = None):
    """主流程：拉取合同并存入数据库"""
    t0 = datetime.now()
    targets = regions or TRADE_REGIONS
    region_names = [n for n, _ in targets]
    log.info(f"=== 合同拉取: {', '.join(region_names)} ===")

    write_progress(0, 5, "初始化数据库...")
    await init_db()

    async with APIClient(timeout=120) as session:
        # 阶段 1: 拉取合同列表
        write_progress(1, 5, "拉取公开合同列表...")
        all_contracts: dict[int, list[dict]] = {}
        page_complete: dict[int, bool] = {}
        contract_region: dict[int, int] = {}
        total_contracts = 0
        for name, rid in targets:
            log.info(f"  拉取 {name} (region={rid}) 合同...")
            contracts, ok = await _fetch_contract_pages_detailed(session, rid)
            all_contracts[rid] = contracts
            page_complete[rid] = ok
            total_contracts += len(contracts)
            for c in contracts:
                contract_region[c["contract_id"]] = rid
            log.info(f"    {name}: {len(contracts)} 条合同")

        write_progress(3, 5, f"获取 {total_contracts} 条合同的物品详情...")

        # 阶段 2: 收集所有 contract_id 并拉取物品
        all_contract_ids = []
        for contracts in all_contracts.values():
            for c in contracts:
                all_contract_ids.append(c["contract_id"])

        log.info(f"  共 {len(all_contract_ids)} 个合同，获取物品详情...")
        all_items, failed_item_ids = await _fetch_contract_items_detailed(session, all_contract_ids)
        items_count = sum(len(v) for v in all_items.values())
        log.info(f"  获取 {items_count} 条物品记录")

        # 完整区域 = 合同列表完整 + 该区域所有合同物品都拉取成功
        complete_regions = {
            rid
            for rid in targets
            if page_complete.get(rid[1], False)
            and not any(cid in failed_item_ids for cid, crid in contract_region.items() if crid == rid[1])
        }

    # 阶段 3: 写入数据库
    write_progress(4, 5, "写入数据库...")
    c_cnt, i_cnt = await save_contracts(
        all_contracts, all_items, [rid for _, rid in targets], complete_regions
    )
    log.info(f"  写入 {c_cnt} 条合同, {i_cnt} 条物品")

    elapsed = (datetime.now() - t0).total_seconds()
    write_progress(5, 5, "完成")
    log.info(f"合同拉取完成! 耗时 {elapsed:.0f} 秒")

    for rid in [rid for _, rid in targets]:
        name = {v: k for k, v in TRADE_REGIONS}.get(rid, str(rid))
        count = len(all_contracts.get(rid, []))
        log.info(f"  {name} (id={rid}): {count} 条合同")


def run_contract_update(regions: list[str] | None = None):
    """
    运行合同更新。

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
    run_contract_update()

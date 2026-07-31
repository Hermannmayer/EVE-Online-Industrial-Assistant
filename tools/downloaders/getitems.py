"""
物品数据拉取 — 从 SDE zip 本地解析 typeIDs.yaml / groupIDs.yaml / marketGroups.yaml

流程：
  1. 检查本地缓存 data/typeIDs.yaml 等是否存在
  2. 若不存在 → 下载 SDE zip(~112MB)，提取所需的 YAML 文件并缓存
  3. 解析 YAML → 批量写入 reference.db 的 item 表 + market_tree 表

首次拉取需要下载一次 SDE zip，后续跳过。
"""

import asyncio
from collections.abc import Callable

import aiohttp
import aiosqlite
from tqdm import tqdm

from core.logger import log
from core.paths import reference_db_path
from tools.downloaders.sde_cache import ensure_sde_cache, load_yaml

DATABASE_PATH = reference_db_path()
BATCH_SIZE = 500
START_TYPE_ID = 17  # 基础矿物 34+ 也在范围内


async def initialize_database():
    """初始化数据库结构"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS item (
                type_id INTEGER PRIMARY KEY,
                en_name TEXT, zh_name TEXT,
                group_id INTEGER,
                en_group_name TEXT, zh_group_name TEXT,
                market_group_id INTEGER,
                en_market_group_name TEXT, zh_market_group_name TEXT,
                volume REAL, iconID INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market_tree (
                market_group_id INTEGER PRIMARY KEY,
                parent_group_id INTEGER,
                en_name TEXT, zh_name TEXT, icon_id INTEGER
            )
        """)
        await db.commit()


# ─── 写入 item 表 ───


def _build_group_lookup(data: dict) -> dict[int, tuple[str, str]]:
    result: dict[int, tuple[str, str]] = {}
    for sid, item in data.items():
        gid = int(sid) if not isinstance(sid, int) else sid
        name = item.get("name", {}) or {}
        en = (name.get("en") or "") if isinstance(name, dict) else ""
        zh = (name.get("zh") or "") if isinstance(name, dict) else ""
        result[gid] = (en, zh)
    return result


async def write_items(progress_cb: Callable[[int, str], None] | None = None):
    """从缓存的 typeIDs.yaml + groupIDs.yaml + marketGroups.yaml 批量写入 item 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM item WHERE en_name IS NOT NULL AND en_name != ''")
        row = await c.fetchone()
        named = row[0] if row else 0
        if named >= 50000:
            log.info(f"所有物品信息已就绪 ({named} 条)，跳过")
            return

    log.info("加载 SDE YAML 数据...")
    if progress_cb:
        progress_cb(45, "加载 typeIDs.yaml...")
    type_ids = load_yaml("typeIDs.yaml")
    if progress_cb:
        progress_cb(55, "加载 groupIDs.yaml...")
    groups = load_yaml("groupIDs.yaml")
    if progress_cb:
        progress_cb(60, "加载 marketGroups.yaml...")
    mkt_groups = load_yaml("marketGroups.yaml")

    group_names = _build_group_lookup(groups)
    mg_names = _build_group_lookup(mkt_groups)

    items = []
    for tid_str, tdata in type_ids.items():
        tid = int(tid_str) if not isinstance(tid_str, int) else tid_str
        if tid < START_TYPE_ID:
            continue

        name_data = tdata.get("name", {}) or {}
        en_name = (name_data.get("en") or "") if isinstance(name_data, dict) else ""
        zh_name = (name_data.get("zh") or "") if isinstance(name_data, dict) else ""
        group_id = tdata.get("groupID")
        volume = tdata.get("volume", 0.0)
        market_group_id = tdata.get("marketGroupID")

        en_group, zh_group = group_names.get(group_id, ("", ""))
        en_mkt, zh_mkt = mg_names.get(market_group_id, ("", ""))
        icon_id = (tdata.get("iconID") or 0) or (
            mg_names.get(market_group_id) and mkt_groups.get(str(market_group_id), {}).get("iconID", 0) or 0
        )

        items.append(
            (
                en_name,
                zh_name,
                group_id,
                en_group,
                zh_group,
                market_group_id,
                en_mkt,
                zh_mkt,
                volume,
                icon_id,
                tid,
            )
        )

    if not items:
        log.info("没有需要写入的物品数据")
        return

    log.info(f"共 {len(items)} 个物品，写入数据库...")
    if progress_cb:
        progress_cb(70, f"写入 {len(items)} 条物品数据...")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for i in tqdm(range(0, len(items), BATCH_SIZE), desc="物品"):
            batch = items[i : i + BATCH_SIZE]
            await db.executemany(
                """INSERT OR REPLACE INTO item
                   (en_name, zh_name, group_id, en_group_name, zh_group_name,
                    market_group_id, en_market_group_name, zh_market_group_name,
                    volume, iconID, type_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
            pct = 70 + int((i + len(batch)) / len(items) * 15)
            if progress_cb:
                progress_cb(pct, f"写入物品数据... {min(i + BATCH_SIZE, len(items))}/{len(items)}")
        await db.commit()
    log.info("物品数据写入完成")


# ─── 写入 market_tree 表 ───


async def write_market_tree():
    """从 marketGroups.yaml 写入 market_tree 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM market_tree")
        if (await c.fetchone())[0] > 500:
            log.info("market_tree 已就绪，跳过")
            return

    data = load_yaml("marketGroups.yaml")
    if not data:
        return

    rows = []
    for sid, item in data.items():
        mgid = int(sid) if not isinstance(sid, int) else sid
        name_data = item.get("nameID", item.get("name", {})) or {}
        en = (name_data.get("en") or "") if isinstance(name_data, dict) else ""
        zh = (name_data.get("zh") or "") if isinstance(name_data, dict) else ""
        rows.append((mgid, item.get("parentGroupID"), en, zh, item.get("iconID", 0)))

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM market_tree")
        await db.executemany(
            "INSERT INTO market_tree VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()
    log.info(f"market_tree 写入完成，共 {len(rows)} 条")


# ─── 主入口 ───


async def main(progress_cb: Callable[[int, str], None] | None = None):
    """主流程：检查数据状态 → 如需更新则下载 SDE zip → 解析 YAML → 批量写入

    Args:
        progress_cb: 可选进度回调 (percent: 0-100, message: str)
    """
    await initialize_database()
    if progress_cb:
        progress_cb(5, "检查数据状态...")

    async with aiosqlite.connect(DATABASE_PATH) as db:
        c1 = await db.execute("SELECT COUNT(*) FROM item WHERE en_name IS NOT NULL AND en_name != ''")
        r1 = await c1.fetchone()
        named = r1[0] if r1 else 0
        c2 = await db.execute("SELECT COUNT(*) FROM market_tree")
        r2 = await c2.fetchone()
        mt_cnt = r2[0] if r2 else 0

    if named >= 50000 and mt_cnt > 500:
        log.info(f"所有数据已就绪（item={named}, market_tree={mt_cnt}），跳过")
        if progress_cb:
            progress_cb(90, "检查缺失名称...")
        await fill_missing_item_names_from_esi(progress_cb)
        if progress_cb:
            progress_cb(100, "数据已就绪")
        return

    if progress_cb:
        progress_cb(10, "下载/加载 SDE 数据包...")
    await ensure_sde_cache()
    if named < 50000:
        if progress_cb:
            progress_cb(40, "解析物品 YAML 数据...")
        await write_items(progress_cb)
    if mt_cnt <= 500:
        if progress_cb:
            progress_cb(85, "写入市场分类树...")
        await write_market_tree()
    # ESI 补拉：SDE YAML 中缺失名称的物品（如 21009 等）
    if progress_cb:
        progress_cb(90, "补拉缺失名称...")
    await fill_missing_item_names_from_esi(progress_cb)
    if progress_cb:
        progress_cb(100, "完成")
    log.info("物品数据初始化完成")


# ─── 蓝图名称补拉 ───


async def fill_missing_blueprint_names():
    """补充 item 表中缺失的蓝图名称

    优先从缓存的 typeIDs.yaml 补拉，缓存不可用时降级到 SDE API。
    """
    import aiosqlite as _aiosqlite

    async with _aiosqlite.connect(DATABASE_PATH) as db:
        from core.paths import blueprint_db_path

        bp_db = blueprint_db_path()
        await db.execute(f"ATTACH DATABASE '{bp_db.replace(chr(92), '/')}' AS bp")
        c = await db.execute("SELECT DISTINCT blueprint_type_id FROM bp.blueprint_activities")
        all_bp_ids = [r[0] async for r in c]

        ph = ",".join("?" * len(all_bp_ids))
        c = await db.execute(
            f"SELECT type_id FROM item WHERE type_id IN ({ph}) AND (zh_name IS NULL OR zh_name = '')",
            all_bp_ids,
        )
        missing = [r[0] async for r in c]

    if not missing:
        log.info("所有蓝图名称已完整，无需补拉")
        return

    log.info(f"发现 {len(missing)} 个蓝图缺少名称，正在补拉...")

    type_ids_data = load_yaml("typeIDs.yaml")
    if type_ids_data:
        batch = []
        for i, tid in enumerate(missing):
            td = type_ids_data.get(str(tid))
            if not td:
                continue
            nd = td.get("name", {}) or {}
            en = (nd.get("en") or "") if isinstance(nd, dict) else ""
            zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
            if en or zh:
                batch.append((en, zh, tid))
            if len(batch) >= 50 or (i == len(missing) - 1 and batch):
                async with _aiosqlite.connect(DATABASE_PATH) as db:
                    await db.executemany("UPDATE item SET en_name=?, zh_name=? WHERE type_id=?", batch)
                    await db.commit()
                log.info(f"  已写入 {len(batch)} 条 ({i + 1}/{len(missing)})")
                batch.clear()
        log.info(f"补拉完成，共修复 {len(missing)} 个蓝图名称")
        return

    # 降级到 SDE API
    import aiohttp

    log.info("本地缓存不可用，降级到 SDE API 补拉...")
    API_BASE = "https://sde.jita.space/latest"
    async with aiohttp.ClientSession() as session:
        batch = []
        for i, tid in enumerate(missing):
            try:
                url = f"{API_BASE}/universe/types/{tid}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        nd = data.get("name", {})
                        en = nd.get("en", "") if isinstance(nd, dict) else ""
                        zh = nd.get("zh", "") if isinstance(nd, dict) else ""
                        if en or zh:
                            batch.append((en, zh, tid))
            except Exception:
                pass
            if len(batch) >= 50 or (i == len(missing) - 1 and batch):
                async with _aiosqlite.connect(DATABASE_PATH) as db:
                    await db.executemany("UPDATE item SET en_name=?, zh_name=? WHERE type_id=?", batch)
                    await db.commit()
                log.info(f"  已写入 {len(batch)} 条 ({i + 1}/{len(missing)})")
                batch.clear()
    log.info(f"补拉完成，共修复 {len(missing)} 个蓝图名称")


async def fill_missing_item_names_from_esi(progress_cb: Callable[[int, str], None] | None = None):
    """从 ESI 补拉 item 表中缺失名称的物品。

    用于:
      1. type_id < 178（被 START_TYPE_ID 跳过的基础矿物等）
      2. type_id >= 178 但 YAML 中没有 name 字段（如 21009 等）
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute(
            "SELECT type_id FROM item WHERE (zh_name IS NULL OR zh_name = '')" " OR (en_name IS NULL OR en_name = '')"
        )
        missing = [r[0] async for r in c]

    if not missing:
        log.info("所有物品名称已完整，无需补拉")
        if progress_cb:
            progress_cb(100, "名称已完整")
        return

    log.info(f"发现 {len(missing)} 个物品缺少名称，从 ESI 补拉...")
    BATCH = 50
    fixed = 0
    async with aiohttp.ClientSession() as session:
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            updates = []
            for tid in batch:
                try:
                    url = f"https://esi.evetech.net/latest/universe/types/{tid}/?datasource=tranquility&language=zh"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            zh_name = data.get("name", "") or ""
                            en_name = ""
                            try:
                                url_en = f"https://esi.evetech.net/latest/universe/types/{tid}/?datasource=tranquility&language=en"
                                async with session.get(url_en, timeout=aiohttp.ClientTimeout(total=15)) as resp_en:
                                    if resp_en.status == 200:
                                        en_name = (await resp_en.json()).get("name", "") or ""
                            except Exception:
                                pass
                            if en_name or zh_name:
                                updates.append((en_name, zh_name, tid))
                except Exception:
                    continue

            if updates:
                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.executemany(
                        "UPDATE item SET en_name=?, zh_name=? WHERE type_id=?",
                        updates,
                    )
                    await db.commit()
                fixed += len(updates)

            pct = min(95, int((start + BATCH) / len(missing) * 100))
            if progress_cb:
                progress_cb(pct, f"名称补拉... {min(start + BATCH, len(missing))}/{len(missing)}")
            await asyncio.sleep(0.5)

    log.info(f"ESI 补拉完成，共修复 {fixed}/{len(missing)} 个物品名称")
    if progress_cb:
        progress_cb(100, f"名称修复: {fixed}/{len(missing)}")


if __name__ == "__main__":
    asyncio.run(main())

"""
SDE 扩展数据加载器 — 将 16 个新表写入 reference.db

功能:
  - metaGroups.yaml         → meta_group 表 + item.meta_group_id
  - categories.yaml         → category 表 + item.category_id (via groupIDs.yaml)
  - typeMaterials.yaml      → reprocessing_materials 表
  - dogmaAttributes.yaml    → dogma_attribute 表
  - dogmaEffects.yaml       → dogma_effect 表
  - iconIDs.yaml            → icon_ids 表
  - staStations.yaml        → station 表（旧源 bsd/staStations.yaml；新源 npcStations.yaml
                              无 stationName → 写库走 COALESCE 保留旧站名，见 sde_cache B 段）
  - stationOperations.yaml  → station_operation 表
  - operationServices.yaml  → station_operation_service 表
  - stationServices.yaml    → station_service 表
  - researchAgents.yaml     → research_agent 表
  - npcCorporations.yaml    → npc_corporation 表
  - agents.yaml             → agent 表
  - universe/               → solar_system 表（星系名/安全等级/**区域归属**）
"""

import asyncio
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

import aiosqlite

from core.logger import log
from core.paths import reference_db_path
from services.db_locks import get_db_write_lock
from services.importers.sde_cache import (
    SDE_ZIP_PATH,
    ensure_sde_cache,
    ensure_sde_zip,
    ensure_universe_cache,
    load_universe_geo,
    load_yaml_async,
)

DATABASE_PATH = reference_db_path()
BATCH_SIZE = 500


@asynccontextmanager
async def _ref_db():
    """reference.db 写库上下文：per-DB 写锁 + 连接。

    并行初始化时 sde_data 与 implants/rigs/industry 同时写 reference.db，
    大事务会互相阻塞（database is locked）。写库阶段显式串行，
    网络拉取 / YAML 解析保持并行。
    """
    async with get_db_write_lock("ref"):
        async with aiosqlite.connect(DATABASE_PATH, timeout=30) as db:
            yield db


def _ensure_dict(data):
    """Normalize BSD YAML data (list or dict) to dict keyed by ID

    BSD 格式的 YAML 文件可能是列表（每个元素含 _id 字段）或普通字典。
    统一转为 {id: item} 字典。
    """
    if isinstance(data, list):
        result = {}
        for item in data:
            key = item.get("_id")
            if key is not None:
                result[key] = item
        return result
    return data or {}


async def initialize_database():
    """创建 16 个新表 + item 表新增列"""
    sql_statements = [
        "CREATE TABLE IF NOT EXISTS meta_group (meta_group_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT)",
        "CREATE TABLE IF NOT EXISTS reprocessing_materials (type_id INTEGER NOT NULL, material_type_id INTEGER NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (type_id, material_type_id))",
        "CREATE TABLE IF NOT EXISTS dogma_attribute (attribute_id INTEGER PRIMARY KEY, name TEXT, display_name TEXT, unit_id INTEGER, icon_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS dogma_effect (effect_id INTEGER PRIMARY KEY, effect_name TEXT, description TEXT, icon_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS icon_ids (icon_id INTEGER PRIMARY KEY, icon_file TEXT, description TEXT)",
        "CREATE TABLE IF NOT EXISTS category (category_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT)",
        "CREATE TABLE IF NOT EXISTS station (station_id INTEGER PRIMARY KEY, station_name TEXT, solar_system_id INTEGER, operation_id INTEGER, station_type_id INTEGER, corporation_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS station_operation (operation_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT)",
        "CREATE TABLE IF NOT EXISTS station_operation_service (operation_id INTEGER, service_id INTEGER, PRIMARY KEY (operation_id, service_id))",
        "CREATE TABLE IF NOT EXISTS station_service (service_id INTEGER PRIMARY KEY, service_name TEXT)",
        "CREATE TABLE IF NOT EXISTS research_agent (agent_id INTEGER PRIMARY KEY, corporation_id INTEGER, skill_type_id INTEGER, research_cost_modifier REAL)",
        "CREATE TABLE IF NOT EXISTS npc_corporation (corporation_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT)",
        "CREATE TABLE IF NOT EXISTS agent (agent_id INTEGER PRIMARY KEY, corporation_id INTEGER, division_id INTEGER, level INTEGER, location_id INTEGER, quality INTEGER)",
        "CREATE TABLE IF NOT EXISTS region (region_id INTEGER PRIMARY KEY, region_name TEXT)",
        "CREATE TABLE IF NOT EXISTS constellation (constellation_id INTEGER PRIMARY KEY, constellation_name TEXT, region_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT, region_id INTEGER, constellation_id INTEGER, security REAL)",
        "CREATE TABLE IF NOT EXISTS stargate (stargate_id INTEGER PRIMARY KEY, solar_system_id INTEGER, destination_system_id INTEGER)",
    ]
    async with _ref_db() as db:
        for sql in sql_statements:
            await db.execute(sql)
        # item 表补列：新库由 getitems 的 CREATE 直接建出这两列，这里只为**老缓存库**补。
        # 本步骤与 items 步并行，若本步先跑则 item 表尚不存在 —— 那不是错误（items 建表已带列）；
        # 其余 OperationalError（权限/损坏）必须留痕，不能静默吞掉。
        for col, col_type in [("meta_group_id", "INTEGER"), ("category_id", "INTEGER")]:
            try:
                await db.execute(f"ALTER TABLE item ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    log.info("item.%s 补列跳过：%s", col, e)
        # 名称索引（剪贴板导入的名称解析此前只能全表扫 5 万行）——item 表由 items 步骤创建，
        # 尚未建表时跳过（本步骤与 items 可并行，谁先跑都可能）
        from services.item_kind import item_name_index_sql

        cur = await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item'")
        if await cur.fetchone():
            for idx_sql in item_name_index_sql():
                await db.execute(idx_sql)
        await db.commit()
    log.info("SDE 扩展数据库表结构已初始化")


async def write_meta_groups():
    """写入 meta_group 表 + 更新 item.meta_group_id"""
    # --- 快速路径 ---
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM meta_group")
        meta_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM item WHERE meta_group_id IS NOT NULL")
        item_meta_count = (await c.fetchone())[0]
        if meta_count > 0 and item_meta_count > 10000:
            log.info("meta_group 已就绪，跳过")
            return

    # --- meta_group 表 ---
    data = await load_yaml_async("metaGroups.yaml")
    if not data:
        log.warning("metaGroups.yaml 为空，跳过")
        return

    rows = []
    for sid, item_data in data.items():
        mgid = int(sid) if not isinstance(sid, int) else sid
        nd = item_data.get("nameID") or item_data.get("name") or {}
        en = (nd.get("en") or "") if isinstance(nd, dict) else ""
        zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
        rows.append((mgid, en, zh))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO meta_group (meta_group_id, en_name, zh_name) VALUES (?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"meta_group 写入完成 ({len(rows)} 条)")

    # --- item.meta_group_id 更新 ---
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM item WHERE meta_group_id IS NOT NULL")
        if (await c.fetchone())[0] > 10000:
            log.info("item.meta_group_id 已就绪，跳过")
            return

    type_ids = await load_yaml_async("typeIDs.yaml")
    if not type_ids:
        return

    updates = []
    for tid_str, tdata in type_ids.items():
        tid = int(tid_str) if not isinstance(tid_str, int) else tid_str
        mgid = tdata.get("metaGroupID")
        if mgid is not None:
            updates.append((int(mgid), tid))

    if updates:
        async with _ref_db() as db:
            for i in range(0, len(updates), BATCH_SIZE):
                await db.executemany(
                    "UPDATE item SET meta_group_id = ? WHERE type_id = ?",
                    updates[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"item.meta_group_id 更新完成 ({len(updates)} 条)")


async def write_type_materials():
    """写入 reprocessing_materials 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM reprocessing_materials")
        if (await c.fetchone())[0] > 0:
            log.info("reprocessing_materials 已就绪，跳过")
            return

    data = await load_yaml_async("typeMaterials.yaml")
    if not data:
        log.warning("typeMaterials.yaml 为空，跳过")
        return

    rows = []
    for tid_str, tdata in data.items():
        tid = int(tid_str) if not isinstance(tid_str, int) else tid_str
        materials = tdata.get("materials", []) or []
        for mat in materials:
            rows.append((tid, mat.get("materialTypeID", 0), mat.get("quantity", 0)))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO reprocessing_materials (type_id, material_type_id, quantity) VALUES (?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"reprocessing_materials 写入完成 ({len(rows)} 条)")
    else:
        log.info("reprocessing_materials 无数据")


async def write_dogma_attributes():
    """写入 dogma_attribute 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM dogma_attribute")
        if (await c.fetchone())[0] > 500:
            log.info("dogma_attribute 已就绪，跳过")
            return

    data = await load_yaml_async("dogmaAttributes.yaml")
    if not data:
        log.warning("dogmaAttributes.yaml 为空，跳过")
        return

    rows = []
    for aid_str, adata in data.items():
        attribute_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
        name = adata.get("name", "") or ""
        display_name = adata.get("displayName") or adata.get("name") or ""
        unit_id = adata.get("unitID")
        icon_id = adata.get("iconID")
        rows.append((attribute_id, name, display_name, unit_id, icon_id))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO dogma_attribute (attribute_id, name, display_name, unit_id, icon_id) VALUES (?, ?, ?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"dogma_attribute 写入完成 ({len(rows)} 条)")


async def write_icon_ids():
    """写入 icon_ids 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM icon_ids")
        if (await c.fetchone())[0] > 0:
            log.info("icon_ids 已就绪，跳过")
            return

    data = await load_yaml_async("iconIDs.yaml")
    if not data:
        log.warning("iconIDs.yaml 为空，跳过")
        return

    rows = []
    for iid_str, idata in data.items():
        icon_id = int(iid_str) if not isinstance(iid_str, int) else iid_str
        icon_file = idata.get("iconFile", "") or ""
        description = idata.get("description", "") or ""
        rows.append((icon_id, icon_file, description))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO icon_ids (icon_id, icon_file, description) VALUES (?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"icon_ids 写入完成 ({len(rows)} 条)")


async def write_categories():
    """写入 category 表 + 更新 item.category_id"""
    # --- 快速路径 ---
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM category")
        category_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM item WHERE category_id IS NOT NULL")
        item_category_count = (await c.fetchone())[0]
        if category_count > 0 and item_category_count > 50000:
            log.info("category 已就绪，跳过")
            return

    # --- category 表 ---
    data = await load_yaml_async("categories.yaml")
    if not data:
        log.warning("categories.yaml 为空，跳过")
        return

    rows = []
    for sid, item_data in data.items():
        cid = int(sid) if not isinstance(sid, int) else sid
        nd = item_data.get("nameID") or item_data.get("name") or {}
        en = (nd.get("en") or "") if isinstance(nd, dict) else ""
        zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
        rows.append((cid, en, zh))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO category (category_id, en_name, zh_name) VALUES (?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"category 写入完成 ({len(rows)} 条)")

    # --- item.category_id 更新 ---
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM item WHERE category_id IS NOT NULL")
        if (await c.fetchone())[0] > 50000:
            log.info("item.category_id 已就绪，跳过")
            return

    groups = await load_yaml_async("groupIDs.yaml")
    if not groups:
        return

    # group_id → category_id 映射
    group_to_cat = {}
    for gid_str, gdata in groups.items():
        gid = int(gid_str) if not isinstance(gid_str, int) else gid_str
        cat_id = gdata.get("categoryID")
        if cat_id is not None:
            group_to_cat[gid] = int(cat_id)

    if group_to_cat:
        updates = [(cat_id, gid) for gid, cat_id in group_to_cat.items()]
        async with _ref_db() as db:
            # group_id 无索引时每个 UPDATE 全表扫描 5 万行（1556 个 group → 数十秒）；
            # 建索引后 O(log n) 定位。建在 items 写入之后，不影响 items 写入速度。
            await db.execute("CREATE INDEX IF NOT EXISTS idx_item_group_id ON item(group_id)")
            for i in range(0, len(updates), BATCH_SIZE):
                await db.executemany(
                    "UPDATE item SET category_id = ? WHERE group_id = ?",
                    updates[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"item.category_id 更新完成 ({len(updates)} 个 group 映射)")


def _station_rows(sta_raw) -> list[tuple]:
    """SDE station YAML → station 表行；兼容旧列表格式与新源字典格式。

    旧源 `bsd/staStations.yaml`：列表，行内 `stationID/stationName/stationTypeID/corporationID`。
    新源 `npcStations.yaml`：字典（键=stationID），**无 stationName**、字段改名
    `typeID/ownerID`；站名返回空串，由写库 SQL 的 COALESCE 保留旧值（不得清空）。
    """
    rows: list[tuple] = []
    if isinstance(sta_raw, dict):
        for raw_id, item in sta_raw.items():
            if not isinstance(item, dict):
                continue
            try:
                station_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            rows.append(
                (
                    station_id,
                    "",  # 新源没有 stationName：空串 → upsert COALESCE 保留旧站名
                    int(item["solarSystemID"]) if item.get("solarSystemID") else None,
                    int(item["operationID"]) if item.get("operationID") else None,
                    int(item["typeID"]) if item.get("typeID") else None,
                    int(item["ownerID"]) if item.get("ownerID") else None,
                )
            )
    elif isinstance(sta_raw, list):
        for item in sta_raw:
            if not isinstance(item, dict):
                continue
            raw_station_id = item.get("stationID")
            if raw_station_id is None:
                continue
            rows.append(
                (
                    int(raw_station_id),
                    item.get("stationName", "") or "",
                    int(item["solarSystemID"]) if item.get("solarSystemID") else None,
                    int(item["operationID"]) if item.get("operationID") else None,
                    int(item["stationTypeID"]) if item.get("stationTypeID") else None,
                    int(item["corporationID"]) if item.get("corporationID") else None,
                )
            )
    return rows


async def write_stations():
    """写入 station + station_operation + station_operation_service + station_service 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM station")
        station_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM station_operation")
        operation_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM station_service")
        service_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM station_operation_service")
        operation_service_count = (await c.fetchone())[0]
        if station_count > 0 and operation_count > 0 and service_count > 0 and operation_service_count > 0:
            log.info("station 相关表已就绪，跳过")
            return

    # --- station_service ---
    ss_data = _ensure_dict(await load_yaml_async("stationServices.yaml"))
    if ss_data:
        ss_rows = []
        for sid_str, sd in ss_data.items():
            service_id = int(sid_str) if not isinstance(sid_str, int) else sid_str
            raw_service_name = sd.get("serviceName", "") or ""
            if isinstance(raw_service_name, dict):
                # 新扁平源 stationServices.yaml 的 serviceName 是本地化字典（旧源是字符串）
                raw_service_name = raw_service_name.get("en") or raw_service_name.get("zh") or ""
            service_name = str(raw_service_name)
            ss_rows.append((service_id, service_name))
        if ss_rows:
            async with _ref_db() as db:
                for i in range(0, len(ss_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO station_service (service_id, service_name) VALUES (?, ?)",
                        ss_rows[i : i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"station_service 写入完成 ({len(ss_rows)} 条)")

    # --- station_operation ---
    so_data = _ensure_dict(await load_yaml_async("stationOperations.yaml"))
    if so_data:
        so_rows = []
        for oid_str, od in so_data.items():
            op_id = int(oid_str) if not isinstance(oid_str, int) else oid_str
            nd = od.get("nameID") or od.get("name") or od.get("operationName") or {}
            en = (nd.get("en") or "") if isinstance(nd, dict) else ""
            zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
            so_rows.append((op_id, en, zh))
        if so_rows:
            async with _ref_db() as db:
                for i in range(0, len(so_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO station_operation (operation_id, en_name, zh_name) VALUES (?, ?, ?)",
                        so_rows[i : i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"station_operation 写入完成 ({len(so_rows)} 条)")

    # --- station_operation_service (从 stationOperations.yaml 的 services 字段提取) ---
    sos_rows = []
    for op_id_str, od in so_data.items():
        op_id = int(op_id_str) if not isinstance(op_id_str, int) else op_id_str
        for svc in od.get("services", []) or []:
            if svc is not None:
                sos_rows.append((op_id, int(svc)))
    if sos_rows:
        async with _ref_db() as db:
            for i in range(0, len(sos_rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO station_operation_service (operation_id, service_id) VALUES (?, ?)",
                    sos_rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"station_operation_service 写入完成 ({len(sos_rows)} 条)")

    # --- station ---
    # 旧源（bsd/staStations.yaml）：列表，字段 stationID/stationName/stationTypeID/corporationID。
    # 新源（扁平包 npcStations.yaml）：字典（键=stationID），**没有 stationName**，字段改名
    # typeID/ownerID。直接 INSERT OR REPLACE 会把已有 5,154 个站名清成空串 —— 这里：
    #   ① 名字缺失时 upsert 用 COALESCE(NULLIF(excluded.station_name,''), station.station_name) 保留旧值；
    #   ② 新源没有名字的站，站名留空并记日志（ESI `/universe/stations/{id}/` 补齐为后续步骤）。
    sta_raw = await load_yaml_async("staStations.yaml")
    sta_rows = _station_rows(sta_raw)
    if sta_rows:
        async with _ref_db() as db:
            for i in range(0, len(sta_rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT INTO station "
                    "(station_id, station_name, solar_system_id, operation_id, station_type_id, corporation_id) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(station_id) DO UPDATE SET "
                    "  station_name = COALESCE(NULLIF(excluded.station_name, ''), station.station_name), "
                    "  solar_system_id = COALESCE(excluded.solar_system_id, station.solar_system_id), "
                    "  operation_id = COALESCE(excluded.operation_id, station.operation_id), "
                    "  station_type_id = COALESCE(excluded.station_type_id, station.station_type_id), "
                    "  corporation_id = COALESCE(excluded.corporation_id, station.corporation_id)",
                    sta_rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        unnamed = sum(1 for row in sta_rows if not row[1])
        if unnamed:
            log.warning(
                "station 写入完成 (%s 条)，其中 %s 条无站名（新源 npcStations.yaml 不含 stationName）"
                "—— 已保留库里已有站名；空名站名可由 ESI /universe/stations/{id}/ 后续补齐",
                len(sta_rows),
                unnamed,
            )
        else:
            log.info(f"station 写入完成 ({len(sta_rows)} 条)")


async def _ensure_region_zh_column(db: aiosqlite.Connection) -> bool:
    """reference.db（可重建缓存）**一次性**补 `region.zh_name` 列；补了 → True。

    为什么 ALTER 在业务侧：`reference.db` 是可重建缓存，按克制条款第 3 条**不进**
    `schema_migrations`（那是给 user.db 的），而 `region` 表在旧缓存里只有英文名。
    规则上仍要求「补列只有这一个入口 + 有存在性检查 + 留痕」，因此抽成本函数：
    只在列确实缺失时 ALTER 一次，其余情况零操作 —— 后续任何新增列也必须走这里，
    不允许在业务函数里散落 `ALTER TABLE`。
    """
    cur = await db.execute("PRAGMA table_info(region)")
    if "zh_name" in {r[1] for r in await cur.fetchall()}:
        return False
    log.info("reference.db（可重建缓存）补列 region.zh_name：新建缓存表结构落后于当前代码")
    await db.execute("ALTER TABLE region ADD COLUMN zh_name TEXT")
    await db.commit()
    return True


async def write_region_names(progress_cb: Callable[[int, str], None] | None = None) -> int:
    """补齐 `region.zh_name`（CCP 官方中文星域名），返回写入条数。

    `region` 表原先只有英文名（The Forge / Domain / Sinq Laison）。合同页要让用户**按名字**
    挑星域，而玩家记的是中文名 —— 且官方译名和口语名常常对不上（口语「寂静谷」，
    官方「静谧谷」），所以必须有中文名可搜。

    113 个星域各一次请求，只在缺名字时才发；补齐后重跑是空操作。
    ESI 的 `GET /universe/regions/{id}/?language=zh` 是 CCP 官方译名的来源。
    """
    async with _ref_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS region (region_id INTEGER PRIMARY KEY, region_name TEXT)")
        await _ensure_region_zh_column(db)
        cur = await db.execute("SELECT region_id FROM region WHERE zh_name IS NULL OR zh_name = ''")
        missing = [int(r[0]) for r in await cur.fetchall()]

    if not missing:
        return 0

    from services.client import APIClient

    written = 0
    async with APIClient(timeout=60) as session:
        for idx, region_id in enumerate(missing):
            if progress_cb is not None:
                progress_cb(idx, f"星域中文名 {idx}/{len(missing)}")
            data = await session.fetch(f"https://esi.evetech.net/latest/universe/regions/{region_id}/?language=zh")
            name = (data or {}).get("name")
            if not name:
                continue
            async with _ref_db() as db:
                await db.execute("UPDATE region SET zh_name = ? WHERE region_id = ?", (name, region_id))
                await db.commit()
            written += 1

    log.info("星域中文名补齐完成 (%d 条)", written)
    return written


#: 增量回填 UPDATE：只补 NULL（COALESCE 保留已有值），幂等。
_SYSTEM_GEO_UPDATE_SQL = (
    "UPDATE solar_system SET region_id = COALESCE(region_id, ?), "
    "constellation_id = COALESCE(constellation_id, ?) WHERE solar_system_id = ?"
)
_SYSTEM_REGION_UPDATE_SQL = "UPDATE solar_system SET region_id = COALESCE(region_id, ?) WHERE solar_system_id = ?"


async def _solar_system_columns(db) -> set[str]:
    """`solar_system` 表现有列（兼容极老/测试用的最小 schema）。"""
    cursor = await db.execute("PRAGMA table_info(solar_system)")
    return {str(row[1]) for row in await cursor.fetchall()}


def _region_backfill_rows(
    existing: list[tuple[int, int | None, int | None]],
    geo: dict[int, tuple[int | None, int | None]],
) -> list[tuple[int | None, int | None, int]]:
    """只挑「库里 NULL 且 SDE 能给」的行 → `[(region_id, constellation_id, solar_system_id)]`。

    幂等：第一轮跑完后，库里不再有「NULL 且 geo 有值」的行 → 第二轮返回空。
    两列都已有值的行不进来（不覆盖既有数据）；geo 里没有的星系也不进来（不误写）。
    """
    rows: list[tuple[int | None, int | None, int]] = []
    for system_id, region_id, constellation_id in existing:
        geo_region, geo_constellation = geo.get(int(system_id), (None, None))
        if (region_id is None and geo_region is not None) or (
            constellation_id is None and geo_constellation is not None
        ):
            rows.append((geo_region, geo_constellation, int(system_id)))
    return rows


async def _backfill_universe_region_ids(progress_cb=None) -> int:
    """历史库增量回填 `solar_system.region_id/constellation_id`（只补 NULL，不重导其它表）。

    reference.db 是可重建缓存，不需要 user.db 式迁移；下次应用启动自动补齐一次即收敛。
    只读 SDE zip 的 113 个 region.yaml + 1,175 个 constellation.yaml（**不解析 8,437 个
    星系 YAML**——实测单线程要 ~11 分钟），星系 ID 用库内「星系名→id」归一匹配。
    """
    t0 = time.time()
    await ensure_sde_zip()
    async with _ref_db() as db:
        columns = await _solar_system_columns(db)
        has_constellation = "constellation_id" in columns
        select_sql = (
            "SELECT solar_system_id, solar_system_name, region_id, constellation_id FROM solar_system"
            if has_constellation
            else "SELECT solar_system_id, solar_system_name, region_id, NULL FROM solar_system"
        )
        cursor = await db.execute(select_sql)
        existing = await cursor.fetchall()
        before = (await (await db.execute("SELECT COUNT(*) FROM solar_system WHERE region_id IS NULL")).fetchone())[0]
    name_to_id = {str(row[1] or ""): int(row[0]) for row in existing if row[1]}
    geo = await asyncio.to_thread(load_universe_geo, SDE_ZIP_PATH, name_to_id)
    candidates = _region_backfill_rows([(int(r[0]), r[2], r[3]) for r in existing], geo)
    if progress_cb:
        progress_cb(60, f"回填星系区域归属 {len(candidates)} 条")
    if candidates:
        # 极老/最小 schema 没有 constellation_id 列时只补 region_id（不擅自 ALTER）
        sql = _SYSTEM_GEO_UPDATE_SQL if has_constellation else _SYSTEM_REGION_UPDATE_SQL
        params = (
            candidates if has_constellation else [(region_id, system_id) for region_id, _cid, system_id in candidates]
        )
        async with _ref_db() as db:
            for i in range(0, len(params), BATCH_SIZE):
                await db.executemany(sql, params[i : i + BATCH_SIZE])
            await db.commit()
    async with _ref_db() as db:
        after = (await (await db.execute("SELECT COUNT(*) FROM solar_system WHERE region_id IS NULL")).fetchone())[0]
    log.info(
        "solar_system 区域归属增量回填：更新 %s 行（region_id NULL %s → %s，耗时 %.1fs）",
        len(candidates),
        before,
        after,
        time.time() - t0,
    )
    return len(candidates)


async def write_universe(progress_cb=None):
    """写入 solar_system 表（星系名/安全等级/**区域归属**）。

    就绪判据（task-15）：
      - 名称齐 且 region_id/constellation_id 无 NULL → 就绪跳过；
      - 名称齐 但区域归属有 NULL（历史库）→ **只增量回填** NULL 列，不动名称/安全等级；
      - 名称缺（全新库 / 空名缓存）→ 全量导入（解析 universe 树，system 已带 region_id）。
    region_id 是订单「是否在首位」反查挂单市场区域的依据；玩家建筑不在 station 表里，
    仍无法判定（不在本任务范围）。
    """
    async with _ref_db() as db:
        columns = await _solar_system_columns(db)
        c = await db.execute(
            "SELECT COUNT(*) FROM solar_system WHERE solar_system_name IS NOT NULL AND solar_system_name != ''"
        )
        named = (await c.fetchone())[0]
        if named and "region_id" not in columns:
            # 极老/最小 schema 连列都没有：没有可回填的目标，保持原「就绪即跳过」语义
            log.info("universe 相关表已就绪（该库无 region_id 列，跳过区域回填）")
            return
        region_null = 0
        const_null = 0
        if named:
            region_null = (
                await (await db.execute("SELECT COUNT(*) FROM solar_system WHERE region_id IS NULL")).fetchone()
            )[0]
            if "constellation_id" in columns:
                const_null = (
                    await (
                        await db.execute("SELECT COUNT(*) FROM solar_system WHERE constellation_id IS NULL")
                    ).fetchone()
                )[0]
    if named and region_null == 0 and const_null == 0:
        log.info("universe 相关表已就绪（含区域归属），跳过")
        return
    if named:
        await _backfill_universe_region_ids(progress_cb)
        return

    _, _, systems, _ = await ensure_universe_cache(progress_cb)
    if not systems:
        log.warning("universe 数据为空，跳过")
        return

    s_rows = []
    for s in systems:
        sid = s.get("solar_system_id") or s.get("solarSystemID")
        name = s.get("solar_system_name") or s.get("solarSystemName", "") or ""
        rid = s.get("region_id") or s.get("regionID")
        cid = s.get("constellation_id") or s.get("constellationID")
        sec = s.get("security", s.get("securityStatus", 0.0))
        if sid is not None:
            s_rows.append(
                (
                    int(sid),
                    name,
                    int(rid) if rid is not None else None,
                    int(cid) if cid is not None else None,
                    float(sec) if sec is not None else 0.0,
                )
            )
    if s_rows:
        async with _ref_db() as db:
            for i in range(0, len(s_rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO solar_system (solar_system_id, solar_system_name, region_id, constellation_id, security) VALUES (?, ?, ?, ?, ?)",
                    s_rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"solar_system 写入完成 ({len(s_rows)} 条)")


async def write_research():
    """写入 research_agent + npc_corporation + agent 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM research_agent")
        research_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM npc_corporation")
        corp_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM agent")
        agent_count = (await c.fetchone())[0]
        if research_count > 0 and corp_count > 0 and agent_count > 0:
            log.info("research 相关表已就绪，跳过")
            return

    # --- research_agent ---
    ra_data = _ensure_dict(await load_yaml_async("researchAgents.yaml"))
    if not ra_data:
        log.warning(
            "researchAgents.yaml 缺失（新扁平发布源已不发布该文件）—— research_agent 表保持原状，"
            "科研 Agent 功能沿用旧库数据；如需更新须另找数据源"
        )
    if ra_data:
        ra_rows = []
        for aid_str, ad in ra_data.items():
            agent_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
            corp_id = ad.get("corporationID")
            skill_id = ad.get("skillTypeID")
            cost_mod = ad.get("researchCostModifier", 0.0)
            ra_rows.append(
                (
                    agent_id,
                    int(corp_id) if corp_id is not None else None,
                    int(skill_id) if skill_id is not None else None,
                    float(cost_mod) if cost_mod is not None else 0.0,
                )
            )
        if ra_rows:
            async with _ref_db() as db:
                for i in range(0, len(ra_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO research_agent (agent_id, corporation_id, skill_type_id, research_cost_modifier) VALUES (?, ?, ?, ?)",
                        ra_rows[i : i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"research_agent 写入完成 ({len(ra_rows)} 条)")

    # --- npc_corporation ---
    nc_data = _ensure_dict(await load_yaml_async("npcCorporations.yaml"))
    if nc_data:
        nc_rows = []
        for cid_str, cd in nc_data.items():
            corp_id = int(cid_str) if not isinstance(cid_str, int) else cid_str
            nd = cd.get("nameID") or cd.get("name") or {}
            en = (nd.get("en") or "") if isinstance(nd, dict) else ""
            zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
            nc_rows.append((corp_id, en, zh))
        if nc_rows:
            async with _ref_db() as db:
                for i in range(0, len(nc_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO npc_corporation (corporation_id, en_name, zh_name) VALUES (?, ?, ?)",
                        nc_rows[i : i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"npc_corporation 写入完成 ({len(nc_rows)} 条)")

    # --- agent ---
    ag_data = _ensure_dict(await load_yaml_async("agents.yaml"))
    if not ag_data:
        log.warning("agents.yaml 缺失（新扁平发布源已不发布该文件）—— agent 表保持原状（沿用旧库数据）")
    if ag_data:
        ag_rows = []
        for aid_str, ad in ag_data.items():
            agent_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
            corp_id = ad.get("corporationID")
            div_id = ad.get("divisionID")
            level = ad.get("level")
            loc_id = ad.get("locationID")
            quality = ad.get("quality")
            ag_rows.append(
                (
                    agent_id,
                    int(corp_id) if corp_id is not None else None,
                    int(div_id) if div_id is not None else None,
                    int(level) if level is not None else None,
                    int(loc_id) if loc_id is not None else None,
                    int(quality) if quality is not None else None,
                )
            )
        if ag_rows:
            async with _ref_db() as db:
                for i in range(0, len(ag_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO agent (agent_id, corporation_id, division_id, level, location_id, quality) VALUES (?, ?, ?, ?, ?, ?)",
                        ag_rows[i : i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"agent 写入完成 ({len(ag_rows)} 条)")


async def write_dogma_effects():
    """写入 dogma_effect 表"""
    async with _ref_db() as db:
        c = await db.execute("SELECT COUNT(*) FROM dogma_effect")
        if (await c.fetchone())[0] > 500:
            log.info("dogma_effect 已就绪，跳过")
            return

    data = await load_yaml_async("dogmaEffects.yaml")
    if not data:
        log.warning("dogmaEffects.yaml 为空，跳过")
        return

    rows = []
    for eid_str, edata in data.items():
        effect_id = int(eid_str) if not isinstance(eid_str, int) else eid_str
        effect_name = edata.get("effectName") or edata.get("name") or ""
        description = edata.get("description", "") or ""
        icon_id = edata.get("iconID")
        rows.append((effect_id, effect_name, description, icon_id))

    if rows:
        async with _ref_db() as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO dogma_effect (effect_id, effect_name, description, icon_id) VALUES (?, ?, ?, ?)",
                    rows[i : i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"dogma_effect 写入完成 ({len(rows)} 条)")


# 不依赖 item 表的部分（仅需 SDE zip，可与 items 的下载/typeIDs 解析并行）
CORE_WRITERS = [
    ("write_type_materials", write_type_materials),
    ("write_dogma_attributes", write_dogma_attributes),
    ("write_dogma_effects", write_dogma_effects),
    ("write_icon_ids", write_icon_ids),
    ("write_stations", write_stations),
    ("write_research", write_research),
    ("write_universe", write_universe),
    # 唯一走 ESI 的一个（其余都只读 SDE zip）—— 星域中文名不在 SDE 里。
    # 幂等：已补齐时是空操作，所以放在每次初始化里跑不心疼。
    ("write_region_names", write_region_names),
]

# 依赖 item 表的部分（必须等 items 写完 item 表后执行）
ITEM_WRITERS = [
    ("write_meta_groups", write_meta_groups),
    ("write_categories", write_categories),
]


async def _run_writers(writers, progress_cb):
    """逐表写入（单表失败不影响其他）"""
    for i, (name, func) in enumerate(writers):
        if progress_cb:
            pct = 15 + int(i / max(len(writers), 1) * 75)
            progress_cb(pct, f"写入 {name}...")
        try:
            if name == "write_universe":
                # universe 解析耗时可长（首次 1-4 分钟），透传进度
                await func(progress_cb=progress_cb)
            else:
                await func()
            log.info(f"[OK] {name} 完成")
        except Exception as e:
            log.error(f"[FAIL] {name}: {e}", exc_info=True)


async def run_core(progress_cb=None):
    """SDE 扩展数据（不依赖 item 表）— universe/stations/research/dogma/materials。

    仅依赖 SDE zip，可与 items（下载 SDE / typeIDs 解析 / 写库）并行执行，
    缩短 items 完成后的等待。
    """
    if progress_cb:
        progress_cb(5, "确保 SDE 缓存就绪...")
    await ensure_sde_cache(progress_cb)
    await initialize_database()
    await _run_writers(CORE_WRITERS, progress_cb)
    if progress_cb:
        progress_cb(100, "SDE 扩展数据完成")


async def run_item_data(progress_cb=None):
    """SDE 扩展数据（依赖 item 表）— meta_groups/categories + 蓝图名称补拉。

    必须等 items 写入 item 表、blueprints 写入 blueprint 表之后执行。
    """
    await _run_writers(ITEM_WRITERS, progress_cb)
    from services.importers.getitems import fill_missing_blueprint_names

    if progress_cb:
        progress_cb(95, "补拉蓝图名称")
    await fill_missing_blueprint_names()
    if progress_cb:
        progress_cb(100, "SDE 扩展数据完成")


async def main(progress_cb=None):
    """主流程：确保 SDE 缓存就绪 → 初始化数据库 → 逐表写入（单表失败不影响其他）

    CLI/兼容入口：跑全部写入（含依赖 item 表的部分）。初始化流程使用 run_core + run_item_data。
    """
    if progress_cb:
        progress_cb(5, "确保 SDE 缓存就绪...")
    await ensure_sde_cache(progress_cb)
    await initialize_database()
    await _run_writers(CORE_WRITERS + ITEM_WRITERS, progress_cb)
    from services.importers.getitems import fill_missing_blueprint_names

    if progress_cb:
        progress_cb(95, "补拉蓝图名称")
    await fill_missing_blueprint_names()
    if progress_cb:
        progress_cb(100, "SDE 扩展数据完成")
    log.info("SDE 扩展数据初始化完成")


if __name__ == "__main__":
    asyncio.run(main())

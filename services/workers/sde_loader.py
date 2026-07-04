"""
SDE 扩展数据加载器 — 将 16 个新表写入 reference.db

功能:
  - metaGroups.yaml         → meta_group 表 + item.meta_group_id
  - categories.yaml         → category 表 + item.category_id (via groupIDs.yaml)
  - typeMaterials.yaml      → reprocessing_materials 表
  - dogmaAttributes.yaml    → dogma_attribute 表
  - dogmaEffects.yaml       → dogma_effect 表
  - iconIDs.yaml            → icon_ids 表
  - staStations.yaml        → station 表
  - stationOperations.yaml  → station_operation 表
  - operationServices.yaml  → station_operation_service 表
  - stationServices.yaml    → station_service 表
  - researchAgents.yaml     → research_agent 表
  - npcCorporations.yaml    → npc_corporation 表
  - agents.yaml             → agent 表
  - universe/               → region + constellation + solar_system + stargate 表
"""

import asyncio

import aiosqlite

from core.logger import log
from core.paths import reference_db_path
from services.workers.sde_cache import ensure_sde_cache, ensure_universe_cache, load_yaml

DATABASE_PATH = reference_db_path()
BATCH_SIZE = 500


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
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for sql in sql_statements:
            await db.execute(sql)
        # item 表新增列
        for col, col_type in [("meta_group_id", "INTEGER"), ("category_id", "INTEGER")]:
            try:
                await db.execute(f"ALTER TABLE item ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass  # 列已存在
        await db.commit()
    log.info("SDE 扩展数据库表结构已初始化")


async def write_meta_groups():
    """写入 meta_group 表 + 更新 item.meta_group_id"""
    # --- 快速路径 ---
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM meta_group")
        if (await c.fetchone())[0] > 0:
            log.info("meta_group 已就绪，跳过")
            return

    # --- meta_group 表 ---
    data = load_yaml("metaGroups.yaml")
    if not data:
        log.warning("metaGroups.yaml 为空，跳过")
        return

    rows = []
    for sid, item_data in data.items():
        mgid = int(sid) if not isinstance(sid, int) else sid
        nd = item_data.get("nameID", {}) or {}
        en = (nd.get("en") or "") if isinstance(nd, dict) else ""
        zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
        rows.append((mgid, en, zh))

    if rows:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO meta_group (meta_group_id, en_name, zh_name) VALUES (?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"meta_group 写入完成 ({len(rows)} 条)")

    # --- item.meta_group_id 更新 ---
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM item WHERE meta_group_id IS NOT NULL")
        if (await c.fetchone())[0] > 10000:
            log.info("item.meta_group_id 已就绪，跳过")
            return

    type_ids = load_yaml("typeIDs.yaml")
    if not type_ids:
        return

    updates = []
    for tid_str, tdata in type_ids.items():
        tid = int(tid_str) if not isinstance(tid_str, int) else tid_str
        mgid = tdata.get("metaGroupID")
        if mgid is not None:
            updates.append((int(mgid), tid))

    if updates:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(updates), BATCH_SIZE):
                await db.executemany(
                    "UPDATE item SET meta_group_id = ? WHERE type_id = ?",
                    updates[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"item.meta_group_id 更新完成 ({len(updates)} 条)")


async def write_type_materials():
    """写入 reprocessing_materials 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM reprocessing_materials")
        if (await c.fetchone())[0] > 0:
            log.info("reprocessing_materials 已就绪，跳过")
            return

    data = load_yaml("typeMaterials.yaml")
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
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO reprocessing_materials (type_id, material_type_id, quantity) VALUES (?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"reprocessing_materials 写入完成 ({len(rows)} 条)")
    else:
        log.info("reprocessing_materials 无数据")


async def write_dogma_attributes():
    """写入 dogma_attribute 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM dogma_attribute")
        if (await c.fetchone())[0] > 500:
            log.info("dogma_attribute 已就绪，跳过")
            return

    data = load_yaml("dogmaAttributes.yaml")
    if not data:
        log.warning("dogmaAttributes.yaml 为空，跳过")
        return

    rows = []
    for aid_str, adata in data.items():
        attribute_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
        name = adata.get("name", "") or ""
        display_name = adata.get("displayName", "") or ""
        unit_id = adata.get("unitID")
        icon_id = adata.get("iconID")
        rows.append((attribute_id, name, display_name, unit_id, icon_id))

    if rows:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO dogma_attribute (attribute_id, name, display_name, unit_id, icon_id) VALUES (?, ?, ?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"dogma_attribute 写入完成 ({len(rows)} 条)")


async def write_icon_ids():
    """写入 icon_ids 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM icon_ids")
        if (await c.fetchone())[0] > 0:
            log.info("icon_ids 已就绪，跳过")
            return

    data = load_yaml("iconIDs.yaml")
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
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO icon_ids (icon_id, icon_file, description) VALUES (?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"icon_ids 写入完成 ({len(rows)} 条)")


async def write_categories():
    """写入 category 表 + 更新 item.category_id"""
    # --- 快速路径 ---
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM category")
        if (await c.fetchone())[0] > 0:
            log.info("category 已就绪，跳过")
            return

    # --- category 表 ---
    data = load_yaml("categories.yaml")
    if not data:
        log.warning("categories.yaml 为空，跳过")
        return

    rows = []
    for sid, item_data in data.items():
        cid = int(sid) if not isinstance(sid, int) else sid
        nd = item_data.get("nameID", {}) or {}
        en = (nd.get("en") or "") if isinstance(nd, dict) else ""
        zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
        rows.append((cid, en, zh))

    if rows:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO category (category_id, en_name, zh_name) VALUES (?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"category 写入完成 ({len(rows)} 条)")

    # --- item.category_id 更新 ---
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM item WHERE category_id IS NOT NULL")
        if (await c.fetchone())[0] > 50000:
            log.info("item.category_id 已就绪，跳过")
            return

    groups = load_yaml("groupIDs.yaml")
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
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(updates), BATCH_SIZE):
                await db.executemany(
                    "UPDATE item SET category_id = ? WHERE group_id = ?",
                    updates[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"item.category_id 更新完成 ({len(updates)} 个 group 映射)")


async def write_stations():
    """写入 station + station_operation + station_operation_service + station_service 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM station")
        if (await c.fetchone())[0] > 0:
            log.info("station 相关表已就绪，跳过")
            return

    # --- station_service ---
    ss_data = _ensure_dict(load_yaml("stationServices.yaml"))
    if ss_data:
        ss_rows = []
        for sid_str, sd in ss_data.items():
            service_id = int(sid_str) if not isinstance(sid_str, int) else sid_str
            service_name = sd.get("serviceName", "") or ""
            ss_rows.append((service_id, service_name))
        if ss_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(ss_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO station_service (service_id, service_name) VALUES (?, ?)",
                        ss_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"station_service 写入完成 ({len(ss_rows)} 条)")

    # --- station_operation ---
    so_data = _ensure_dict(load_yaml("stationOperations.yaml"))
    if so_data:
        so_rows = []
        for oid_str, od in so_data.items():
            op_id = int(oid_str) if not isinstance(oid_str, int) else oid_str
            nd = od.get("nameID", {}) or {}
            en = (nd.get("en") or "") if isinstance(nd, dict) else ""
            zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
            so_rows.append((op_id, en, zh))
        if so_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(so_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO station_operation (operation_id, en_name, zh_name) VALUES (?, ?, ?)",
                        so_rows[i:i + BATCH_SIZE],
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
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(sos_rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO station_operation_service (operation_id, service_id) VALUES (?, ?)",
                    sos_rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"station_operation_service 写入完成 ({len(sos_rows)} 条)")

    # --- station（BSD 格式：列表，用 stationID 而非 _id）---
    sta_raw = load_yaml("staStations.yaml")
    if isinstance(sta_raw, list) and sta_raw:
        sta_rows = []
        for item in sta_raw:
            station_id = item.get("stationID")
            if station_id is None:
                continue
            sta_rows.append((
                int(station_id),
                item.get("stationName", "") or "",
                int(item["solarSystemID"]) if item.get("solarSystemID") else None,
                int(item["operationID"]) if item.get("operationID") else None,
                int(item["stationTypeID"]) if item.get("stationTypeID") else None,
                int(item["corporationID"]) if item.get("corporationID") else None,
            ))
        if sta_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(sta_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO station (station_id, station_name, solar_system_id, operation_id, station_type_id, corporation_id) VALUES (?, ?, ?, ?, ?, ?)",
                        sta_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"station 写入完成 ({len(sta_rows)} 条)")


async def write_universe():
    """写入 region + constellation + solar_system + stargate 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM region")
        if (await c.fetchone())[0] > 0:
            log.info("universe 相关表已就绪，跳过")
            return

    regions, constellations, systems, stargates = await ensure_universe_cache()
    if not any([regions, constellations, systems, stargates]):
        log.warning("universe 数据为空，跳过")
        return

    # --- region ---
    if regions:
        r_rows = []
        for r in regions:
            rid = r.get("region_id") or r.get("regionID")
            name = r.get("regionName", "") or ""
            if rid is not None:
                r_rows.append((int(rid), name))
        if r_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(r_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO region (region_id, region_name) VALUES (?, ?)",
                        r_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"region 写入完成 ({len(r_rows)} 条)")

    # --- constellation ---
    if constellations:
        c_rows = []
        for c in constellations:
            cid = c.get("constellation_id") or c.get("constellationID")
            name = c.get("constellationName", "") or ""
            rid = c.get("regionID")
            if cid is not None:
                c_rows.append((
                    int(cid),
                    name,
                    int(rid) if rid is not None else None,
                ))
        if c_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(c_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO constellation (constellation_id, constellation_name, region_id) VALUES (?, ?, ?)",
                        c_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"constellation 写入完成 ({len(c_rows)} 条)")

    # --- solar_system ---
    if systems:
        s_rows = []
        for s in systems:
            sid = s.get("solar_system_id") or s.get("solarSystemID")
            name = s.get("solarSystemName", "") or ""
            rid = s.get("regionID")
            cid = s.get("constellationID")
            sec = s.get("security", s.get("securityStatus", 0.0))
            if sid is not None:
                s_rows.append((
                    int(sid),
                    name,
                    int(rid) if rid is not None else None,
                    int(cid) if cid is not None else None,
                    float(sec) if sec is not None else 0.0,
                ))
        if s_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(s_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO solar_system (solar_system_id, solar_system_name, region_id, constellation_id, security) VALUES (?, ?, ?, ?, ?)",
                        s_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"solar_system 写入完成 ({len(s_rows)} 条)")

    # --- stargate ---
    if stargates:
        g_rows = []
        for g in stargates:
            g_rows.append((
                int(g["stargate_id"]),
                int(g["solar_system_id"]),
                int(g["destination_system_id"]),
            ))
        if g_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(g_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO stargate (stargate_id, solar_system_id, destination_system_id) VALUES (?, ?, ?)",
                        g_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"stargate 写入完成 ({len(g_rows)} 条)")


async def write_research():
    """写入 research_agent + npc_corporation + agent 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM research_agent")
        if (await c.fetchone())[0] > 0:
            log.info("research 相关表已就绪，跳过")
            return

    # --- research_agent ---
    ra_data = _ensure_dict(load_yaml("researchAgents.yaml"))
    if ra_data:
        ra_rows = []
        for aid_str, ad in ra_data.items():
            agent_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
            corp_id = ad.get("corporationID")
            skill_id = ad.get("skillTypeID")
            cost_mod = ad.get("researchCostModifier", 0.0)
            ra_rows.append((
                agent_id,
                int(corp_id) if corp_id is not None else None,
                int(skill_id) if skill_id is not None else None,
                float(cost_mod) if cost_mod is not None else 0.0,
            ))
        if ra_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(ra_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO research_agent (agent_id, corporation_id, skill_type_id, research_cost_modifier) VALUES (?, ?, ?, ?)",
                        ra_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"research_agent 写入完成 ({len(ra_rows)} 条)")

    # --- npc_corporation ---
    nc_data = _ensure_dict(load_yaml("npcCorporations.yaml"))
    if nc_data:
        nc_rows = []
        for cid_str, cd in nc_data.items():
            corp_id = int(cid_str) if not isinstance(cid_str, int) else cid_str
            nd = cd.get("nameID", {}) or {}
            en = (nd.get("en") or "") if isinstance(nd, dict) else ""
            zh = (nd.get("zh") or "") if isinstance(nd, dict) else ""
            nc_rows.append((corp_id, en, zh))
        if nc_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(nc_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO npc_corporation (corporation_id, en_name, zh_name) VALUES (?, ?, ?)",
                        nc_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"npc_corporation 写入完成 ({len(nc_rows)} 条)")

    # --- agent ---
    ag_data = _ensure_dict(load_yaml("agents.yaml"))
    if ag_data:
        ag_rows = []
        for aid_str, ad in ag_data.items():
            agent_id = int(aid_str) if not isinstance(aid_str, int) else aid_str
            corp_id = ad.get("corporationID")
            div_id = ad.get("divisionID")
            level = ad.get("level")
            loc_id = ad.get("locationID")
            quality = ad.get("quality")
            ag_rows.append((
                agent_id,
                int(corp_id) if corp_id is not None else None,
                int(div_id) if div_id is not None else None,
                int(level) if level is not None else None,
                int(loc_id) if loc_id is not None else None,
                int(quality) if quality is not None else None,
            ))
        if ag_rows:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                for i in range(0, len(ag_rows), BATCH_SIZE):
                    await db.executemany(
                        "INSERT OR REPLACE INTO agent (agent_id, corporation_id, division_id, level, location_id, quality) VALUES (?, ?, ?, ?, ?, ?)",
                        ag_rows[i:i + BATCH_SIZE],
                    )
                await db.commit()
            log.info(f"agent 写入完成 ({len(ag_rows)} 条)")


async def write_dogma_effects():
    """写入 dogma_effect 表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        c = await db.execute("SELECT COUNT(*) FROM dogma_effect")
        if (await c.fetchone())[0] > 500:
            log.info("dogma_effect 已就绪，跳过")
            return

    data = load_yaml("dogmaEffects.yaml")
    if not data:
        log.warning("dogmaEffects.yaml 为空，跳过")
        return

    rows = []
    for eid_str, edata in data.items():
        effect_id = int(eid_str) if not isinstance(eid_str, int) else eid_str
        effect_name = edata.get("effectName", "") or ""
        description = edata.get("description", "") or ""
        icon_id = edata.get("iconID")
        rows.append((effect_id, effect_name, description, icon_id))

    if rows:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(rows), BATCH_SIZE):
                await db.executemany(
                    "INSERT OR REPLACE INTO dogma_effect (effect_id, effect_name, description, icon_id) VALUES (?, ?, ?, ?)",
                    rows[i:i + BATCH_SIZE],
                )
            await db.commit()
        log.info(f"dogma_effect 写入完成 ({len(rows)} 条)")


async def main():
    """主流程：确保 SDE 缓存就绪 → 初始化数据库 → 逐表写入（单表失败不影响其他）"""
    await ensure_sde_cache()
    await initialize_database()

    functions = [
        ("write_meta_groups", write_meta_groups),
        ("write_categories", write_categories),
        ("write_type_materials", write_type_materials),
        ("write_dogma_attributes", write_dogma_attributes),
        ("write_dogma_effects", write_dogma_effects),
        ("write_icon_ids", write_icon_ids),
        ("write_stations", write_stations),
        ("write_research", write_research),
        ("write_universe", write_universe),
    ]

    for name, func in functions:
        try:
            await func()
            log.info(f"[OK] {name} 完成")
        except Exception as e:
            log.error(f"[FAIL] {name}: {e}", exc_info=True)

    log.info("SDE 扩展数据初始化完成")


if __name__ == "__main__":
    asyncio.run(main())

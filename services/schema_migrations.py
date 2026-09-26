"""
集中式数据库 Schema 版本管理 — PRAGMA user_version

用法: ensure_all_schemas() 在 Main.py 启动时调用。
所有 schema 变更必须在此注册迁移函数，不得在业务代码中写 ALTER TABLE。

版本号: 整数，从 1 开始。PRAGMA user_version = 0 视为"未知旧库"。

自动备份: 每次检测到需要迁移的库，先 VACUUM INTO 一份快照到
<库目录>/backups/ 下（保留最近 BACKUP_KEEP 份），迁移失败/回滚后可手动恢复。
"""

import glob
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime

from core.logger import log
from core.paths import BP_DB_PATH, MKT_DB_PATH, REF_DB_PATH, USR_DB_PATH

# 迁移前自动备份保留份数
BACKUP_KEEP = 5

# ── 当前 Schema 版本 ──
# 每次有 schema 变更时加 1
DB_SCHEMA_VERSIONS: dict[str, int] = {
    "ref": 1,
    "mkt": 4,  # v1→v2: adjusted_price 列; v2→v3: market_prices(fetch_time) 索引; v3→v4: market_volume_snapshots 统计信息（**不建索引**，理由见迁移函数）
    "user": 20,  # v1→v2: user_blueprints.cost_per_run;  v2→v3: production_plans 扩展列;  v3→v4: production_plans 执行列;  v4→v5: 机库/计划星系列 + facility_cost_mult 补齐;  v5→v6: hangars 设施类型/设施税/改件;  v6→v7: plan_blueprint_bindings 多蓝图绑定表;  v7→v8: 回填空星系计划（从材料机库带出）;  v8→v9: 修复 production_plans 缺 v2 扩展列的历史库;  v9→v10: production_plans 扣减快照列（撤销精确返还）;  v10→v11: price_snapshots 表收口到迁移;  v11→v12: production_plans 引用式子项需求列（source_mother_ids/component_parent_type_id/demand，共享合并+母项联动重算）;  v12→v13: production_plans 科研作业列（activity/decryptor_type_id/success_rate/research_target_level/actual_output_runs）;  v13→v14: 修复「版本已到 13 但科研列缺失」的历史库;  v14→v15: production_plans 启动成本快照列（material_cost_snapshot，入库/撤销按启动时成本）;  v15→v16: user_blueprints 原图权威化（runs<0 → is_bpo=1/runs=0，-1 退场）;  v16→v17: asset_snapshots / open_orders 表;  v17→v18: asset_snapshots.line_value 列（运行中产线价值）+ order_events 台账表;  v18→v19: esi_tokens 表（按角色绑定的 ESI 刷新令牌）;  v19→v20: open_orders 归属列（char_id/is_corp —— 挂单变动按「角色 × 军团单」分组比较，多来源并存时不再互相误判成交）
    "bp": 3,  # v1→v2: blueprint_materials.wastefactor 列;  v2→v3: 蓝图表查找索引（逐件研究成本 37×）
}

# 数据库路径映射（与 database_manager.py 保持同步）
_DB_PATH_MAP = {
    "ref": REF_DB_PATH,
    "mkt": MKT_DB_PATH,
    "user": USR_DB_PATH,
    "bp": BP_DB_PATH,
}

# ── 迁移函数 ──
# 签名: (db_path: str) -> str  返回人类可读描述


def _migrate_mkt_v1_to_v2(db_path: str) -> str:
    """v1→v2: market_prices 新增 adjusted_price 列（EIV 计算用）"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "market_prices"):
            return "market_prices 表不存在，跳过"
        conn.execute("ALTER TABLE market_prices ADD COLUMN adjusted_price REAL DEFAULT 0.0")
        conn.commit()
        return "新增 adjusted_price 列"
    except sqlite3.OperationalError as e:
        if "duplicate" in str(e).lower():
            return "adjusted_price 列已存在（跳过）"
        raise
    finally:
        conn.close()


def _migrate_mkt_v2_to_v3(db_path: str) -> str:
    """v2→v3: market_prices(fetch_time) 索引 — 加速 MAX(fetch_time) 与按时间过滤（主线程查询）"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "market_prices"):
            return "market_prices 表不存在，跳过"
        conn.execute("CREATE INDEX IF NOT EXISTS idx_market_prices_fetch_time ON market_prices(fetch_time)")
        conn.commit()
        return "新增 market_prices(fetch_time) 索引"
    finally:
        conn.close()


def _migrate_mkt_v3_to_v4(db_path: str) -> str:
    """v3→v4: 为 market_volume_snapshots 收集统计信息（挂单变化聚合查询的规划器输入）。

    **刻意不建 `(region_id, date)` 索引** —— 2026-09-26 在真实 63.8 万行库上实测：
    加了那个索引，SQLite 改用 region_id 单列去探，丢掉 join 侧
    `(type_id, region_id, date)` 主键的精确定位，查询从 **168 ms 变成 5760 ms（34× 慢）**；
    而 `ANALYZE` 之后规划器改用主键跳扫（`ANY(type_id) AND region_id=? AND date>?`），
    查询 **153 ms** —— 既不盲扫，也不比基线慢。索引在这里是负收益，见 AUDIT-20260926.md 的 P2-2。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "market_volume_snapshots"):
            return "market_volume_snapshots 表不存在，跳过"
        conn.execute("ANALYZE market_volume_snapshots")  # 实测 132 ms / 638,837 行
        conn.commit()
        return "已收集 market_volume_snapshots 统计信息（挂单变化聚合走主键跳扫）"
    finally:
        conn.close()


def _migrate_user_v1_to_v2(db_path: str) -> str:
    """v1→v2: user_blueprints 新增 cost_per_run 列"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "user_blueprints"):
            return "user_blueprints 表不存在，跳过"
        conn.execute("ALTER TABLE user_blueprints ADD COLUMN cost_per_run REAL DEFAULT 0")
        conn.commit()
        return "新增 cost_per_run 列"
    except sqlite3.OperationalError as e:
        if "duplicate" in str(e).lower():
            return "cost_per_run 列已存在（跳过）"
        raise
    finally:
        conn.close()


# production_plans 的 v2 扩展列（v2→v3 首次加入；v8→v9 对「迁移先于建表」的历史库重新补齐）
_PRODUCTION_PLANS_V2_EXT_COLUMNS: list[tuple[str, str]] = [
    ("calculated_time", "REAL DEFAULT 0"),
    ("notes", "TEXT DEFAULT ''"),
    ("group_number", "INTEGER DEFAULT 0"),
    ("sub_level", "INTEGER DEFAULT 0"),
    ("output_location", "TEXT DEFAULT ''"),
    ("market_margin", "REAL DEFAULT 0"),
    ("personal_margin", "REAL DEFAULT 0"),
    ("daily_output", "REAL DEFAULT 0"),
    ("materials_ready", "INTEGER DEFAULT 0"),
    ("iskph", "REAL DEFAULT 0"),
    ("deposit_hangar_id", "INTEGER DEFAULT NULL"),
    ("deposited", "INTEGER DEFAULT 0"),
]


def _migrate_user_v2_to_v3(db_path: str) -> str:
    """v2→v3: production_plans 新增各扩展列"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(db_path, "production_plans", _PRODUCTION_PLANS_V2_EXT_COLUMNS)
    return f"production_plans 扩展列 (新增 {net} 列)"


def _migrate_user_v3_to_v4(db_path: str) -> str:
    """v3→v4: production_plans 新增生产执行列（绑定蓝图/材料机库/缺口）"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(
        db_path,
        "production_plans",
        [
            ("assigned_blueprint_id", "INTEGER DEFAULT NULL"),
            ("mat_hangar_id", "INTEGER DEFAULT NULL"),
            ("material_short", "TEXT DEFAULT ''"),
        ],
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prod_plans_assigned_bp ON production_plans(assigned_blueprint_id)")
        conn.commit()
    finally:
        conn.close()
    return f"production_plans 执行列 (新增 {net} 列 + 索引)"


def _migrate_user_v4_to_v5(db_path: str) -> str:
    """v4→v5: hangars/production_plans 加 solar_system_id，并补 v2→v3 遗漏的 facility_cost_mult。

    facility_cost_mult 此前仅存在于 CREATE TABLE 路径，ALTER 迁移遗漏；
    老库在此一并补齐，避免成本计算读到 NULL。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "hangars") and not _table_exists(conn, "production_plans"):
            return "hangars/production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = 0
    net += _add_columns(db_path, "hangars", [("solar_system_id", "INTEGER DEFAULT NULL")])
    net += _add_columns(
        db_path,
        "production_plans",
        [
            ("solar_system_id", "INTEGER DEFAULT NULL"),
            ("facility_cost_mult", "REAL DEFAULT 1.0"),
        ],
    )
    return f"机库/计划加 solar_system_id (新增 {net} 列)"


def _migrate_user_v5_to_v6(db_path: str) -> str:
    """v5→v6: hangars 加设施类型/设施税/改件 JSON 列（机库级工业配置）"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "hangars"):
            return "hangars 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(
        db_path,
        "hangars",
        [
            ("facility_type", "TEXT DEFAULT NULL"),
            ("facility_tax", "REAL DEFAULT NULL"),
            ("rigs", "TEXT DEFAULT NULL"),
        ],
    )
    return f"hangars 工业配置列 (新增 {net} 列)"


def _migrate_user_v6_to_v7(db_path: str) -> str:
    """v6→v7: plan_blueprint_bindings 多蓝图绑定表（一条计划绑定多张库存蓝图）"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plan_blueprint_bindings ("
            "plan_id INTEGER NOT NULL, blueprint_id INTEGER NOT NULL, runs_used INTEGER DEFAULT 0, "
            "PRIMARY KEY (plan_id, blueprint_id))"
        )
        conn.commit()
        return "新增 plan_blueprint_bindings 多蓝图绑定表"
    finally:
        conn.close()


def _migrate_user_v7_to_v8(db_path: str) -> str:
    """v7→v8: 回填 production_plans 空星系快照（从材料机库带出）。

    修复成本核算用错星系（空快照 → 回退 sell_hub=吉他 SCI）的历史数据：
    只填补 solar_system_id 为空且有材料机库的计划；机库无星系/未绑定 → 保持 NULL。
    幂等：只 UPDATE 为 NULL 的行，重复运行不产生变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans") or not _table_exists(conn, "hangars"):
            return "production_plans/hangars 表不存在，跳过"
        cur = conn.execute(
            """
            UPDATE production_plans
            SET solar_system_id = (
                SELECT solar_system_id FROM hangars WHERE hangars.id = production_plans.mat_hangar_id
            )
            WHERE solar_system_id IS NULL AND mat_hangar_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM hangars
                  WHERE hangars.id = production_plans.mat_hangar_id AND solar_system_id IS NOT NULL
              )
            """
        )
        conn.commit()
        return f"回填 {cur.rowcount} 条空星系计划"
    finally:
        conn.close()


def _migrate_user_v8_to_v9(db_path: str) -> str:
    """v8→v9: 对缺失 v2 扩展列的 production_plans 重新补列。

    成因：v2→v3 迁移在 production_plans 尚未建表时运行会跳过加列但仍升版本，
    之后按 CREATE TABLE 路径（industry_view.PLAN_DB_SCHEMA）建出的表缺这 12 列，
    运行时报 no such column（倒计时补算 / 建计划 / 完成入库均受影响）。
    幂等：已存在的列跳过，重复运行无变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(db_path, "production_plans", _PRODUCTION_PLANS_V2_EXT_COLUMNS)
    return f"production_plans 补齐 v2 扩展列 (新增 {net} 列)"


def _migrate_user_v9_to_v10(db_path: str) -> str:
    """v9→v10: production_plans 新增 deducted_materials 列（启动扣减快照，撤销精确返还）。

    撤销返还不再依赖评分重算（评分失败时静默丢材料），
    改为 start_plan 持久化实际扣减 {type_id: qty} JSON，cancel_plan 直接读快照。
    幂等：已存在的列跳过，重复运行无变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(db_path, "production_plans", [("deducted_materials", "TEXT DEFAULT ''")])
    return f"production_plans 扣减快照列 (新增 {net} 列)"


def _migrate_user_v15_to_v16(db_path: str) -> str:
    """v15→v16: user_blueprints 原图权威化（runs<0 → is_bpo=1, runs=0）。

    `runs = -1` 长期被子系统反着读：蓝图管理界面按它显示「无限」
    （ui_qml/models/inventory_helpers），生产计划侧却归零判
    「0 可用流程」（plan_execution._bp_available_runs）。后果是绑定了这类行的
    计划永远「蓝图流程不足」，强制下线时被 consume_bpc_runs 当成 0 流程行
    **删除**——用户库里 86 张真原图正处于这个状态。

    游戏里原图的「流程数」列本就显示 -1，故 `runs < 0` 即原图。归一后
    `is_bpo` 成为「原图」的唯一权威（该状态永不消耗、永不删除），`runs` 恒为
    非负。解析侧同步把 `runs<0` 与英文 Original 判为原图，使「粘贴 → 落库」
    成为不动点（见 domain/blueprint_sync.normalize_clipboard_attr），否则下次
    剪贴板全量同步会按 is_bpo 不同把本迁移的结果删旧插新。

    第二条 UPDATE 是未来守卫：把任何 `is_bpo=1` 却带非零 runs 的行一并归一
    （现库命中 0 行），保证原图行的形态唯一。
    幂等：重复运行两条 UPDATE 各命中 0 行。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "user_blueprints"):
            return "user_blueprints 表不存在，跳过"
        neg = conn.execute("UPDATE user_blueprints SET is_bpo=1, runs=0 WHERE runs < 0").rowcount
        norm = conn.execute("UPDATE user_blueprints SET runs=0 WHERE is_bpo=1 AND runs <> 0").rowcount
        conn.commit()
    finally:
        conn.close()
    return f"原图归一：runs<0 → is_bpo=1/runs=0 共 {neg} 行；is_bpo=1 行 runs 归一 {norm} 行"


def _migrate_user_v14_to_v15(db_path: str) -> str:
    """v14→v15: production_plans 新增 material_cost_snapshot 列（启动时成本快照）。

    版本号说明：本迁移原登记为 v12→v13，与「科研作业列」相撞；合并时顺延到 v14→v15，
    使 v12 的老库依次跑完 12→13→14→15，已到 13/14 的库也能补上本列。

    入库/撤销改用**启动那一刻**的真实成本，不再被在产期间的价格重算改写：
    - 重算白名单含 in_progress（industry_view._auto_calculate_plans），会改写 material_cost
    - complete_plan 原先读 material_cost → 下线时按「最后一次重算」的口径入库
    - cancel_plan 原先读「撤销那一刻」的机库加权成本 → 与扣减时不一致

    快照 JSON：``{"total": <启动时材料总成本>, "unit": {"<type_id>": <扣减时加权平均单价>}}``。
    旧计划该列为空 → 完成/撤销回退原有逻辑（向后兼容）。
    幂等：已存在的列跳过，重复运行无变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(db_path, "production_plans", [("material_cost_snapshot", "TEXT DEFAULT ''")])
    return f"production_plans 启动成本快照列 (新增 {net} 列)"


def _migrate_user_v13_to_v14(db_path: str) -> str:
    """v13→v14: 修复「user_version 已是 13、但科研作业列不存在」的历史库。

    成因：科研列被登记为 v12→v13，而某些库的版本号已先行到 13（例如外部
    以更高版本号运行过、或版本号与迁移函数错配）。此时 v12→v13 **不会执行**
    （ensure_schema 只跑 version < target 的迁移），列永久缺失且版本已前进 ——
    与 v8→v9 修「迁移先于建表」的缺口是同一类问题（见该函数注释）。

    本迁移幂等重放加列，并把可能为 NULL 的 activity 回填成 manufacturing。
    """
    added = _add_columns(
        db_path,
        "production_plans",
        [
            ("activity", "TEXT DEFAULT 'manufacturing'"),
            ("decryptor_type_id", "INTEGER DEFAULT NULL"),
            ("success_rate", "REAL DEFAULT NULL"),
            ("research_target_level", "INTEGER DEFAULT 0"),
            ("actual_output_runs", "INTEGER DEFAULT NULL"),
        ],
    )
    # ALTER ADD COLUMN 的 DEFAULT 只作用于**新行**；已存在的行 activity 是 NULL，
    # 会让 plan_job_kinds.normalize 之外的读取方（直接读列的 SQL）拿到空值。
    backfilled = 0
    conn = sqlite3.connect(db_path)
    try:
        if _table_exists(conn, "production_plans"):
            cur = conn.execute(
                "UPDATE production_plans SET activity='manufacturing' WHERE activity IS NULL OR activity=''"
            )
            backfilled = cur.rowcount or 0
            conn.commit()
    finally:
        conn.close()
    return f"补齐科研作业列 {added} 个，回填 activity {backfilled} 行"


def _migrate_user_v12_to_v13(db_path: str) -> str:
    """v12→v13: production_plans 增科研作业列（拷贝/发明/ME-TE 研究并入计划）。

    - activity: 作业类型；旧行默认 'manufacturing'（行为完全不变）。
      取值见 domain.research：manufacturing / copying / invention /
      researching_material_efficiency / researching_time_efficiency。
    - decryptor_type_id: 发明用解码器（8 种，见 domain.research.DECRYPTORS）；NULL=不使用。
    - success_rate: 发明的用户覆盖成功率；NULL=按技能算。
    - research_target_level: ME/TE 研究的目标等级。
    - actual_output_runs: 发明完成后手填的实际产出流程；
      NULL=未回填（按期望值估算），0=发明失败，>0=实际拿到的流程数。
    """
    added = _add_columns(
        db_path,
        "production_plans",
        [
            ("activity", "TEXT DEFAULT 'manufacturing'"),
            ("decryptor_type_id", "INTEGER DEFAULT NULL"),
            ("success_rate", "REAL DEFAULT NULL"),
            ("research_target_level", "INTEGER DEFAULT 0"),
            ("actual_output_runs", "INTEGER DEFAULT NULL"),
        ],
    )
    return f"新增科研作业列 {added} 个"


def _migrate_user_v11_to_v12(db_path: str) -> str:
    """v11→v12: production_plans 增引用式子项需求列（共享合并 / 母项联动重算）。

    - source_mother_ids: 逗号分隔的母项 plan id（子项被哪些母项引用；空=普通计划/叶子）。
    - component_parent_type_id: 共享树内父组件 type_id（层级/级联删除/采购排除单表推导）。
    - demand: 全局聚合需求（跨所有引用母项）。
    """
    added = _add_columns(
        db_path,
        "production_plans",
        [
            ("source_mother_ids", "TEXT DEFAULT ''"),
            ("component_parent_type_id", "INTEGER DEFAULT NULL"),
            ("demand", "INTEGER DEFAULT 0"),
        ],
    )
    return f"新增引用式子项需求列 {added} 个"


def _migrate_user_v10_to_v11(db_path: str) -> str:
    """v10→v11: price_snapshots 表从 UI 层收口到集中迁移。

    该表用于保存计划价格快照，此前由 IndustryPage.init_plan_db 直接创建。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                region_id INTEGER NOT NULL,
                sell_price REAL,
                buy_price REAL,
                snapshot_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(type_id, region_id, snapshot_time)
            )
            """
        )
        conn.commit()
        return "新增 price_snapshots 表"
    finally:
        conn.close()


# v16→v17：资产快照 + 挂单两张表（物品查询页空闲态仪表盘）。
# 单一事实来源：迁移函数与测试共用同一段 DDL，避免测试手抄副本与迁移漂移。
_USER_V17_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snap_date TEXT NOT NULL UNIQUE,          -- YYYY-MM-DD（本地日期），每天一行
    total REAL DEFAULT 0,                    -- 总资产（库存 + 挂单 + 钱包）
    orders REAL DEFAULT 0,                   -- 挂单金额（卖单按 sell 价、买单按 buy 价）
    inventory REAL DEFAULT 0,                -- 库存材料金额
    wallet REAL DEFAULT 0,                   -- 钱包余额（用户手填）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS open_orders (
    order_id INTEGER PRIMARY KEY,
    is_buy INTEGER DEFAULT 0,
    price REAL DEFAULT 0,
    volume_total INTEGER DEFAULT 0,
    volume_remain INTEGER DEFAULT 0,
    location_id INTEGER DEFAULT 0,
    location_name TEXT DEFAULT '',
    type_id INTEGER DEFAULT 0,
    type_name TEXT DEFAULT '',
    issued TEXT DEFAULT '',
    duration INTEGER DEFAULT 0,
    char_id INTEGER DEFAULT 0,               -- 挂单归属角色（ESI 给 character_id；日志导出取 charID 列；启发式解析取不到时为 0）
    is_corp INTEGER DEFAULT 0,               -- 军团单标记（个人单/军团单是两份独立导出，混着比会把对方判成「已成交」）
    imported_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


# 订单变动台账（v17→v18）。与 `services/asset_snapshot_service.SCHEMA` 的同名表保持一致
# （那边用 IF NOT EXISTS 兜底新库/测试，两边重复执行幂等）。
_ORDER_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS order_events (
    order_id INTEGER NOT NULL,
    applied_at TEXT NOT NULL,
    outcome TEXT DEFAULT '',        -- filled / cancelled
    is_buy INTEGER DEFAULT 0,
    price REAL DEFAULT 0,
    volume INTEGER DEFAULT 0,
    delta REAL DEFAULT 0,           -- 本次对钱包余额的增减（ISK，正=加）
    PRIMARY KEY (order_id, applied_at)
);
"""


# ESI OAuth 刷新令牌（v18→v19）。**不可重建的用户数据** —— 丢了就得让用户
# 重新走一遍浏览器授权，所以放 user.db 而不是 settings.json。
# 每次刷新后必须把响应里的 refresh_token 原样写回：CCP 文档明说返回的令牌
# 可能和提交的不同（会启用轮换），只存第一次那个迟早失效。
# 使用方 `ui_qml/workers/esi_skill_worker.py` 也执行同一段 DDL 兜底：
# `sqlite3.connect` 会创建空库文件，全新安装时它可能晚于 schema 迁移才出现。
ESI_TOKENS_SQL = """
CREATE TABLE IF NOT EXISTS esi_tokens (
    character_id INTEGER PRIMARY KEY,
    character_name TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    access_expires_at TEXT,                -- %Y-%m-%dT%H:%M:%SZ，读时比较，剩 <60s 即刷新
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def _migrate_user_v16_to_v17(db_path: str) -> str:
    """v16→v17: 新增 asset_snapshots（每日资产快照）与 open_orders（挂单）两张表。

    供「物品查询页空闲态仪表盘」使用：资产折线图按天记录总资产/挂单/库存/钱包，
    挂单列表从游戏导出的本地订单文件导入。仅加表，不改既有列。
    幂等：CREATE TABLE IF NOT EXISTS，重复运行无变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_USER_V17_TABLES_SQL)
        conn.commit()
        return "新增 asset_snapshots / open_orders 表"
    except sqlite3.OperationalError as e:
        if "duplicate" in str(e).lower():
            return "asset_snapshots / open_orders 表已存在（跳过）"
        raise
    finally:
        conn.close()


def _migrate_user_v17_to_v18(db_path: str) -> str:
    """v17→v18: asset_snapshots 新增 line_value 列 + 新增 order_events 台账表。

    - ``line_value``：资产折线图第 5 条线「运行中产线价值」（只取制造中产线的
      材料占用 × 卖单价）。存量行的历史值补 0 —— 那一天没记过这条线，不该编造。
    - ``order_events``：用户确认「订单变动」（成交 / 手动撤销）后落一条台账。
      **只做记录**，不参与任何计算 —— 钱包余额的增减是当次动作做的，台账是事后可查的凭据。
      ``order_id`` 不设外键：挂单随时会被清掉，台账要留得住。
    """
    net = _add_columns(db_path, "asset_snapshots", [("line_value", "REAL DEFAULT 0")])
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_ORDER_EVENTS_SQL)
        conn.commit()
    finally:
        conn.close()
    return f"asset_snapshots.line_value (新增 {net} 列) + order_events 表"


def _migrate_user_v18_to_v19(db_path: str) -> str:
    """v18→v19: 新增 esi_tokens 表（按角色绑定 ESI 刷新令牌）。

    每个角色一行，主键是 ESI 的 character_id。只加表，不改既有列。
    幂等：CREATE TABLE IF NOT EXISTS，重复运行无变化。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(ESI_TOKENS_SQL)
        conn.commit()
        return "新增 esi_tokens 表"
    finally:
        conn.close()


def _migrate_user_v19_to_v20(db_path: str) -> str:
    """v19→v20: open_orders 加归属列 ``char_id`` / ``is_corp``。

    挂单有两个来源（游戏日志导出、ESI），一个账号还能绑多个角色，而变动识别是拿
    「表里现有的全部」和「本次拿到的全部」做差 —— 不分组就会把别的角色、或另一份
    导出（个人单 / 军团单）里的挂单判成「已成交」，进而**错误增减钱包**。

    存量行补 0（归属未知），所以升级后首次导入时这些老行不参与比较 —— 表现为
    **漏报一次而不是误扣**；``order_id`` 是主键（``INSERT OR REPLACE``），第一遍
    导入就把它们改写成真值，第二遍起恢复正常。
    """
    net = _add_columns(
        db_path,
        "open_orders",
        [("char_id", "INTEGER DEFAULT 0"), ("is_corp", "INTEGER DEFAULT 0")],
    )
    return f"open_orders.char_id/is_corp (新增 {net} 列)"


def _migrate_bp_v2_to_v3(db_path: str) -> str:
    """v2→v3: 蓝图表查找索引（实测逐件研究成本 3.92ms → 0.10ms）"""
    from services.blueprint_reader import blueprint_index_sql

    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "blueprint_materials"):
            return "蓝图表不存在，跳过"
        for sql in blueprint_index_sql():
            conn.execute(sql)
        conn.commit()
        return "蓝图查找索引已就绪"
    finally:
        conn.close()


def _migrate_bp_v1_to_v2(db_path: str) -> str:
    """v1→v2: blueprint_materials 新增 wastefactor 列"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "blueprint_materials"):
            return "blueprint_materials 表不存在，跳过"
        conn.execute("ALTER TABLE blueprint_materials ADD COLUMN wastefactor INTEGER DEFAULT 10")
        conn.commit()
        return "新增 wastefactor 列"
    except sqlite3.OperationalError as e:
        if "duplicate" in str(e).lower():
            return "wastefactor 列已存在（跳过）"
        raise
    finally:
        conn.close()


# ── 迁移函数注册 ──
# {库别名: {起始版本: 迁移函数}}
_MIGRATIONS: dict[str, dict[int, Callable[[str], str]]] = {
    "mkt": {
        1: _migrate_mkt_v1_to_v2,
        2: _migrate_mkt_v2_to_v3,
        3: _migrate_mkt_v3_to_v4,
    },
    "user": {
        1: _migrate_user_v1_to_v2,
        2: _migrate_user_v2_to_v3,
        3: _migrate_user_v3_to_v4,
        4: _migrate_user_v4_to_v5,
        5: _migrate_user_v5_to_v6,
        6: _migrate_user_v6_to_v7,
        7: _migrate_user_v7_to_v8,
        8: _migrate_user_v8_to_v9,
        9: _migrate_user_v9_to_v10,
        10: _migrate_user_v10_to_v11,
        11: _migrate_user_v11_to_v12,
        12: _migrate_user_v12_to_v13,
        13: _migrate_user_v13_to_v14,
        14: _migrate_user_v14_to_v15,
        15: _migrate_user_v15_to_v16,
        16: _migrate_user_v16_to_v17,
        17: _migrate_user_v17_to_v18,
        18: _migrate_user_v18_to_v19,
        19: _migrate_user_v19_to_v20,
    },
    "bp": {
        1: _migrate_bp_v1_to_v2,
        2: _migrate_bp_v2_to_v3,
    },
}


# ═══════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """检查连接中是否存在指定表"""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _add_columns(db_path: str, table: str, columns: list[tuple[str, str]]) -> int:
    """批量 ADD COLUMN，忽略已存在的列。返回实际新增的列数。"""
    added = 0
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, table):
            return 0
        for col_name, col_type in columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                added += 1
            except sqlite3.OperationalError as e:
                if "duplicate" in str(e).lower():
                    continue
                raise
        conn.commit()
        return added
    finally:
        conn.close()


def _open(db_path: str) -> sqlite3.Connection:
    """打开连接（带 busy_timeout，容忍启动期短暂写锁/被强杀后的句柄未释放）"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _get_version(db_path: str) -> int:
    """读取 PRAGMA user_version"""
    conn = _open(db_path)
    try:
        v = conn.execute("PRAGMA user_version").fetchone()[0]
        return int(v)
    finally:
        conn.close()


def _set_version(db_path: str, version: int):
    """写入 PRAGMA user_version"""
    conn = _open(db_path)
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def _backup_db(db_path: str) -> str | None:
    """迁移前对库做一致快照（VACUUM INTO），返回备份文件路径；失败返回 None。

    备份目录跟随库文件（<库目录>/backups/），打包环境与测试临时库自动各归其位。
    保留最近 BACKUP_KEEP 份；备份失败不阻断迁移（仅告警）。
    """
    try:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        base = os.path.basename(db_path)
        name, _ = os.path.splitext(base)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(backup_dir, f"{name}-{ts}.db")
        if os.path.exists(target):  # 秒级时间戳冲突（几乎不可能）
            os.unlink(target)
        conn = _open(db_path)
        try:
            conn.execute("VACUUM INTO ?", (target,))
        finally:
            conn.close()
        _cleanup_old_backups(backup_dir, f"{name}-*.db")
        log.info("  💾 已备份 %s → %s", base, target)
        return target
    except Exception:
        log.warning("  ⚠️ 迁移前备份失败（不阻断迁移）: %s", db_path, exc_info=True)
        return None


def _cleanup_old_backups(backup_dir: str, pattern: str, keep: int = BACKUP_KEEP) -> None:
    """保留最近 keep 份备份，删除更早的。删除失败仅告警，不阻断。"""
    try:
        backups = sorted(
            glob.glob(os.path.join(backup_dir, pattern)),
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return
    for old in backups[keep:]:
        try:
            os.remove(old)
        except OSError:
            log.warning("  ⚠️ 清理旧备份失败: %s", old, exc_info=True)


def _rebuild_table(db_path: str, table: str, create_sql: str, copy_columns: list[str]) -> None:
    """大变动迁移：重建表结构并保留数据（改列类型/拆表/合并/重命名列）。

    SQLite 的 ALTER TABLE 只支持加列；要改列类型/拆表/合并时必须走
    建新表→复制→换名的标准流程。本函数在单个事务内完成：
    旧表改名 → 建新表 → INSERT...SELECT 复制 → 删旧表。
    ALTER/DROP 在 SQLite 中均可回滚，任一步失败整体回滚，原表与数据完好。
    幂等可重入：失败已回滚，无 __old 残留。

    Args:
        db_path: 库文件路径
        table: 要重建的表名（create_sql 必须建同名表）
        create_sql: 新表完整 CREATE TABLE 语句
        copy_columns: 需从旧表复制的列名列表（新表须含这些列；新列留默认值）
    """
    old_table = f"{table}__old"
    cols = ", ".join(copy_columns)
    conn = _open(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(f"ALTER TABLE {table} RENAME TO {old_table}")
        conn.execute(create_sql)
        conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {old_table}")
        conn.execute(f"DROP TABLE {old_table}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  公开 API
# ═══════════════════════════════════════════


def ensure_schema(db_alias: str) -> dict:
    """检查并迁移单个库的 schema。

    Args:
        db_alias: 库别名 ('ref', 'mkt', 'user', 'bp')

    Returns:
        {"before": int|None, "after": int|None, "applied": list[str], "failed": bool}
        before/after 为 None 表示库文件不存在或检查失败（跳过）；failed=True 表示
        检查/迁移过程抛异常（区别于「库缺失」）。
    """
    db_path = _DB_PATH_MAP.get(db_alias)
    if not db_path or not os.path.exists(db_path):
        return {"before": None, "after": None, "applied": [], "backup": None}

    try:
        current = DB_SCHEMA_VERSIONS.get(db_alias, 1)
        on_disk = _get_version(db_path)
        applied: list[str] = []
        backup: str | None = None

        if on_disk == 0:
            # 版本 0：可能是「有表但未打版本号」的旧库/半迁移库。
            # 不能直接标 v1 跳过 —— 缺列会导致业务崩溃。从 v1 起逐版本补跑
            # 全部迁移（迁移函数均幂等：列已存在/索引已存在时跳过）。
            on_disk = 1

        if on_disk > current:
            # 数据库版本比代码还新 → 可能是降级或手改过，跳过
            log.warning("  ⚠️ %s: 数据库版本 v%s > 代码版本 v%s，跳过", db_alias, on_disk, current)
            return {"before": on_disk, "after": on_disk, "applied": [], "backup": None}

        if on_disk < current:
            # 需要迁移：先做一致快照，出问题可回滚。
            # user.db 是唯一不可重建的用户数据 —— 没有快照就不许动；缓存库（ref/mkt/bp）
            # 缺列可直接重建，不因备份失败阻断。
            backup = _backup_db(db_path)
            if backup is None and db_alias == "user":
                log.error("  ❌ user: 迁移前备份失败，已阻断迁移（用户库没有可回滚快照时不继续）")
                return {"before": on_disk, "after": on_disk, "applied": [], "failed": True, "backup": None}

        for v in range(on_disk, current):
            mig = _MIGRATIONS.get(db_alias, {}).get(v)
            if not mig:
                # 迁移函数缺失时**不得**推进版本号：旧库会被静默标成最新版，
                # 之后运行时才因缺列崩溃。宁可停在原版本并报错。
                log.error("  ❌ %s: 缺少 v%s→v%s 的迁移函数，已停止迁移（版本号保持 v%s）", db_alias, v, v + 1, v)
                return {"before": on_disk, "after": on_disk, "applied": applied, "failed": True, "backup": backup}
            applied.append(f"v{v}→v{v + 1}: {mig(db_path)}")
            _set_version(db_path, v + 1)

        # 从版本 0 起始的库（有表但未打版本号）：迁移循环可能为空
        # （如 ref 已是最新 v1），磁盘版本号仍是 0 → 必须显式落盘，
        # 否则下次启动 schema 检查永远失败、每次都弹下载窗
        if _get_version(db_path) == 0:
            _set_version(db_path, current)
            applied.append(f"v0→v{current}: 初始化版本号")

        after = current if on_disk > 0 else None
        return {"before": on_disk, "after": after, "applied": applied, "backup": backup}

    except Exception:
        log.exception("  ❌ %s: Schema 检查/迁移失败", db_alias)
        return {"before": None, "after": None, "applied": [], "failed": True, "backup": None}


def ensure_all_schemas() -> dict[str, dict]:
    """遍历所有 4 个库，执行必要的 schema 迁移。

    Returns:
        {别名: {"before": int|None, "after": int|None, "applied": [str]}}
        方便 Main.py 展示日志。
    """
    results: dict[str, dict] = {}
    for alias in DB_SCHEMA_VERSIONS:
        results[alias] = ensure_schema(alias)
    return results


def get_db_version(db_alias: str) -> int | None:
    """读取当前库的磁盘版本号（诊断用）"""
    db_path = _DB_PATH_MAP.get(db_alias)
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        return _get_version(db_path)
    except Exception:
        return None


def get_expected_version(db_alias: str) -> int | None:
    """返回代码中定义的预期版本号（诊断用）"""
    return DB_SCHEMA_VERSIONS.get(db_alias)

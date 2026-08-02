"""
集中式数据库 Schema 版本管理 — PRAGMA user_version

用法: ensure_all_schemas() 在 Main.py 启动时调用。
所有 schema 变更必须在此注册迁移函数，不得在业务代码中写 ALTER TABLE。

版本号: 整数，从 1 开始。PRAGMA user_version = 0 视为"未知旧库"。
"""

import os
import sqlite3
from collections.abc import Callable

from core.logger import log
from core.paths import BP_DB_PATH, MKT_DB_PATH, REF_DB_PATH, USR_DB_PATH

# ── 当前 Schema 版本 ──
# 每次有 schema 变更时加 1
DB_SCHEMA_VERSIONS: dict[str, int] = {
    "ref": 1,
    "mkt": 3,  # v1→v2: adjusted_price 列;  v2→v3: market_prices(fetch_time) 索引
    "user": 7,  # v1→v2: user_blueprints.cost_per_run;  v2→v3: production_plans 扩展列;  v3→v4: production_plans 执行列;  v4→v5: 机库/计划星系列 + facility_cost_mult 补齐;  v5→v6: hangars 设施类型/设施税/改件;  v6→v7: plan_blueprint_bindings 多蓝图绑定表
    "bp": 2,  # v1→v2: blueprint_materials.wastefactor 列
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


def _migrate_user_v2_to_v3(db_path: str) -> str:
    """v2→v3: production_plans 新增各扩展列"""
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
        ],
    )
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
    },
    "user": {
        1: _migrate_user_v1_to_v2,
        2: _migrate_user_v2_to_v3,
        3: _migrate_user_v3_to_v4,
        4: _migrate_user_v4_to_v5,
        5: _migrate_user_v5_to_v6,
        6: _migrate_user_v6_to_v7,
    },
    "bp": {
        1: _migrate_bp_v1_to_v2,
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


def _get_version(db_path: str) -> int:
    """读取 PRAGMA user_version"""
    conn = sqlite3.connect(db_path)
    try:
        v = conn.execute("PRAGMA user_version").fetchone()[0]
        return int(v)
    finally:
        conn.close()


def _set_version(db_path: str, version: int):
    """写入 PRAGMA user_version"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
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
        {"before": int|None, "after": int|None, "applied": list[str]}
        None 表示库文件不存在或无法打开（跳过）。
    """
    db_path = _DB_PATH_MAP.get(db_alias)
    if not db_path or not os.path.exists(db_path):
        return {"before": None, "after": None, "applied": []}

    try:
        current = DB_SCHEMA_VERSIONS.get(db_alias, 1)
        on_disk = _get_version(db_path)
        applied: list[str] = []

        if on_disk == 0:
            # 版本 0：可能是「有表但未打版本号」的旧库/半迁移库。
            # 不能直接标 v1 跳过 —— 缺列会导致业务崩溃。从 v1 起逐版本补跑
            # 全部迁移（迁移函数均幂等：列已存在/索引已存在时跳过）。
            on_disk = 1

        if on_disk > current:
            # 数据库版本比代码还新 → 可能是降级或手改过，跳过
            log.warning("  ⚠️ %s: 数据库版本 v%s > 代码版本 v%s，跳过", db_alias, on_disk, current)
            return {"before": on_disk, "after": on_disk, "applied": []}

        for v in range(on_disk, current):
            mig = _MIGRATIONS.get(db_alias, {}).get(v)
            if mig:
                label = mig(db_path)
                applied.append(f"v{v}→v{v + 1}: {label}")
            _set_version(db_path, v + 1)

        # 从版本 0 起始的库（有表但未打版本号）：迁移循环可能为空
        # （如 ref 已是最新 v1），磁盘版本号仍是 0 → 必须显式落盘，
        # 否则下次启动 schema 检查永远失败、每次都弹下载窗
        if _get_version(db_path) == 0:
            _set_version(db_path, current)
            applied.append(f"v0→v{current}: 初始化版本号")

        after = current if on_disk > 0 else None
        return {"before": on_disk, "after": after, "applied": applied}

    except Exception:
        log.exception("  ❌ %s: Schema 检查/迁移失败", db_alias)
        return {"before": None, "after": None, "applied": []}


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

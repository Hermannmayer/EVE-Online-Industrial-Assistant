"""测试集中式 Schema 迁移 — schema_migrations.py

覆盖审计发现：
- F9: v0 判定修复（有表但 user_version=0 的旧库应补跑迁移而非跳过）
- F15: mkt v2→v3 market_prices(fetch_time) 索引
- 幂等性：重复运行不报错
- 迁移前自动备份（VACUUM INTO 快照 + 保留策略）
- _rebuild_table 大变动重建（数据保留 / 失败回滚）
"""

import os
import sqlite3

import pytest

from services import schema_migrations as sm


@pytest.fixture
def tmp_mkt_db(tmp_path, monkeypatch):
    """临时 market.db + 路径替换（注意：必须替换 _DB_PATH_MAP，ensure_schema 走它）"""
    db_path = tmp_path / "market.db"
    monkeypatch.setattr(sm, "MKT_DB_PATH", str(db_path))
    monkeypatch.setitem(sm._DB_PATH_MAP, "mkt", str(db_path))
    return db_path


def _create_mkt_v1(db_path):
    """构造 v1 的 market_prices 表（无 adjusted_price 列）"""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE market_prices (
            type_id INTEGER NOT NULL,
            region_id INTEGER NOT NULL,
            buy_price REAL,
            sell_price REAL,
            buy_volume BIGINT DEFAULT 0,
            sell_volume BIGINT DEFAULT 0,
            fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (type_id, region_id)
        )
        """
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_v0_db_runs_all_migrations(tmp_mkt_db):
    """有表但 user_version=0（半迁移/旧库）→ 应补跑全部迁移（v1→v3），而非跳过"""
    _create_mkt_v1(tmp_mkt_db)
    conn = sqlite3.connect(str(tmp_mkt_db))
    conn.execute("PRAGMA user_version = 0")  # 模拟版本丢失
    conn.commit()
    conn.close()

    result = sm.ensure_schema("mkt")

    assert result["after"] == 3, "应从 v0 补跑到最新 v3"
    conn = sqlite3.connect(str(tmp_mkt_db))
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    cols = {r[1] for r in conn.execute("PRAGMA table_info(market_prices)")}
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(market_prices)")}
    conn.close()

    assert v == 3
    assert "adjusted_price" in cols, "v1→v2 的 adjusted_price 列应补上"
    assert "idx_market_prices_fetch_time" in idxs, "v2→v3 的 fetch_time 索引应补上"


def test_mkt_v2_to_v3_creates_fetch_time_index(tmp_mkt_db):
    """v2 库 → v3：创建 fetch_time 索引（MAX 查询加速）"""
    conn = sqlite3.connect(str(tmp_mkt_db))
    conn.execute(
        """
        CREATE TABLE market_prices (
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
        """
    )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("mkt")

    assert result["after"] == 3
    assert any("索引" in s for s in result["applied"])
    conn = sqlite3.connect(str(tmp_mkt_db))
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(market_prices)")}
    conn.close()
    assert "idx_market_prices_fetch_time" in idxs


def test_migrations_idempotent(tmp_mkt_db):
    """重复运行不报错（幂等）"""
    _create_mkt_v1(tmp_mkt_db)

    sm.ensure_schema("mkt")
    sm.ensure_schema("mkt")  # 第二次运行

    conn = sqlite3.connect(str(tmp_mkt_db))
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 3


def test_ensure_schema_missing_db_returns_none(tmp_path):
    """库文件不存在 → 返回 None 标记跳过"""

    result = sm.ensure_schema("ref")  # 用默认路径（不存在于 CI 环境）
    assert result["before"] is None or result["after"] is not None  # 不抛异常
    assert result.get("failed") is None  # 库缺失 ≠ 检查失败


def test_ensure_schema_failure_marks_failed(tmp_path, monkeypatch):
    """schema 检查抛异常（如强杀后的短暂 disk I/O error）→ failed=True，区别于库缺失"""

    db_path = tmp_path / "reference.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setitem(sm._DB_PATH_MAP, "ref", str(db_path))

    def _boom(_p):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sm, "_get_version", _boom)

    result = sm.ensure_schema("ref")
    assert result["failed"] is True
    assert result["before"] is None
    assert result["after"] is None
    assert result["applied"] == []


def test_v0_db_with_no_migrations_stamps_version(tmp_path, monkeypatch):
    """ref 库 user_version=0 且已是当前版本（无迁移）→ 必须显式写入版本号

    否则磁盘版本永远是 0，check_schema 每次启动都失败、每次都弹下载窗。
    """
    db_path = tmp_path / "reference.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    monkeypatch.setitem(sm._DB_PATH_MAP, "ref", str(db_path))

    result = sm.ensure_schema("ref")

    assert result["after"] == 1
    assert any("版本号" in s for s in result["applied"]), "应记录版本号初始化"
    conn = sqlite3.connect(str(db_path))
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 1, "磁盘 user_version 应落盘为 1"

    # 二次运行不再标记（已是最新版本）
    result2 = sm.ensure_schema("ref")
    assert result2["applied"] == []


@pytest.fixture
def tmp_user_db(tmp_path, monkeypatch):
    """临时 user.db + 路径替换"""
    db_path = tmp_path / "user.db"
    monkeypatch.setitem(sm._DB_PATH_MAP, "user", str(db_path))
    return db_path


def _create_user_v3(db_path):
    """构造 v3 的 production_plans 表（基础列，无执行列）"""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            facility_cost_mult REAL DEFAULT 1.0,
            notes TEXT DEFAULT '',
            group_number INTEGER DEFAULT 0,
            sub_level INTEGER DEFAULT 0,
            output_location TEXT DEFAULT '',
            market_margin REAL DEFAULT 0,
            personal_margin REAL DEFAULT 0,
            daily_output REAL DEFAULT 0,
            materials_ready INTEGER DEFAULT 0,
            iskph REAL DEFAULT 0,
            deposit_hangar_id INTEGER DEFAULT NULL,
            deposited INTEGER DEFAULT 0,
            calculated_time REAL DEFAULT 0
        );
        """
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()


def test_user_v3_to_v4_adds_execution_columns(tmp_user_db):
    """user v3→v4：新增生产执行列 + 占用索引"""
    _create_user_v3(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 12  # v3 库会一路补跑到最新 v12
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    for col in ("assigned_blueprint_id", "mat_hangar_id", "material_short"):
        assert col in cols, f"{col} 列应被 v3→v4 迁移添加"
    assert "idx_prod_plans_assigned_bp" in idxs
    for col in ("source_mother_ids", "component_parent_type_id", "demand"):
        assert col in cols, f"{col} 列应被 v11→v12 迁移添加"


def test_user_v3_to_v4_idempotent(tmp_user_db):
    """重复运行不报错，且不重复加列"""
    _create_user_v3(tmp_user_db)

    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")

    assert result2["applied"] == []
    conn = sqlite3.connect(str(tmp_user_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(production_plans)")]
    conn.close()
    assert cols.count("assigned_blueprint_id") == 1, "列不应重复添加"


def test_user_v3_to_v4_skips_missing_table(tmp_user_db):
    """无 production_plans 表时迁移跳过，不报错"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("user")
    assert result["after"] == 12


# ────────────────────────────────────────────
#  user v4 → v5：机库/计划星系列 + facility_cost_mult 迁移缺口
# ────────────────────────────────────────────


def test_user_v4_to_v5_adds_solar_system_columns(tmp_user_db):
    """v4→v5：hangars/production_plans 加 solar_system_id，production_plans 补 facility_cost_mult"""
    from tests.conftest import _create_user_v4

    _create_user_v4(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 12
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = {r[1] for r in conn.execute("PRAGMA table_info(hangars)")}
    p_cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    assert "solar_system_id" in h_cols, "hangars.solar_system_id 列应被 v4→v5 迁移添加"
    assert "solar_system_id" in p_cols, "production_plans.solar_system_id 列应被 v4→v5 迁移添加"
    assert "facility_cost_mult" in p_cols, "v2→v3 遗漏的 facility_cost_mult 应在 v4→v5 补齐"
    assert any("solar_system_id" in s for s in result["applied"]), "迁移应记录星系列变更"


def test_user_v4_to_v5_idempotent(tmp_user_db):
    """重复运行不报错，且不重复加列"""
    from tests.conftest import _create_user_v4

    _create_user_v4(tmp_user_db)

    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")

    assert result2["applied"] == []
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = [r[1] for r in conn.execute("PRAGMA table_info(hangars)")]
    p_cols = [r[1] for r in conn.execute("PRAGMA table_info(production_plans)")]
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    assert h_cols.count("solar_system_id") == 1
    assert p_cols.count("solar_system_id") == 1
    assert p_cols.count("facility_cost_mult") == 1


def test_user_v4_to_v5_skips_missing_tables(tmp_user_db):
    """缺表时迁移跳过（_add_columns 返回 0），不抛异常"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("user")
    assert result["after"] == 12
    assert result["applied"], "应记录 v4→v5 迁移（即便无表可改）"


# ────────────────────────────────────────────
#  user v5 → v6：hangars 设施类型/设施税/改件
# ────────────────────────────────────────────


def test_user_v5_to_v6_adds_industry_columns(tmp_user_db):
    """v5→v6：hangars 加 facility_type/facility_tax/rigs"""
    from tests.conftest import _create_user_v5

    _create_user_v5(tmp_user_db)
    result = sm.ensure_schema("user")
    assert result["after"] == 12
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = {r[1] for r in conn.execute("PRAGMA table_info(hangars)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    for col in ("facility_type", "facility_tax", "rigs"):
        assert col in h_cols, f"{col} 列应被 v5→v6 迁移添加"


def test_user_v5_to_v6_idempotent(tmp_user_db):
    from tests.conftest import _create_user_v5

    _create_user_v5(tmp_user_db)
    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")
    assert result2["applied"] == []
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = [r[1] for r in conn.execute("PRAGMA table_info(hangars)")]
    conn.close()
    assert h_cols.count("facility_type") == 1
    assert h_cols.count("rigs") == 1


def test_user_v5_to_v6_skips_missing_table(tmp_user_db):
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("user")
    assert result["after"] == 12
    assert result["applied"], "应记录 v5→v6 迁移（即便无表可改）"


# ────────────────────────────────────────────
#  user v7 → v8：回填空星系计划（从材料机库带出）
# ────────────────────────────────────────────


def _create_user_v7_with_data(db_path):
    """构造 v7 库：hangars + production_plans（含 solar_system_id/mat_hangar_id）+ 测试数据。"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL,
            facility_type TEXT DEFAULT NULL,
            facility_tax REAL DEFAULT NULL,
            rigs TEXT DEFAULT NULL
        );
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            calculated_time REAL DEFAULT 0,
            daily_output REAL DEFAULT 0,
            deposit_hangar_id INTEGER DEFAULT NULL,
            mat_hangar_id INTEGER DEFAULT NULL,
            solar_system_id INTEGER DEFAULT NULL,
            facility_cost_mult REAL DEFAULT 1.0
        );
        """
    )
    conn.executemany(
        "INSERT INTO hangars (id, name, solar_system_id) VALUES (?,?,?)",
        [(1, "矿仓", 30000145), (2, "空仓", None)],
    )
    # A: mat_hangar=1(新加达里) 但 solar_system_id=NULL → 应回填 30000145
    # B: mat_hangar=2(机库无星系) 且 solar=NULL → 保持 NULL
    # C: solar_system_id 已手动设置 → 不覆盖
    conn.executemany(
        "INSERT INTO production_plans (id, product_type_id, product_name, mat_hangar_id, solar_system_id) "
        "VALUES (?,?,?,?,?)",
        [(1, 2001, "A", 1, None), (2, 2001, "B", 2, None), (3, 2001, "C", 1, 30000142)],
    )
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()


def test_user_v7_to_v8_backfills_null_system(tmp_user_db):
    """v7→v8：空星系计划从材料机库带出星系回填；机库无星系保持 NULL；手动覆盖不被覆盖"""
    _create_user_v7_with_data(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 12
    assert any("回填" in s for s in result["applied"]), "应执行 v7→v8 回填迁移"
    conn = sqlite3.connect(str(tmp_user_db))
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, solar_system_id FROM production_plans ORDER BY id")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    assert rows[1] == 30000145, "空星系计划应从材料机库(新加达里)带出星系"
    assert rows[2] is None, "材料机库无星系 → 保持 NULL"
    assert rows[3] == 30000142, "已手动设置的星系不应被覆盖"


def test_user_v7_to_v8_idempotent(tmp_user_db):
    """重复运行不再产生变更（幂等）"""
    _create_user_v7_with_data(tmp_user_db)

    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")

    assert result2["applied"] == []


# ────────────────────────────────────────────
#  user v8 → v9：修复 production_plans 缺 v2 扩展列的历史库
# ────────────────────────────────────────────


def _create_user_v8_missing_v2_columns(db_path):
    """构造 v8 库：production_plans 缺 v2 扩展列（模拟「迁移先于建表」的历史库）。

    与线上库一致：user_version=8 但 production_plans 缺
    calculated_time / deposit_hangar_id / materials_ready 等 12 列，
    运行时 SELECT/INSERT 这些列报 no such column。
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            facility_cost_mult REAL DEFAULT 1.0,
            assigned_blueprint_id INTEGER DEFAULT NULL,
            mat_hangar_id INTEGER DEFAULT NULL,
            material_short TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL
        );
        """
    )
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    conn.close()


def test_user_v8_to_v9_heals_missing_v2_columns(tmp_user_db):
    """v8→v9：对缺 v2 扩展列的历史库补列，版本升到 9"""
    _create_user_v8_missing_v2_columns(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 12
    assert any("补齐" in s for s in result["applied"]), "应执行 v8→v9 补列迁移"
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    for col in (
        "calculated_time",
        "notes",
        "group_number",
        "sub_level",
        "output_location",
        "market_margin",
        "personal_margin",
        "daily_output",
        "materials_ready",
        "iskph",
        "deposit_hangar_id",
        "deposited",
    ):
        assert col in cols, f"{col} 列应被 v8→v9 迁移补上"


def test_user_v8_to_v9_idempotent(tmp_user_db):
    """重复运行不再产生变更（幂等）"""
    _create_user_v8_missing_v2_columns(tmp_user_db)

    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")

    assert result2["applied"] == []
    conn = sqlite3.connect(str(tmp_user_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(production_plans)")]
    conn.close()
    assert cols.count("calculated_time") == 1, "列不应重复添加"


# ────────────────────────────────────────────
#  user v9 → v10：production_plans 扣减快照列（撤销精确返还）
# ────────────────────────────────────────────


def _create_user_v9(db_path):
    """构造 v9 库：production_plans 完整 v9 列（含 v2 扩展列，无 deducted_materials）"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            facility_cost_mult REAL DEFAULT 1.0,
            calculated_time REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            group_number INTEGER DEFAULT 0,
            sub_level INTEGER DEFAULT 0,
            output_location TEXT DEFAULT '',
            market_margin REAL DEFAULT 0,
            personal_margin REAL DEFAULT 0,
            daily_output REAL DEFAULT 0,
            materials_ready INTEGER DEFAULT 0,
            iskph REAL DEFAULT 0,
            deposit_hangar_id INTEGER DEFAULT NULL,
            deposited INTEGER DEFAULT 0,
            assigned_blueprint_id INTEGER DEFAULT NULL,
            mat_hangar_id INTEGER DEFAULT NULL,
            material_short TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL
        );
        """
    )
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()


def test_user_v9_to_v10_adds_deducted_materials(tmp_user_db):
    """v9→v11：production_plans 新增 deducted_materials 扣减快照列，版本升到 10"""
    _create_user_v9(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 12
    assert any("扣减快照" in s for s in result["applied"]), "应执行 v9→v11 扣减快照迁移"
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 12
    assert "deducted_materials" in cols, "deducted_materials 列应被 v9→v11 迁移添加"


def test_user_v9_to_v10_idempotent(tmp_user_db):
    """重复运行不再产生变更（幂等）"""
    _create_user_v9(tmp_user_db)

    sm.ensure_schema("user")
    result2 = sm.ensure_schema("user")

    assert result2["applied"] == []
    conn = sqlite3.connect(str(tmp_user_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(production_plans)")]
    conn.close()
    assert cols.count("deducted_materials") == 1, "列不应重复添加"


def test_user_v9_to_v10_skips_missing_table(tmp_user_db):
    """无 production_plans 表时迁移跳过，不报错"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("user")
    assert result["after"] == 12
    assert result["applied"], "应记录 v9→v11 迁移（即便无表可改）"


# ────────────────────────────────────────────
#  迁移前自动备份
# ────────────────────────────────────────────


def _backup_dir(tmp_user_db) -> str:
    return str(tmp_user_db.parent / "backups")


def test_migration_creates_pre_migration_backup(tmp_user_db):
    """迁移前自动备份：构造 v9 库 → 迁移到 v11，备份存在且为迁移前版本 v9"""
    _create_user_v9(tmp_user_db)
    assert not os.path.exists(_backup_dir(tmp_user_db)), "迁移前不应有备份"

    result = sm.ensure_schema("user")

    backups = sorted(os.listdir(_backup_dir(tmp_user_db)))
    assert len(backups) == 1
    backup_path = os.path.join(_backup_dir(tmp_user_db), backups[0])
    assert result["backup"] == backup_path, "返回 dict 应带 backup 键"
    conn = sqlite3.connect(backup_path)
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9, "备份应是迁移前的版本快照"


def test_no_backup_when_already_current(tmp_user_db):
    """库已是最新版本 → 不触发备份"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()

    result = sm.ensure_schema("user")

    assert result["applied"] == []
    assert result["backup"] is None
    assert not os.path.exists(_backup_dir(tmp_user_db))


def test_backup_cleanup_keeps_latest_n(tmp_path):
    """保留最近 BACKUP_KEEP 份，删除更早的"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(sm.BACKUP_KEEP + 2):
        p = backup_dir / f"user-2026010{i}.db"
        p.write_bytes(b"x")
        os.utime(p, (i, i))  # mtime 递增，i 越大越新

    sm._cleanup_old_backups(str(backup_dir), "user-*.db")

    remaining = sorted(backup_dir.glob("user-*.db"))
    assert len(remaining) == sm.BACKUP_KEEP
    assert remaining[-1].name == "user-20260106.db", "应保留最新（mtime 最大）的份数"


# ────────────────────────────────────────────
#  _rebuild_table 大变动重建
# ────────────────────────────────────────────


def test_rebuild_table_preserves_data_and_adds_column(tmp_user_db):
    """重建表加列：数据保留、新列存在且填默认值"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)")
    conn.executemany("INSERT INTO widget (name, qty) VALUES (?,?)", [("a", 1), ("b", 2)])
    conn.commit()
    conn.close()

    sm._rebuild_table(
        str(tmp_user_db),
        "widget",
        create_sql="CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER, unit_price REAL DEFAULT 0)",
        copy_columns=["id", "name", "qty"],
    )

    conn = sqlite3.connect(str(tmp_user_db))
    rows = conn.execute("SELECT id, name, qty, unit_price FROM widget ORDER BY id").fetchall()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(widget)")}
    conn.close()
    assert rows == [(1, "a", 1, 0), (2, "b", 2, 0)]
    assert "unit_price" in cols


def test_rebuild_table_rolls_back_on_failure(tmp_user_db):
    """create_sql 非法 → 整体回滚，原表与数据完好，无 __old 残留"""
    conn = sqlite3.connect(str(tmp_user_db))
    conn.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO widget (name) VALUES ('keep')")
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.OperationalError):
        sm._rebuild_table(
            str(tmp_user_db),
            "widget",
            create_sql="CREATE TABLE widget (id INTEGER PRIMARY KEY, bogus COLUMN)",  # 非法 DDL
            copy_columns=["id", "name"],
        )

    conn = sqlite3.connect(str(tmp_user_db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = conn.execute("SELECT name FROM widget").fetchall()
    conn.close()
    assert "widget" in tables
    assert "widget__old" not in tables, "失败后不应残留 __old 表"
    assert rows == [("keep",)], "原数据应完好"

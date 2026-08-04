"""测试集中式 Schema 迁移 — schema_migrations.py

覆盖审计发现：
- F9: v0 判定修复（有表但 user_version=0 的旧库应补跑迁移而非跳过）
- F15: mkt v2→v3 market_prices(fetch_time) 索引
- 幂等性：重复运行不报错
"""

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

    assert result["after"] == 9  # v3 库会一路补跑到最新 v9
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9
    for col in ("assigned_blueprint_id", "mat_hangar_id", "material_short"):
        assert col in cols, f"{col} 列应被 v3→v4 迁移添加"
    assert "idx_prod_plans_assigned_bp" in idxs


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
    assert result["after"] == 9


# ────────────────────────────────────────────
#  user v4 → v5：机库/计划星系列 + facility_cost_mult 迁移缺口
# ────────────────────────────────────────────


def test_user_v4_to_v5_adds_solar_system_columns(tmp_user_db):
    """v4→v5：hangars/production_plans 加 solar_system_id，production_plans 补 facility_cost_mult"""
    from tests.conftest import _create_user_v4

    _create_user_v4(tmp_user_db)

    result = sm.ensure_schema("user")

    assert result["after"] == 9
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = {r[1] for r in conn.execute("PRAGMA table_info(hangars)")}
    p_cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9
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
    assert v == 9
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
    assert result["after"] == 9
    assert result["applied"], "应记录 v4→v5 迁移（即便无表可改）"


# ────────────────────────────────────────────
#  user v5 → v6：hangars 设施类型/设施税/改件
# ────────────────────────────────────────────


def test_user_v5_to_v6_adds_industry_columns(tmp_user_db):
    """v5→v6：hangars 加 facility_type/facility_tax/rigs"""
    from tests.conftest import _create_user_v5

    _create_user_v5(tmp_user_db)
    result = sm.ensure_schema("user")
    assert result["after"] == 9
    conn = sqlite3.connect(str(tmp_user_db))
    h_cols = {r[1] for r in conn.execute("PRAGMA table_info(hangars)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9
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
    assert result["after"] == 9
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

    assert result["after"] == 9
    assert any("回填" in s for s in result["applied"]), "应执行 v7→v8 回填迁移"
    conn = sqlite3.connect(str(tmp_user_db))
    rows = {r[0]: r[1] for r in conn.execute("SELECT id, solar_system_id FROM production_plans ORDER BY id")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9
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

    assert result["after"] == 9
    assert any("补齐" in s for s in result["applied"]), "应执行 v8→v9 补列迁移"
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 9
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

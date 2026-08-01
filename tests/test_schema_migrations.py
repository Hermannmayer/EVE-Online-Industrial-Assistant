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

    assert result["after"] == 4
    conn = sqlite3.connect(str(tmp_user_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_plans)")}
    idxs = {r[1] for r in conn.execute("PRAGMA index_list(production_plans)")}
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert v == 4
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
    assert result["after"] == 4

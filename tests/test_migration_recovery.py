"""测试数据库拆分/蓝图迁移的失败恢复 — 半迁移状态可重入

覆盖审计发现：
- _migrate_blueprint_db 非原子 → 改为 .tmp + os.replace 原子替换
- _migrate_split_db 以文件存在判定 → 改为 _split_migration_complete 标记
"""

import sqlite3

import pytest

import scripts.migrate_split_db as msd
from Main import _migrate_blueprint_db, _migrate_split_db


@pytest.fixture
def db_paths(tmp_path, monkeypatch):
    """临时库路径 + 模块级路径替换（避免触碰真实 database/）"""
    old_db = tmp_path / "items.db"
    ref_db = tmp_path / "reference.db"
    mkt_db = tmp_path / "market.db"
    usr_db = tmp_path / "user.db"
    bp_db = tmp_path / "blueprint.db"

    monkeypatch.setattr(msd, "database_path", lambda: str(old_db))
    monkeypatch.setattr(msd, "REF_DB_PATH", str(ref_db))
    monkeypatch.setattr(msd, "MKT_DB_PATH", str(mkt_db))
    monkeypatch.setattr(msd, "USR_DB_PATH", str(usr_db))

    import Main as main_mod

    monkeypatch.setattr(main_mod, "DB_PATH", str(old_db))
    monkeypatch.setattr(main_mod, "REF_DB_PATH", str(ref_db))
    monkeypatch.setattr(main_mod, "USR_DB_PATH", str(usr_db))
    monkeypatch.setattr(main_mod, "BP_DB_PATH", str(bp_db))

    return {"old": old_db, "ref": ref_db, "mkt": mkt_db, "usr": usr_db, "bp": bp_db}


def _make_old_db(path):
    """构造带全部旧表数据的 items.db"""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT);
        CREATE TABLE market_tree (market_group_id INTEGER PRIMARY KEY, parent_group_id INTEGER);
        CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER);
        CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_skills (blueprint_type_id INTEGER, activity TEXT, skill_type_id INTEGER, level INTEGER);
        CREATE TABLE market_prices (type_id INTEGER, region_id INTEGER, buy_price REAL, sell_price REAL);
        CREATE TABLE hangars (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, notes TEXT DEFAULT '');
        CREATE TABLE inventory_items (id INTEGER PRIMARY KEY AUTOINCREMENT, hangar_id INTEGER, type_id INTEGER, quantity INTEGER);
        CREATE TABLE production_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, product_type_id INTEGER);
        CREATE TABLE user_skills (skill_type_id INTEGER PRIMARY KEY, level INTEGER DEFAULT 5);
        """
    )
    conn.execute("INSERT INTO item (type_id, en_name, zh_name) VALUES (34, 'Tritanium', '三钛合金')")
    conn.execute(
        "INSERT INTO blueprint_products (blueprint_type_id, activity, product_type_id, quantity) VALUES (1, 'manufacturing', 34, 1)"
    )
    conn.execute("INSERT INTO hangars (name) VALUES ('测试机库')")
    conn.commit()
    conn.close()


# ── _migrate_split_db ──


def test_split_migration_complete_marker(db_paths):
    """正常迁移后写入完成标记；再次调用跳过（不重复执行）"""
    _make_old_db(db_paths["old"])
    assert _migrate_split_db() is None  # 正常执行

    conn = sqlite3.connect(str(db_paths["usr"]))
    marker = conn.execute("SELECT 1 FROM _split_migration_complete WHERE id = 1").fetchone()
    conn.close()
    assert marker, "user.db 应写入 _split_migration_complete 标记"
    assert db_paths["ref"].exists() and db_paths["mkt"].exists()

    # 再次调用：有标记 → 直接返回（以 monkeypatch 记录调用次数验证）
    calls = []
    original = msd.run_migration

    def _counting_run():
        calls.append(1)
        return original()

    msd.run_migration = _counting_run
    try:
        _migrate_split_db()
    finally:
        msd.run_migration = original
    assert calls == [], "有完成标记时不应再次执行迁移"


def test_split_migration_half_done_resumes(db_paths, monkeypatch):
    """半迁移（三个库文件都在但无标记）→ 重跑补齐，数据不丢"""
    _make_old_db(db_paths["old"])
    # 模拟半迁移：仅创建了 ref/mkt 库和部分表，无完成标记
    sqlite3.connect(str(db_paths["ref"])).close()
    sqlite3.connect(str(db_paths["mkt"])).close()
    sqlite3.connect(str(db_paths["usr"])).close()

    _migrate_split_db()

    conn = sqlite3.connect(str(db_paths["ref"]))
    row = conn.execute("SELECT zh_name FROM item WHERE type_id = 34").fetchone()
    conn.close()
    assert row == ("三钛合金",), "半迁移后重跑应补齐数据（INSERT OR IGNORE 幂等）"

    conn = sqlite3.connect(str(db_paths["usr"]))
    marker = conn.execute("SELECT 1 FROM _split_migration_complete WHERE id = 1").fetchone()
    conn.close()
    assert marker, "重跑后应写入完成标记"


# ── _migrate_blueprint_db ──


def test_blueprint_migration_atomic(tmp_path, monkeypatch):
    """蓝图迁移写入 .tmp 后原子替换为 blueprint.db"""
    ref_db = tmp_path / "reference.db"
    bp_db = tmp_path / "blueprint.db"

    ref = sqlite3.connect(str(ref_db))
    ref.executescript(
        """
        CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER);
        CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_skills (blueprint_type_id INTEGER, activity TEXT, skill_type_id INTEGER, level INTEGER);
        CREATE TABLE item (type_id INTEGER PRIMARY KEY);
        """
    )
    ref.execute("INSERT INTO blueprint_products VALUES (1, 'manufacturing', 34, 1)")
    ref.commit()
    ref.close()

    import Main as main_mod

    monkeypatch.setattr(main_mod, "REF_DB_PATH", str(ref_db))
    monkeypatch.setattr(main_mod, "BP_DB_PATH", str(bp_db))

    _migrate_blueprint_db()

    assert bp_db.exists(), "blueprint.db 应已创建"
    assert not (tmp_path / "blueprint.db.tmp").exists(), ".tmp 残留应被 os.replace 清理"

    conn = sqlite3.connect(str(bp_db))
    row = conn.execute("SELECT product_type_id FROM blueprint_products").fetchone()
    conn.close()
    assert row == (34,)

    # reference.db 的蓝图表已删除
    ref = sqlite3.connect(str(ref_db))
    names = {r[0] for r in ref.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ref.close()
    assert "blueprint_products" not in names


def test_blueprint_migration_tmp_residue_recovers(tmp_path, monkeypatch):
    """半途崩溃（.tmp 残留 + 源表仍在）→ 下次启动删除 tmp 重新迁移成功"""
    ref_db = tmp_path / "reference.db"
    bp_db = tmp_path / "blueprint.db"
    tmp_db = tmp_path / "blueprint.db.tmp"

    ref = sqlite3.connect(str(ref_db))
    ref.executescript(
        """
        CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER);
        CREATE TABLE item (type_id INTEGER PRIMARY KEY);
        """
    )
    ref.execute("INSERT INTO blueprint_products VALUES (1, 'manufacturing', 34, 1)")
    ref.commit()
    ref.close()

    # 模拟上次崩溃：tmp 已建（部分数据），正式文件不存在，源表还在
    t = sqlite3.connect(str(tmp_db))
    t.execute(
        "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER)"
    )
    t.commit()
    t.close()

    import Main as main_mod

    monkeypatch.setattr(main_mod, "REF_DB_PATH", str(ref_db))
    monkeypatch.setattr(main_mod, "BP_DB_PATH", str(bp_db))

    _migrate_blueprint_db()

    assert bp_db.exists(), "残留 .tmp 应被清除并重新迁移"
    conn = sqlite3.connect(str(bp_db))
    row = conn.execute("SELECT product_type_id FROM blueprint_products").fetchone()
    conn.close()
    assert row == (34,)

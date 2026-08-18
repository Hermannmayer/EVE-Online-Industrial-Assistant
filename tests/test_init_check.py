"""初始化检测测试 — 使用临时 SQLite 数据库"""

import os
import shutil
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from services.init_check import (
    ITEMS_NAMED_READY,
    check_all,
    check_blueprints,
    check_icons,
    check_implants,
    check_items,
    check_prices,
    missing_count,
)

# ═══════════════════════════════════════════
#  Fixture: 临时数据库
# ═══════════════════════════════════════════


@pytest.fixture
def db_paths():
    """创建临时数据库目录，返回 { "ref": str, "mkt": str, "bp": str }"""
    tmp = tempfile.mkdtemp(prefix="init_check_")
    paths = {
        "ref": os.path.join(tmp, "reference.db"),
        "mkt": os.path.join(tmp, "market.db"),
        "bp": os.path.join(tmp, "blueprint.db"),
    }
    yield paths
    shutil.rmtree(tmp, ignore_errors=True)


def _patch_init_check(paths):
    """返回一个 patcher 上下文，覆盖 services.init_check 中引用的路径常量"""
    return patch.multiple(
        "services.init_check",
        REF_DB_PATH=paths["ref"],
        MKT_DB_PATH=paths["mkt"],
        BP_DB_PATH=paths["bp"],
    )


@pytest.fixture
def full_dbs(db_paths):
    """创建含完整数据的数据库"""
    # reference.db — item 表 ITEMS_NAMED_READY 行 + item_dogma + 扩展表
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT, market_group_id INTEGER)")
    for i in range(1, ITEMS_NAMED_READY + 1):
        # 前 200 行设 market_group_id（check_icons 计数用）
        mkt_grp = i if i <= 500 else None
        conn.execute(
            "INSERT INTO item (type_id, en_name, zh_name, market_group_id) VALUES (?, ?, ?, ?)",
            (i, f"item_{i}", f"物品{i}", mkt_grp),
        )
    conn.execute("CREATE TABLE item_dogma (type_id INTEGER, attribute_id INTEGER)")
    for i in range(1, 301):
        conn.execute("INSERT INTO item_dogma VALUES (?, 1)", (i,))
    conn.execute("CREATE TABLE market_tree (market_group_id INTEGER PRIMARY KEY, parent_group_id INTEGER)")
    for i in range(1, 502):
        conn.execute("INSERT INTO market_tree VALUES (?, ?)", (i, None))
    conn.execute("CREATE TABLE industry_system_costs (solar_system_id INTEGER PRIMARY KEY, cost REAL)")
    for i in range(1, 102):
        conn.execute("INSERT INTO industry_system_costs VALUES (?, 1.0)", (i,))
    conn.execute("CREATE TABLE meta_group (meta_group_id INTEGER PRIMARY KEY, en_name TEXT)")
    conn.execute("INSERT INTO meta_group VALUES (1, 'Tech I')")
    conn.execute("CREATE TABLE reprocessing_materials (type_id INTEGER, material_type_id INTEGER)")
    conn.execute("INSERT INTO reprocessing_materials VALUES (1, 1)")
    conn.execute("CREATE TABLE dogma_attribute (attribute_id INTEGER PRIMARY KEY, en_name TEXT)")
    conn.execute("INSERT INTO dogma_attribute VALUES (1, 'test')")
    conn.execute("CREATE TABLE station (station_id INTEGER PRIMARY KEY, station_name TEXT)")
    conn.execute("INSERT INTO station VALUES (1, 'test')")
    conn.execute(
        "CREATE TABLE solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT, security REAL)"
    )
    conn.execute("INSERT INTO solar_system VALUES (1, 'Jita', 0.9)")
    conn.execute("CREATE TABLE structure_rigs (type_id INTEGER PRIMARY KEY, mat_bonus REAL, time_bonus REAL)")
    for i in range(100):
        conn.execute("INSERT INTO structure_rigs VALUES (?, 0, 0)", (i,))
    conn.commit()
    conn.close()

    # market.db
    conn = sqlite3.connect(db_paths["mkt"])
    conn.execute("CREATE TABLE market_prices (type_id INTEGER, region_id INTEGER, buy_price REAL)")
    conn.execute("INSERT INTO market_prices VALUES (1, 10000002, 1.0)")
    conn.commit()
    conn.close()

    # blueprint.db — 需要 1000+ 行 blueprint_activities
    conn = sqlite3.connect(db_paths["bp"])
    conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER)")
    for i in range(1002):
        conn.execute("INSERT INTO blueprint_activities VALUES (?, 'manufacturing', 3600)", (4000 + i,))
    conn.commit()
    conn.close()
    return db_paths


# ═══════════════════════════════════════════
#  Tests: 各 check_* 函数
# ═══════════════════════════════════════════


def test_check_items_full(full_dbs):
    """check_items 返回 >=ITEMS_NAMED_READY 表示就绪"""
    with _patch_init_check(full_dbs):
        assert check_items() >= ITEMS_NAMED_READY


def test_check_items_empty(db_paths):
    """空的 item 表返回 <ITEMS_NAMED_READY"""
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    for key in ("mkt", "bp"):
        sqlite3.connect(db_paths[key]).close()
    with _patch_init_check(db_paths):
        assert check_items() < ITEMS_NAMED_READY


def test_check_prices_has_data(full_dbs):
    """check_prices 返回 >0"""
    with _patch_init_check(full_dbs):
        assert check_prices() > 0


def test_check_prices_no_table(db_paths):
    """无 market_prices 表返回 0"""
    sqlite3.connect(db_paths["ref"]).close()
    sqlite3.connect(db_paths["mkt"]).close()
    sqlite3.connect(db_paths["bp"]).close()
    with _patch_init_check(db_paths):
        assert check_prices() == 0


def test_check_blueprints_ready(full_dbs):
    """check_blueprints 返回 >=1000 表示就绪"""
    with _patch_init_check(full_dbs):
        assert check_blueprints() >= 1000


def test_check_blueprints_no_table(db_paths):
    """蓝图表不存在返回 0"""
    sqlite3.connect(db_paths["ref"]).close()
    sqlite3.connect(db_paths["mkt"]).close()
    conn = sqlite3.connect(db_paths["bp"])
    conn.execute("CREATE TABLE other (id INTEGER)")
    conn.commit()
    conn.close()
    with _patch_init_check(db_paths):
        assert check_blueprints() == 0


def test_check_implants_has_data(full_dbs):
    """check_implants 返回 >0"""
    with _patch_init_check(full_dbs):
        assert check_implants() > 0


def test_check_implants_no_table(db_paths):
    """无 item_dogma 表返回 0"""
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    sqlite3.connect(db_paths["mkt"]).close()
    sqlite3.connect(db_paths["bp"]).close()
    with _patch_init_check(db_paths):
        assert check_implants() == 0


# ═══════════════════════════════════════════
#  Tests: check_icons
# ═══════════════════════════════════════════


def test_check_icons_cache_missing(full_dbs):
    """图标缓存目录不存在时 cached=0，但 total 反映 item 表（避免误判已就绪）"""
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir", return_value="/nonexistent/icons"),
    ):
        cached, total = check_icons()
        assert cached == 0
        assert total == 500  # full_dbs 有 500 行 market_group_id


# ═══════════════════════════════════════════
#  Tests: check_all / missing_count
# ═══════════════════════════════════════════


def test_check_all_full(full_dbs, tmp_path):
    """所有组件就绪时 check_all 全 True"""
    icons_dir = tmp_path / "icons_all"
    icons_dir.mkdir()
    for i in range(80):
        (icons_dir / f"{i}.png").touch()
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir", return_value=str(icons_dir)),
    ):
        status = check_all()
        assert status["items"] is True
        assert status["price_baseline"] is True
        assert status["blueprints"] is True
        assert status["implants"] is True
        assert status["sde_core"] is True, "universe/materials/dogma/stations 都就绪 → sde_core 应 True"
        assert status["sde_data"] is True, "region 有行 + 其它扩展表就绪 → sde_data 应 True"


def test_sde_data_false_when_solar_system_empty(db_paths):
    """solar_system 表 0 行 → sde_core False（即使其它扩展表有数据）

    修复目标：已有库永不触发 universe 写入 → solar_system 0 行 → sde_core 必须判 False，
    从而触发 sde_core 步骤重跑 universe。
    """
    conn = sqlite3.connect(db_paths["ref"])
    for table, ddl in [
        ("meta_group", "meta_group_id INTEGER PRIMARY KEY, en_name TEXT"),
        ("reprocessing_materials", "type_id INTEGER, material_type_id INTEGER"),
        ("dogma_attribute", "attribute_id INTEGER PRIMARY KEY"),
        ("station", "station_id INTEGER PRIMARY KEY"),
    ]:
        conn.execute(f"CREATE TABLE {table} ({ddl})")
    conn.execute("INSERT INTO meta_group VALUES (1, 'Tech I')")
    conn.execute("INSERT INTO reprocessing_materials VALUES (1, 1)")
    conn.execute("INSERT INTO dogma_attribute VALUES (1)")
    conn.execute("INSERT INTO station VALUES (1)")
    conn.execute(
        "CREATE TABLE solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT, security REAL)"
    )  # 0 行
    conn.commit()
    conn.close()
    sqlite3.connect(db_paths["mkt"]).close()
    sqlite3.connect(db_paths["bp"]).close()
    with _patch_init_check(db_paths):
        status = check_all()
        assert status["sde_core"] is False


def test_sde_data_true_when_solar_system_has_rows(full_dbs):
    """solar_system 有行 → sde_core True；meta_group + 蓝图名全 → sde_data True（full_dbs 已含）"""
    with _patch_init_check(full_dbs):
        status = check_all()
        assert status["sde_core"] is True
        assert status["sde_data"] is True


def test_missing_count_zero(full_dbs, tmp_path):
    """全就绪时 missing_count 为 0"""
    icons_dir = tmp_path / "icons_zero"
    icons_dir.mkdir()
    for i in range(401):
        (icons_dir / f"{i}.png").touch()
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir", return_value=str(icons_dir)),
        patch("services.init_check.check_schema", return_value=True),
    ):
        assert missing_count() == 0


def test_missing_db_file_returns_zero():
    """数据库文件不存在时函数返回 0"""
    with _patch_init_check({"ref": "/nope/ref.db", "mkt": "/nope/mkt.db", "bp": "/nope/bp.db"}):
        assert check_items() == 0
        assert check_prices() == 0
        assert check_blueprints() == 0
        assert check_implants() == 0


def test_missing_count_partial(db_paths):
    """部分就绪时 missing_count 反映未就绪组件数"""
    # 只有 ref 有 item 数据
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY)")
    for i in range(1, 10001):
        conn.execute("INSERT INTO item (type_id) VALUES (?)", (i,))
    conn.commit()
    conn.close()
    for key in ("mkt", "bp"):
        sqlite3.connect(db_paths[key]).close()
    with (
        _patch_init_check(db_paths),
        patch("core.paths.icon_cache_dir", return_value="/nonexistent_icons"),
        patch("services.init_check.check_schema", return_value=True),
    ):
        cnt = missing_count()
        # items=False, price_baseline=False, blueprints=False, implants=False,
        # industry=False, sde_core=False, sde_data=False, rigs=False, icons=False（共 9 项，schema=True）
        assert cnt == 9

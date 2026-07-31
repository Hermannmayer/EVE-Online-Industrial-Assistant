"""初始化检测测试 — 使用临时 SQLite 数据库"""

import os
import shutil
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from services.init_check import (
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
    # reference.db — item 表 10000 行 + item_dogma + 扩展表
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT, market_group_id INTEGER)")
    for i in range(1, 10001):
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
    conn.execute("CREATE TABLE region (region_id INTEGER PRIMARY KEY, en_name TEXT)")
    conn.execute("INSERT INTO region VALUES (1, 'test')")
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
    """check_items 返回 >=10000 表示就绪"""
    with _patch_init_check(full_dbs):
        assert check_items() >= 10000


def test_check_items_empty(db_paths):
    """空的 item 表返回 <10000"""
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    for key in ("mkt", "bp"):
        sqlite3.connect(db_paths[key]).close()
    with _patch_init_check(db_paths):
        assert check_items() < 10000


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
    """图标缓存目录不存在时返回 (0, 0)"""
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir", return_value="/nonexistent/icons"),
    ):
        cached, total = check_icons()
        assert cached == 0
        # total 至少为 1（max(total, 1) 保护）
        assert total == 0  # 缓存目录不存在时返回 (0, 0)


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
        assert status["prices"] is True
        assert status["blueprints"] is True
        assert status["implants"] is True


def test_missing_count_zero(full_dbs, tmp_path):
    """全就绪时 missing_count 为 0"""
    icons_dir = tmp_path / "icons_zero"
    icons_dir.mkdir()
    for i in range(401):
        (icons_dir / f"{i}.png").touch()
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir", return_value=str(icons_dir)),
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
    ):
        cnt = missing_count()
        # items=False, prices=False, blueprints=False, implants=False,
        # industry=False, sde_data=False, icons=True (0>=0)
        assert cnt == 6

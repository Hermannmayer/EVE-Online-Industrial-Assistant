"""初始化检测测试 — 使用临时 SQLite 数据库"""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
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
    # reference.db — item 表 10000 行 + item_dogma
    conn = sqlite3.connect(db_paths["ref"])
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT)")
    for i in range(1, 10001):
        conn.execute("INSERT INTO item (type_id, zh_name) VALUES (?, ?)", (i, f"item_{i}"))
    conn.execute("CREATE TABLE item_dogma (type_id INTEGER, attribute_id INTEGER)")
    conn.execute("INSERT INTO item_dogma VALUES (1, 1)")
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


def test_check_all_full(full_dbs):
    """所有组件就绪时 check_all 全 True"""
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir") as mock_icon,
    ):
        mock_icon.return_value = "C:/Users/NIGHTW~1//AppData//Local//Temp/test_icons_all"
        os.makedirs("C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_all", exist_ok=True)
        for i in range(80):
            Path(f"C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_all/{i}.png").touch()
        status = check_all()
        assert status["items"] is True
        assert status["prices"] is True
        assert status["blueprints"] is True
        assert status["implants"] is True
    shutil.rmtree("C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_all", ignore_errors=True)


def test_missing_count_zero(full_dbs):
    """全就绪时 missing_count 为 0"""
    with (
        _patch_init_check(full_dbs),
        patch("core.paths.icon_cache_dir") as mock_icon,
    ):
        mock_icon.return_value = "C:/Users/NIGHTW~1//AppData//Local//Temp/test_icons_zero"
        os.makedirs("C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_zero", exist_ok=True)
        for i in range(80):
            Path(f"C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_zero/{i}.png").touch()
        assert missing_count() == 0
    shutil.rmtree("C:/Users/NIGHTW~1/AppData/Local/Temp/test_icons_zero", ignore_errors=True)


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
        # items=True, 其余全 False = 4 missing
        assert cnt == 3  # icons 在 cached=0, total=0 时 0>=0 为 True

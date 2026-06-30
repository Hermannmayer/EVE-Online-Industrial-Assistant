"""pytest 共享配置与 fixtures"""

import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

# ════════════════════════════════════════════════════════════════
#  辅助：创建标准临时数据库套件
# ════════════════════════════════════════════════════════════════


def _create_temp_databases(tmpdir: str):
    """在 tmpdir 中创建 ref/mkt/bp/user 四个数据库，返回 {alias: path} 字典"""
    ref_path = Path(tmpdir) / "reference.db"
    mkt_path = Path(tmpdir) / "market.db"
    bp_path = Path(tmpdir) / "blueprint.db"
    user_path = Path(tmpdir) / "user.db"

    # ── reference.db ──
    conn = sqlite3.connect(str(ref_path))
    conn.executescript("""
        CREATE TABLE item (
            type_id INTEGER PRIMARY KEY,
            zh_name TEXT,
            en_name TEXT,
            volume REAL DEFAULT 1.0
        );
        CREATE TABLE industry_system_costs (
            solar_system_id INTEGER,
            activity TEXT,
            cost_index REAL
        );
        INSERT INTO item VALUES (1001, '三钛合金', 'Tritanium', 0.01);
        INSERT INTO item VALUES (1002, '类银超金属', 'Pyerite', 0.01);
        INSERT INTO item VALUES (2001, '渡鸦级', 'Raven', 50000);
        INSERT INTO item VALUES (2002, '无人机', 'Drone', 5);
    """)
    conn.commit()
    conn.close()

    # ── market.db ──
    conn = sqlite3.connect(str(mkt_path))
    conn.executescript("""
        CREATE TABLE market_prices (
            type_id INTEGER,
            region_id INTEGER,
            buy_price REAL,
            sell_price REAL,
            buy_volume INTEGER DEFAULT 0,
            sell_volume INTEGER DEFAULT 0,
            fetch_time TEXT
        );
        -- 材料价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (1001, 10000002, 4.0, 5.0, 10000000, 8000000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (1002, 10000002, 8.0, 9.0, 5000000, 4000000, '2026-01-01 00:00:00');
        -- 成品价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (2001, 10000002, 50000000, 55000000, 1000000, 800000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (2002, 10000002, 100000, 120000, 500000, 400000, '2026-01-01 00:00:00');
    """)
    conn.commit()
    conn.close()

    # ── blueprint.db ──
    conn = sqlite3.connect(str(bp_path))
    conn.executescript("""
        CREATE TABLE blueprint_activities (
            blueprint_type_id INTEGER,
            activity TEXT,
            time INTEGER
        );
        CREATE TABLE blueprint_products (
            blueprint_type_id INTEGER,
            activity TEXT,
            product_type_id INTEGER,
            quantity INTEGER
        );
        CREATE TABLE blueprint_materials (
            blueprint_type_id INTEGER,
            activity TEXT,
            material_type_id INTEGER,
            quantity INTEGER
        );
        -- 渡鸦级蓝图: 需要 1000 Trit + 500 Pyer, 产出 1 个, 时间 3600s
        INSERT INTO blueprint_activities VALUES (3001, 'manufacturing', 3600);
        INSERT INTO blueprint_products VALUES (3001, 'manufacturing', 2001, 1);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1001, 1000);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1002, 500);
        -- 无人机蓝图: 需要 100 Trit, 产出 1 个, 时间 600s
        INSERT INTO blueprint_activities VALUES (3002, 'manufacturing', 600);
        INSERT INTO blueprint_products VALUES (3002, 'manufacturing', 2002, 1);
        INSERT INTO blueprint_materials VALUES (3002, 'manufacturing', 1001, 100);
    """)
    conn.commit()
    conn.close()

    # ── user.db ──
    conn = sqlite3.connect(str(user_path))
    conn.close()

    return {
        "ref": str(ref_path),
        "mkt": str(mkt_path),
        "bp": str(bp_path),
        "user": str(user_path),
    }


# ════════════════════════════════════════════════════════════════
#  Mock helpers
# ════════════════════════════════════════════════════════════════


def _mock_db_manager():
    """返回一个用于替换 database_manager.get_db 的 mock DatabaseManager"""
    manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    conn.cursor.return_value = cursor
    conn.executescript = MagicMock()
    conn.execute.return_value = cursor

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    manager.connect.return_value = cm
    manager.direct_connect.return_value = conn
    return manager


# ════════════════════════════════════════════════════════════════
#  Fixtures — Session / Qt
# ════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def qapp():
    """提供全局 QApplication 实例，供 PySide6 UI 测试使用"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ════════════════════════════════════════════════════════════════
#  Fixtures — Mock Database
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_db():
    """在 with 块内将 DB 相关依赖替换为 mock"""
    mock_mgr = _mock_db_manager()

    # 清除 scoring 模块级单例的连接缓存，防止旧连接指向已清理的 tempdir
    from services.scoring import db as scoring_db
    scoring_db._local.connections.clear() if hasattr(scoring_db._local, "connections") else None

    with (
        patch("services.database_manager.get_db", return_value=mock_mgr),
        patch("core.container.get_container") as mock_cont,
    ):
        cont = mock_cont.return_value
        cont.db = mock_mgr
        yield


# ════════════════════════════════════════════════════════════════
#  Fixtures — 真实临时数据库
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库（含标准测试数据），返回 DatabaseManager 实例。

    数据包含:
      - item 表: 三钛合金(1001), 类银超金属(1002), 渡鸦级(2001), 无人机(2002)
      - market_prices: Jita 区域买卖价格
      - blueprint: 渡鸦级蓝图(3001) + 无人机蓝图(3002)
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager

    tmpdir = tempfile.mkdtemp(prefix="eve_test_")
    db_paths = _create_temp_databases(tmpdir)

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db

    # 恢复 & 清理
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def db_manager():
    """创建一个使用临时数据库的 DatabaseManager，与 temp_db 功能相同。

    区别：此 fixture 不预填充测试数据，适用于需要纯净数据库的测试。
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager

    tmpdir = tempfile.mkdtemp(prefix="eve_dbmgr_")
    ref_path = Path(tmpdir) / "reference.db"
    mkt_path = Path(tmpdir) / "market.db"
    bp_path = Path(tmpdir) / "blueprint.db"
    user_path = Path(tmpdir) / "user.db"

    # 创建空数据库（仅建表，不插入数据）
    for p in (ref_path, mkt_path, bp_path, user_path):
        conn = sqlite3.connect(str(p))
        conn.close()

    db_paths = {"ref": str(ref_path), "mkt": str(mkt_path), "bp": str(bp_path), "user": str(user_path)}

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_char_config():
    """返回一个标准的角色配置 dict，含满级技能和 Jita 声望"""
    return {
        "skills": {
            "工业理论": 5,
            "高级工业理论": 5,
            "经纪人关系学": 5,
            "高级经纪人关系学": 5,
            "会计学": 5,
        },
        "market": {
            "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
        },
    }


@pytest.fixture
def sample_market_prices(temp_db):
    """插入示例市场价格数据并返回 type_id。

    使用 temp_db fixture（含完整测试数据库），直接返回无人机 type_id=2002。
    """
    return 2002

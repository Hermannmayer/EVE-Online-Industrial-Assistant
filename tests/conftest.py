"""pytest 共享配置与 fixtures"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication


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


@pytest.fixture(scope="session")
def qapp():
    """提供全局 QApplication 实例，供 PySide6 UI 测试使用"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_db():
    """在 with 块内将 services.database_manager.get_db 替换为 mock"""
    with patch("services.database_manager.get_db", return_value=_mock_db_manager()):
        yield


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库用于评分服务集成测试"""
    import sqlite3

    tmpdir = tempfile.mkdtemp(prefix="eve_test_")
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
        -- 材料价格 (Jita)
        INSERT INTO market_prices VALUES (1001, 10000002, 4.0, 5.0, 10000000, 8000000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (1002, 10000002, 8.0, 9.0, 5000000, 4000000, '2026-01-01 00:00:00');
        -- 成品价格 (Jita)
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

    # Patch 路径
    from services.database_manager import DB_PATH_MAP, DatabaseManager

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(
        {
            "ref": str(ref_path),
            "mkt": str(mkt_path),
            "user": str(user_path),
            "bp": str(bp_path),
        }
    )

    # 创建新的 DatabaseManager 实例（绕过全局单例）
    db = DatabaseManager()

    yield db

    # 恢复
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)

    # 清理临时文件
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)

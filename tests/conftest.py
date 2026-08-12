"""pytest 共享配置与 fixtures"""

import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication


def pytest_addoption(parser):
    parser.addoption(
        "--quick",
        action="store_true",
        default=False,
        help="快速模式：跳过 @pytest.mark.slow 的测试（Qt 界面测试）",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--quick"):
        skip_slow = pytest.mark.skip(reason="已跳过慢速测试（--quick 模式）")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


@pytest.fixture(autouse=True)
def reset_db_locks_each_test():
    """每次测试后重置 per-DB 写锁。

    services.db_locks 的 asyncio.Lock 是模块级持久，会绑定首次使用的事件循环；
    pytest-asyncio 每个测试独立循环，跨测试复用同一把锁会抛
    "bound to a different event loop"，故每个测试结束清空。
    """
    yield
    from services.db_locks import reset_db_locks

    reset_db_locks()


@pytest.fixture(autouse=True)
def no_auto_price_download():
    """阻止测试中 MainWindow 构造触发真实价格检查/下载。

    MainWindow.__init__ 会调用 _init_price_check → PriceCheckWorker → 本地
    market_prices 过期时启动 PriceUpdateWorker 真实下载 ESI。测试不应发起
    真实网络请求：后台下载线程会存活到后续测试，与 Qt 清理冲突导致
    Segmentation fault（access violation）。全局静默该检查。
    """
    from ui_pyside6.main_window import MainWindow

    with patch.object(MainWindow, "_init_price_check", lambda self: None):
        yield


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
    conn.execute("PRAGMA user_version = 1")
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
            adjusted_price REAL DEFAULT 0.0,
            buy_volume INTEGER DEFAULT 0,
            sell_volume INTEGER DEFAULT 0,
            fetch_time TEXT
        );
        -- 材料价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (1001, 10000002, 4.0, 5.0, 0.0, 10000000, 8000000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (1002, 10000002, 8.0, 9.0, 0.0, 5000000, 4000000, '2026-01-01 00:00:00');
        -- 成品价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (2001, 10000002, 50000000, 55000000, 50000000, 1000000, 800000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (2002, 10000002, 100000, 120000, 110000, 500000, 400000, '2026-01-01 00:00:00');
    """)
    conn.execute("PRAGMA user_version = 2")
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
            quantity INTEGER,
            wastefactor INTEGER DEFAULT 10
        );
        -- 渡鸦级蓝图: 需要 1000 Trit + 500 Pyer, 产出 1 个, 时间 3600s
        INSERT INTO blueprint_activities VALUES (3001, 'manufacturing', 3600);
        INSERT INTO blueprint_activities VALUES (3002, 'manufacturing', 600);
        INSERT INTO blueprint_products VALUES (3001, 'manufacturing', 2001, 1);
        INSERT INTO blueprint_products VALUES (3002, 'manufacturing', 2002, 1);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1001, 1000, 10);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1002, 500, 10);
        INSERT INTO blueprint_materials VALUES (3002, 'manufacturing', 1001, 100, 10);
    """)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    # ── user.db ──
    conn = sqlite3.connect(str(user_path))
    conn.execute("PRAGMA user_version = 10")
    conn.commit()
    conn.close()

    return {
        "ref": str(ref_path),
        "mkt": str(mkt_path),
        "bp": str(bp_path),
        "user": str(user_path),
    }


def _create_user_v4(db_path):
    """构造 v4 的 user.db（模拟 ALTER 迁移缺口库）。

    - hangars：**无** solar_system_id 列（v5 迁移待加）
    - production_plans：**显式不含** facility_cost_mult 列
      （该列现仅存在于 CREATE TABLE 路径，v2→v3 ALTER 迁移遗漏 → v4→v5 需补）
    - 已含 v3→v4 执行列（assigned_blueprint_id / mat_hangar_id / material_short）
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT DEFAULT ''
        );
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
            material_short TEXT DEFAULT ''
        );
        """
    )
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()


def _create_user_v5(db_path):
    """构造 v5 的 user.db（hangars 含 solar_system_id、production_plans 含 v5 全列，无 v6 设施列）"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL
        );
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
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()


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


@pytest.fixture(scope="session")
def app(qapp):
    """qapp 的别名，与默认 fixture 命名保持一致"""
    yield qapp


# ════════════════════════════════════════════════════════════════
#  Fixtures — Mock Database
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_db():
    """在 with 块内将 DB 相关依赖替换为 mock"""
    mock_mgr = _mock_db_manager()

    # 清除数据库管理器的线程局部连接缓存，防止旧连接指向已清理的 tempdir
    from services.database_manager import get_db as _get_db

    _scoring_db = _get_db()
    _scoring_db._local.connections.clear() if hasattr(_scoring_db._local, "connections") else None

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
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db

    tmpdir = tempfile.mkdtemp(prefix="eve_test_")
    db_paths = _create_temp_databases(tmpdir)

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db

    # 恢复 & 清理
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    get_db().close_all()  # 清共享单例缓存的临时库连接，防泄漏污染后续测试
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def db_manager():
    """创建一个使用临时数据库的 DatabaseManager，与 temp_db 功能相同。

    区别：此 fixture 不预填充测试数据，适用于需要纯净数据库的测试。
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db

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
    get_db().close_all()  # 清共享单例缓存的临时库连接，防泄漏污染后续测试
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


# ════════════════════════════════════════════════════════════════
#  Fixtures — UI Pages
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def main_window(app, mock_db):
    """创建 MainWindow 实例用于 UI 测试。

    依赖 mock_db 避免真实数据库连接，测试完成后自动关闭窗口。
    """
    from ui_pyside6.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


@pytest.fixture
def industry_page(main_window):
    """创建 IndustryPage 实例用于 UI 测试。"""
    from ui_pyside6.views.industry_view import IndustryPage

    page = IndustryPage(main_window)
    yield page
    page.deleteLater()


@pytest.fixture
def inventory_page(main_window):
    """创建 InventoryPage 实例用于 UI 测试。

    额外 patch services.inventory_manager._default_db 以确保 init_db() 使用 mock 数据库。
    BlueprintTab 通过模块级 get_container 访问 ref/mkt 库（market_tree 等），
    CI 无真实 database/ 目录，必须一并 patch。
    """
    from unittest.mock import MagicMock, patch

    from ui_pyside6.views.inventory_view import InventoryPage

    mock_mgr = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (0,)
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.executescript = MagicMock()
    mock_conn.execute.return_value = mock_cursor

    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_conn)
    mock_cm.__exit__ = MagicMock(return_value=False)
    mock_mgr.connect.return_value = mock_cm

    with (
        patch("services.inventory_manager._default_db", return_value=mock_mgr),
        patch("ui_pyside6.views.inventory.blueprint_tab.get_container") as mock_cont,
    ):
        mock_cont.return_value.db = mock_mgr
        page = InventoryPage(main_window)
    yield page
    page.deleteLater()


@pytest.fixture
def query_page(main_window):
    """创建 QueryPage 实例用于 UI 测试。"""
    from ui_pyside6.views.query_view import QueryPage

    page = QueryPage(main_window)
    yield page
    page.deleteLater()

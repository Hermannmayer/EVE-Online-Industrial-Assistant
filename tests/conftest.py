"""pytest 共享配置与 fixtures"""

import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

# 测试分档由 marker 驱动（见 scripts/run_tests.sh）：
#   fast  = 纯计算/轻服务白名单
#   ui    = Qt 界面 + 真 QThread
# validate = -m "not ui"，ui-retest = -m "ui"，二者互斥覆盖全部用例。


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


def _refuse_network(*args, **kwargs):
    """应用**自动**发起的下载路径：测试里一律空转。"""
    return None


@pytest.fixture(autouse=True)
def no_auto_price_download(monkeypatch):
    """阻断应用**自动发起**的网络：价格检查/下载、SDE/ESI 初始化。

    原先这里 patch 的是 `MainWindow._init_price_check` —— Widgets 外壳的一个私有方法。
    外壳换成 QML（批次 6.1）之后那个 patch 点**直接消失**，而它在 autouse fixture 里，
    等于每个测试的 setup 都炸。教训：**别把全局安全网挂在某一层外壳的私有方法上**。

    现在挂在**会自己发请求的那几个入口**上（两条价格 worker + 价格更新服务），
    与外壳无关、与页面无关：谁在什么时候起线程都拦得住。

    **不**在 `aiohttp.ClientSession` 这一层封：那样会把 `test_client.py` /
    `test_price_history.py` 这些「用 mock 会话测客户端本身」的用例一起打挂
    —— 它们要的正是真实的 ClientSession 语义。
    """
    from services.importers import getprices
    from ui_qml.workers import main_window_workers

    monkeypatch.setattr(main_window_workers.PriceCheckWorker, "run", _refuse_network)
    monkeypatch.setattr(main_window_workers.PriceUpdateWorker, "run", _refuse_network)
    monkeypatch.setattr(getprices, "run_price_update", _refuse_network)
    yield


@pytest.fixture(autouse=True)
def _reset_qt_noise_state():
    """复位 `core.qt_noise` 的退出标记。

    它是**进程级全局**：某个用例跑过 `begin_shutdown()`（构造外壳并关窗就会）之后，
    同进程后续用例的 `ShellWindowBridge.notify()` 会静默变成空操作 —— 表现为
    「后面的外壳用例莫名其妙拿不到 QML 更新」，且很难查。每个用例结束复位。
    """
    yield
    from core import qt_noise

    qt_noise._shutting_down = False


@pytest.fixture(autouse=True)
def isolate_user_settings(tmp_path, monkeypatch):
    """把 settings.json 指向临时文件 —— 测试绝不写用户真实数据。

    回归背景：tests/test_ui_main_window.py 用 patch 替换 user_settings.load_settings
    后构造 MainWindow；MainWindow.__init__ → theme.apply_theme → save_theme_preference
    → save_settings（read-modify-write）此时读到的是 patch 的返回值，于是把真实
    data/settings.json 全量覆盖成那个字典（用户的默认机库等设置被擦除）。
    """
    monkeypatch.setattr("services.user_settings.SETTINGS_PATH", str(tmp_path / "settings.json"))
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
    conn.execute("PRAGMA user_version = 16")
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
    # QML 控件样式必须与生产一致（见 Main.py 同名调用）。
    # 不设会用平台默认样式 —— Windows 上是**原生**样式，它禁止自定义
    # background/indicator/contentItem，会为 FTextField/FSpinBox 等自定义组件
    # 刷「The current style does not support customization of this control」告警，
    # 且渲染结果与真实运行不同。必须在加载任何 QML 之前设置。
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("FluentWinUI3")
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

    # plan_service 用 `from core.container import get_container` 绑定旧引用，
    # patch core.container 无法覆盖已导入模块里的名字；须同时 patch 该模块引用，
    # 否则依赖 load_plans 的 UI 测试会穿透到真实库（no such table）。
    with (
        patch("services.database_manager.get_db", return_value=mock_mgr),
        patch("core.container.get_container") as mock_cont,
        patch("services.plan_service.get_container") as mock_plan_cont,
    ):
        cont = mock_cont.return_value
        cont.db = mock_mgr
        mock_plan_cont.return_value = cont
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
def main_window(app, mock_db, monkeypatch):
    """主窗口（**QML 外壳**）—— 批次 6.1 起主窗口就是 `ui_qml.shell_window.ShellWindow`。

    名字仍叫 `main_window`：几十个用例按这个名字取「主窗口」，改名的收益抵不上改动面。
    `_init_price_check` 由全局的 `no_auto_price_download` 掐掉，这里不用再管。
    """
    from ui_qml.shell_window import ShellWindow

    window = ShellWindow()
    yield window
    window.close()


@pytest.fixture
def industry_page(main_window):
    """创建工业页**控制器**（`IndustryPage`）用于 UI 测试。

    批次 7.4 起它是纯 `QObject` 控制器：**不再自建 QML 宿主**（`_host` / `make_qml_host`
    已删），渲染面由外壳决定。需要渲染 `IndustryPage.qml` 的用例得自己造宿主
    （`ui_qml.host.PageHost`，或外壳的 `ui_qml.registry.build_qml_page`）。
    """
    from ui_qml.views.industry_view import IndustryPage

    page = IndustryPage(main_window)
    yield page
    page.deleteLater()


# ════════════════════════════════════════════════════════════════
#  共享蓝图测试数据 — plan_decompose / parent_decompose 等复用
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def seed_bp_blueprints():
    """返回在指定 connection 上建立 bp 蓝图表并注入渡鸦级/组件数据的函数。

    bp3001 → 产物 2001，材料 1001×5 + 35×10；bp3002 → 产物 1001，材料 34×2。
    跨测试文件共享，避免 _build_dbs 逐行复制。
    """

    def _seed(conn):
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,5)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',35,10)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3002,'manufacturing',34,2)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',1800)")

    return _seed

"""
DatabaseManager — 多库连接管理器

封装三个独立数据库的连接管理，支持 ATTACH DATABASE 跨库查询。

用法:
    db = DatabaseManager()
    with db.connect('user', 'ref', 'mkt') as conn:
        cursor = conn.execute("SELECT * FROM ref.item i JOIN mkt.market_prices mp ...")
"""
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal

from core.paths import BP_DB_PATH, MKT_DB_PATH, REF_DB_PATH, USR_DB_PATH

# 数据库标识符
DB_ALIAS = Literal["ref", "mkt", "user", "bp"]
DB_PATH_MAP = {
    "ref": REF_DB_PATH,
    "mkt": MKT_DB_PATH,
    "user": USR_DB_PATH,
    "bp": BP_DB_PATH,
}

# 各库的 WAL 模式初始化 SQL
_DB_INIT_SQL = {
    "ref": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-8000;
    """,
    "mkt": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-8000;
    """,
    "user": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-4000;
        PRAGMA foreign_keys=ON;
    """,
    "bp": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-8000;
    """,
}


class DatabaseManager:
    """线程安全的多数据库连接管理器"""

    def __init__(self):
        self._local = threading.local()

    def _ensure_init(self, db_alias: str):
        """确保目标数据库存在并已初始化"""
        db_path = DB_PATH_MAP.get(db_alias)
        if not db_path:
            raise ValueError(f"Unknown database alias: {db_alias}")

    @contextmanager
    def connect(self, primary: DB_ALIAS, *attach: DB_ALIAS) -> Generator[sqlite3.Connection, None, None]:
        """获取连接，自动 ATTACH 需要的辅助库。

        用法:
            with db.connect('user', 'ref', 'mkt') as conn:
                conn.execute("SELECT * FROM ref.item ...")
                conn.execute("SELECT * FROM mkt.market_prices ...")

        参数:
            primary: 主数据库 ('ref', 'mkt', 'user')
            attach:  需要 ATTACH 的辅助库列表（自动去重）
        """
        db_path = DB_PATH_MAP[primary]
        conn = sqlite3.connect(db_path)
        try:
            # 初始化 WAL 模式（首次连接时设置）
            init_sql = _DB_INIT_SQL.get(primary, "")
            if init_sql:
                conn.executescript(init_sql)

            # ATTACH 辅助库
            attached = set()
            for alias in attach:
                if alias == primary or alias in attached:
                    continue
                attached.add(alias)
                other_path = DB_PATH_MAP[alias]
                # 使用双反斜杠处理 Windows 路径
                safe_path = other_path.replace("\\", "/")
                conn.execute(f"ATTACH DATABASE '{safe_path}' AS {alias}")

            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def connect_ref(self) -> Generator[sqlite3.Connection, None, None]:
        """便捷方法：连接参考数据库"""
        with self.connect("ref") as conn:
            yield conn

    @contextmanager
    def connect_mkt(self) -> Generator[sqlite3.Connection, None, None]:
        """便捷方法：连接市场数据库"""
        with self.connect("mkt") as conn:
            yield conn

    @contextmanager
    def connect_user(self) -> Generator[sqlite3.Connection, None, None]:
        """便捷方法：连接用户数据库"""
        with self.connect("user") as conn:
            yield conn

    def direct_connect(self, db_alias: DB_ALIAS) -> sqlite3.Connection:
        """直接连接（不经过 context manager），用于 Worker/后台线程等简单场景。

        注意：调用方负责 close()
        """
        db_path = DB_PATH_MAP[db_alias]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


# 全局单例
_db_manager = None
_db_lock = threading.Lock()


def get_db() -> DatabaseManager:
    """获取全局 DatabaseManager 单例"""
    global _db_manager
    if _db_manager is None:
        with _db_lock:
            if _db_manager is None:
                _db_manager = DatabaseManager()
    return _db_manager

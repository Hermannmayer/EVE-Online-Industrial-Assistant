"""
DatabaseManager — 多库连接管理器（连接复用版）

封装三个独立数据库的连接管理，支持 ATTACH DATABASE 跨库查询。
同一线程内相同配置的连接自动复用，避免重复打开和 ATTACH 开销。

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
        PRAGMA busy_timeout=30000;
    """,
    "mkt": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-8000;
        PRAGMA busy_timeout=30000;
    """,
    "user": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-4000;
        PRAGMA foreign_keys=ON;
        PRAGMA busy_timeout=30000;
    """,
    "bp": """
        PRAGMA journal_mode=WAL;
        PRAGMA cache_size=-8000;
        PRAGMA busy_timeout=30000;
    """,
}


class DatabaseManager:
    """线程安全的多数据库连接管理器（连接复用版）

    同一线程内，相同 (primary, attach) 配置的连接会自动复用，
    避免重复打开物理连接和执行 ATTACH DATABASE。
    """

    def __init__(self):
        self._local = threading.local()

    # ---- 内部：按线程缓存连接 ----

    def _get_cache(self) -> dict[str, sqlite3.Connection]:
        """获取当前线程的连接缓存字典"""
        if not hasattr(self._local, "connections"):
            self._local.connections = {}
        cache: dict[str, sqlite3.Connection] = self._local.connections
        return cache

    @staticmethod
    def _cache_key(primary: str, attach: tuple[str, ...]) -> str:
        """生成连接配置的唯一缓存 key：primary:sorted_unique_attach"""
        unique_attach = tuple(sorted({a for a in attach if a != primary}))
        return f"{primary}:{','.join(unique_attach)}"

    def _get_or_create(self, primary: DB_ALIAS, attach: tuple[str, ...]) -> sqlite3.Connection:
        """从缓存获取连接，不存在则创建并缓存"""
        cache = self._get_cache()
        # 校验别名有效性
        valid_aliases = set(DB_PATH_MAP.keys())
        if primary not in valid_aliases:
            raise ValueError(f"Unknown database alias: {primary}")
        for alias in attach:
            if alias not in valid_aliases:
                raise ValueError(f"Unknown database alias: {alias}")

        key = self._cache_key(primary, attach)

        if key in cache:
            return cache[key]

        # 创建新连接
        db_path = DB_PATH_MAP[primary]
        conn = sqlite3.connect(db_path)

        # 初始化 PRAGMA（首次连接时设置，后续复用跳过）
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
            safe_path = other_path.replace("\\", "/").replace("'", "''")
            conn.execute(f"ATTACH DATABASE '{safe_path}' AS {alias}")

        conn.row_factory = sqlite3.Row
        cache[key] = conn
        return conn

    # ---- 公开 API ----

    def _ensure_init(self, db_alias: str):
        """确保目标数据库存在并已初始化"""
        db_path = DB_PATH_MAP.get(db_alias)
        if not db_path:
            raise ValueError(f"Unknown database alias: {db_alias}")

    @contextmanager
    def connect(self, primary: DB_ALIAS, *attach: DB_ALIAS) -> Generator[sqlite3.Connection]:
        """获取连接（自动复用），ATTACH 需要的辅助库。

        同一线程内相同配置的连接会自动复用，无需重复 ATTACH。
        连接在 with 块结束时 commit/rollback 但不关闭，留给后续复用。

        用法:
            with db.connect('user', 'ref', 'mkt') as conn:
                conn.execute("SELECT * FROM ref.item ...")
                conn.execute("SELECT * FROM mkt.market_prices ...")

        参数:
            primary: 主数据库 ('ref', 'mkt', 'user', 'bp')
            attach:  需要 ATTACH 的辅助库列表（自动去重）
        """
        conn = self._get_or_create(primary, tuple(attach))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        # 注意：不再 conn.close()，连接留待复用

    @contextmanager
    def connect_ref(self) -> Generator[sqlite3.Connection]:
        """便捷方法：连接参考数据库"""
        with self.connect("ref") as conn:
            yield conn

    @contextmanager
    def connect_mkt(self) -> Generator[sqlite3.Connection]:
        """便捷方法：连接市场数据库"""
        with self.connect("mkt") as conn:
            yield conn

    @contextmanager
    def connect_user(self) -> Generator[sqlite3.Connection]:
        """便捷方法：连接用户数据库"""
        with self.connect("user") as conn:
            yield conn

    def direct_connect(self, db_alias: DB_ALIAS) -> sqlite3.Connection:
        """直接连接（不经过 context manager，不走缓存），用于 Worker/后台线程等简单场景。

        注意：调用方负责 close()，此连接不会被缓存。
        """
        db_path = DB_PATH_MAP[db_alias]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # 与缓存连接保持一致：WAL 下写锁等待 30s（避免并发 DELETE+INSERT 时报 database is locked）
        init_sql = _DB_INIT_SQL.get(db_alias, "")
        if init_sql:
            conn.executescript(init_sql)
        return conn

    def close_all(self):
        """关闭当前线程的所有缓存连接（应用退出时调用）"""
        if hasattr(self._local, "connections"):
            for conn in self._local.connections.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._local.connections.clear()


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

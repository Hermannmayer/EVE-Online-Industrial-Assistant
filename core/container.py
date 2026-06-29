"""
IOC 容器 — 创建并持有所有依赖，由 Main.py 组装，注入 UI/Service 层

用法:
    container = AppContainer()
    scoring_svc = container.scoring_service()
    db = container.db
"""

import threading

from services.database_manager import DatabaseManager, get_db
from services.scoring_cache import ScoringCache


class AppContainer:
    """应用级依赖注入容器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._db: DatabaseManager | None = None
        self._scoring_cache: ScoringCache | None = None
        self._scoring_service = None

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            with self._lock:
                if self._db is None:
                    self._db = get_db()
        return self._db

    @property
    def scoring_cache(self) -> ScoringCache:
        if self._scoring_cache is None:
            with self._lock:
                if self._scoring_cache is None:
                    self._scoring_cache = ScoringCache(max_size=500)
        return self._scoring_cache

    def scoring_service(self):
        """延迟导入 ScoringService 避免循环依赖"""
        if self._scoring_service is None:
            with self._lock:
                if self._scoring_service is None:
                    from services.scoring_service import ScoringService

                    self._scoring_service = ScoringService(self.db, self.scoring_cache)
        return self._scoring_service


# 全局容器单例（过渡期兼容，后续逐步消除）
_container: AppContainer | None = None
_lock = threading.Lock()


def get_container() -> AppContainer:
    global _container
    if _container is None:
        with _lock:
            if _container is None:
                _container = AppContainer()
    return _container


def init_container() -> AppContainer:
    """Main.py 启动时调用，显式初始化容器"""
    global _container
    with _lock:
        _container = AppContainer()
    return _container

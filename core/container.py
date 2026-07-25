"""
IOC 容器 — 创建并持有所有依赖，由 Main.py 组装，注入 UI/Service 层

用法:
    container = AppContainer()
    scoring_svc = container.scoring_service()
    db = container.db
"""

import threading

from services.database_manager import DatabaseManager, get_db
from services.scoring_service import ScoringCache


class AppContainer:
    """应用级依赖注入容器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._db: DatabaseManager | None = None
        self._scoring_cache: ScoringCache | None = None
        self._scoring_service = None
        self._manufacturing_calculator = None
        self._blueprint_reader = None
        self._name_resolver = None

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

    @property
    def manufacturing_calculator(self):
        """制造计算器（纯函数，无状态）"""
        if self._manufacturing_calculator is None:
            with self._lock:
                if self._manufacturing_calculator is None:
                    from services import manufacturing_calculator

                    self._manufacturing_calculator = manufacturing_calculator
        return self._manufacturing_calculator

    @property
    def blueprint_reader(self):
        """蓝图数据访问层"""
        if self._blueprint_reader is None:
            with self._lock:
                if self._blueprint_reader is None:
                    from services import blueprint_reader

                    self._blueprint_reader = blueprint_reader
        return self._blueprint_reader

    @property
    def name_resolver(self):
        """物品名称解析服务"""
        if self._name_resolver is None:
            with self._lock:
                if self._name_resolver is None:
                    from services import name_resolver

                    self._name_resolver = name_resolver
        return self._name_resolver


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

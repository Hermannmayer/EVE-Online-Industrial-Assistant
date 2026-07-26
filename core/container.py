"""
IOC 容器 — 持有所有依赖，由 Main.py 组装
"""

import threading

from core.cache import TtlLRUCache
from services.database_manager import DatabaseManager, get_db


class AppContainer:
    def __init__(self):
        self._lock = threading.RLock()
        self._db: DatabaseManager | None = None

        self._scoring_service = None
        self._scoring_cache: TtlLRUCache | None = None

        self._pricing_service = None
        self._item_repo = None
        self._market_repo = None
        self._blueprint_repo = None
        self._plan_repo = None
        self._bom_expander = None
        self._logistics_service = None
        self._scheduler = None
        self._watchlist = None
        self._inventory_manager = None
        self._price_history_service = None
        self._char_config_resolver = None
        self._manufacturing_calculator = None
        self._refining_service = None

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            with self._lock:
                if self._db is None:
                    self._db = get_db()
        return self._db

    @property
    def scoring_cache(self) -> TtlLRUCache:
        if self._scoring_cache is None:
            with self._lock:
                if self._scoring_cache is None:
                    self._scoring_cache = TtlLRUCache(max_size=500, ttl_seconds=1800)
        return self._scoring_cache

    @property
    def item_repo(self):
        if self._item_repo is None:
            with self._lock:
                if self._item_repo is None:
                    from services.repositories.item_repository import ItemRepository

                    self._item_repo = ItemRepository(self.db)
        return self._item_repo

    @property
    def market_repo(self):
        if self._market_repo is None:
            with self._lock:
                if self._market_repo is None:
                    from services.repositories.market_repository import MarketRepository

                    self._market_repo = MarketRepository(self.db)
        return self._market_repo

    @property
    def blueprint_repo(self):
        if self._blueprint_repo is None:
            with self._lock:
                if self._blueprint_repo is None:
                    from services.repositories.blueprint_repository import BlueprintRepository

                    self._blueprint_repo = BlueprintRepository(self.db)
        return self._blueprint_repo

    @property
    def plan_repo(self):
        if self._plan_repo is None:
            with self._lock:
                if self._plan_repo is None:
                    from services.repositories.plan_repository import PlanRepository

                    self._plan_repo = PlanRepository(self.db)
        return self._plan_repo

    @property
    def pricing_service(self):
        if self._pricing_service is None:
            with self._lock:
                if self._pricing_service is None:
                    from services.pricing_service import PricingService

                    self._pricing_service = PricingService(self.db)
        return self._pricing_service

    @property
    def bom_expander(self):
        if self._bom_expander is None:
            with self._lock:
                if self._bom_expander is None:
                    from services.bom_expander import BomExpander

                    self._bom_expander = BomExpander(self.db, self.pricing_service)
        return self._bom_expander

    @property
    def logistics_service(self):
        if self._logistics_service is None:
            with self._lock:
                if self._logistics_service is None:
                    from services.logistics import LogisticsService

                    self._logistics_service = LogisticsService(self.db, self.pricing_service)
        return self._logistics_service

    @property
    def scheduler(self):
        if self._scheduler is None:
            with self._lock:
                if self._scheduler is None:
                    from services.production_scheduler import ProductionScheduler

                    self._scheduler = ProductionScheduler(self.db)
        return self._scheduler

    @property
    def watchlist_manager(self):
        if self._watchlist is None:
            with self._lock:
                if self._watchlist is None:
                    from services.watchlist_manager import WatchlistManager

                    self._watchlist = WatchlistManager(self.db)
        return self._watchlist

    @property
    def inventory_manager(self):
        if self._inventory_manager is None:
            with self._lock:
                if self._inventory_manager is None:
                    from services.inventory_manager import InventoryManager

                    self._inventory_manager = InventoryManager(self.db)
        return self._inventory_manager

    @property
    def price_history_service(self):
        if self._price_history_service is None:
            with self._lock:
                if self._price_history_service is None:
                    from services.price_history import PriceHistoryService

                    self._price_history_service = PriceHistoryService(self.db)
        return self._price_history_service

    def scoring_service(self):
        if self._scoring_service is None:
            with self._lock:
                if self._scoring_service is None:
                    from services.scoring_service import ScoringService

                    self._scoring_service = ScoringService(self.db, self.scoring_cache)
        return self._scoring_service

    @property
    def manufacturing_calculator(self):
        """制造计算器（纯函数模块，无状态）"""
        if self._manufacturing_calculator is None:
            with self._lock:
                if self._manufacturing_calculator is None:
                    from services import manufacturing_calculator

                    self._manufacturing_calculator = manufacturing_calculator
        return self._manufacturing_calculator

    @property
    def char_config_resolver(self):
        if self._char_config_resolver is None:
            with self._lock:
                if self._char_config_resolver is None:
                    from services.char_config_resolver import CharConfigResolver

                    def _char_data_provider(char_name: str) -> dict | None:
                        try:
                            from ui_pyside6.views.char_settings_view import get_character

                            return get_character(char_name)
                        except Exception:
                            try:
                                from services.char_config_validator import load_char_config
                                from ui_pyside6.views.char_settings_view import char_config_path

                                data = load_char_config(char_config_path())
                                chars = data.get("characters", {})
                                if char_name in chars:
                                    return dict(chars[char_name])
                                current = data.get("current", "main")
                                if current in chars:
                                    return dict(chars[current])
                            except Exception:
                                pass
                            return None

                    self._char_config_resolver = CharConfigResolver(char_data_provider=_char_data_provider)
        return self._char_config_resolver

    @property
    def refining_service(self):
        if self._refining_service is None:
            with self._lock:
                if self._refining_service is None:
                    from services.refining_service import RefiningService

                    self._refining_service = RefiningService(self.db, self.pricing_service)
        return self._refining_service


# 全局容器（仅在 Main.py 中初始化一次）
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
    global _container
    with _lock:
        _container = AppContainer()
    return _container

"""测试核心模块"""

import logging
import os
import sys

from core.paths import app_root


def test_app_root_exists():
    root = app_root()
    assert root is not None
    assert len(root) > 0


def test_database_path():
    from core.paths import database_path

    path = database_path()
    assert path.endswith("items.db")


def test_is_frozen_default_false():
    """缺少 sys.frozen 时 is_frozen() 应返回 False"""
    from core.paths import is_frozen

    frozen = getattr(sys, "frozen", False)
    assert is_frozen() == bool(frozen)


def test_trade_hubs_default_values():
    """TRADE_HUBS 应包含五大贸易中心"""
    from core.constants import TRADE_HUBS

    assert "Jita" in TRADE_HUBS
    assert "Amarr" in TRADE_HUBS
    assert "Dodixie" in TRADE_HUBS
    assert "Rens" in TRADE_HUBS
    assert "Hek" in TRADE_HUBS
    assert len(TRADE_HUBS) == 5


def test_trade_hub_ids_defaults():
    """TRADE_HUB_IDS 应包含正确的 region_id 映射"""
    from core.constants import TRADE_HUB_IDS

    assert TRADE_HUB_IDS["Jita"] == 10000002
    assert TRADE_HUB_IDS["Amarr"] == 10000043
    assert TRADE_HUB_IDS["Dodixie"] == 10000032
    assert TRADE_HUB_IDS["Rens"] == 10000030


def test_app_root_default_contains_core():
    """默认 app_root() 应包含 core 目录"""
    root = app_root()
    assert os.path.isdir(os.path.join(root, "core"))


def test_logger_default_level():
    """日志模块使用默认 INFO 级别"""
    from core.logger import log

    assert log._logger.level == logging.DEBUG  # __init__ 设置 DEBUG
    console_handlers = [h for h in log._logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(console_handlers) > 0
    assert console_handlers[0].level == logging.INFO

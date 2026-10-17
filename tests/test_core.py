"""测试核心模块"""

import logging

import pytest

pytestmark = pytest.mark.fast


def test_logger_default_level():
    """日志模块使用默认 INFO 级别"""
    from core.logger import log

    assert log._logger.level == logging.DEBUG  # __init__ 设置 DEBUG
    console_handlers = [h for h in log._logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(console_handlers) > 0
    assert console_handlers[0].level == logging.INFO

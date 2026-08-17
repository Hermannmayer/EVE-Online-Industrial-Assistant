"""测试日志模块"""

import logging

import pytest

from core.logger import log

pytestmark = pytest.mark.fast


def test_log_info(caplog):
    caplog.set_level(logging.INFO)
    log.info("test message")
    assert "test message" in caplog.text


def test_log_error(caplog):
    caplog.set_level(logging.ERROR)
    log.error("error test")
    assert "error test" in caplog.text

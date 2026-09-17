"""测试核心模块"""

import logging
import sys

import pytest

pytestmark = pytest.mark.fast


def test_logger_default_level():
    """日志模块使用默认 INFO 级别"""
    from core.logger import log

    assert log._logger.level == logging.DEBUG  # __init__ 设置 DEBUG
    console_handlers = [h for h in log._logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(console_handlers) > 0
    assert console_handlers[0].level == logging.INFO


class TestTaskbarIdentity:
    """Windows 任务栏身份（AppUserModelID）。

    失败会被静默吞掉（外观层的事不该影响启动），所以这里断言它在 Windows 上
    **真的成功** —— 失败通常意味着 ctypes 的 argtypes/restype 写错了。
    """

    def test_sets_ok_on_windows(self):
        from core.taskbar import set_app_user_model_id

        assert set_app_user_model_id() is (sys.platform == "win32")

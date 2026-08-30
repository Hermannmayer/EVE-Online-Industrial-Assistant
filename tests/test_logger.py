"""测试日志模块"""

import logging
import os
import time

import pytest

from core.logger import log, prune_logs, set_debug

pytestmark = pytest.mark.fast


def test_log_info(caplog):
    caplog.set_level(logging.INFO)
    log.info("test message")
    assert "test message" in caplog.text


def test_log_error(caplog):
    caplog.set_level(logging.ERROR)
    log.error("error test")
    assert "error test" in caplog.text


def test_log_critical(caplog):
    caplog.set_level(logging.CRITICAL)
    log.critical("critical test")
    assert "critical test" in caplog.text


def test_file_handler_level_is_info(tmp_path, monkeypatch):
    import core.logger as logger_mod

    # 指向 tmp 目录构造独立 logger（唯一名避免触及全局单例 handlers），
    # 避免依赖真实家目录可写性（沙箱/CI 下不可写）。
    monkeypatch.setattr(logger_mod, "log_dir", lambda: tmp_path / "logs")
    lgr = logger_mod._Logger(name="eve-assistant-test-info")
    fhs = [h for h in lgr._logger.handlers if isinstance(h, logging.FileHandler)]
    assert fhs, "应挂载文件 handler"
    assert all(h.level == logging.INFO for h in fhs)

    # 端到端：info 级消息确实落盘
    lgr.info("功能运行信息")
    logfile = next(tmp_path.glob("logs/app_*.log"))
    assert "功能运行信息" in logfile.read_text(encoding="utf-8")


def test_set_debug_hits_file_handler(tmp_path, monkeypatch):
    import core.logger as logger_mod

    # FileHandler 是 StreamHandler 子类，set_debug 的 isinstance 过滤会覆盖它 → 锁降级语义
    monkeypatch.setattr(logger_mod, "log_dir", lambda: tmp_path / "logs")
    lgr = logger_mod._Logger(name="eve-assistant-test-setdebug")
    fh = next(h for h in lgr._logger.handlers if isinstance(h, logging.FileHandler))
    assert isinstance(fh, logging.StreamHandler)

    console = next(
        h
        for h in log._logger.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    )
    set_debug(True)
    try:
        assert console.level == logging.DEBUG
    finally:
        set_debug(False)
        assert console.level == logging.INFO


def test_prune_logs_removes_expired_only(tmp_path):
    now = time.time()
    logs = tmp_path / "logs"
    crashes = tmp_path / "crashes"
    logs.mkdir()
    crashes.mkdir()

    old_log = logs / "app_20200101.log"
    old_log.write_text("old", encoding="utf-8")
    os.utime(old_log, (now - 20 * 86400, now - 20 * 86400))

    fresh_log = logs / "app_20260830.log"
    fresh_log.write_text("fresh", encoding="utf-8")
    os.utime(fresh_log, (now - 1 * 86400, now - 1 * 86400))

    old_crash = crashes / "crash_old.log"
    old_crash.write_text("old", encoding="utf-8")
    os.utime(old_crash, (now - 30 * 86400, now - 30 * 86400))

    keep_crash = crashes / "crash_keep.log"
    keep_crash.write_text("fresh", encoding="utf-8")
    os.utime(keep_crash, (now - 5, now - 5))

    unrelated = logs / "unrelated.txt"
    unrelated.write_text("x", encoding="utf-8")
    os.utime(unrelated, (now - 30 * 86400, now - 30 * 86400))

    removed = prune_logs(logs, crashes)

    assert removed == 2
    assert not old_log.exists()
    assert fresh_log.exists()
    assert not old_crash.exists()
    assert keep_crash.exists()
    # 非日志模式文件不受影响
    assert unrelated.exists()

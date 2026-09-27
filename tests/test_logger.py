"""测试日志模块"""

import logging
import os
import tempfile
import time

import pytest

from core.logger import log, prune_logs, prune_temp_workspaces, set_debug

pytestmark = pytest.mark.fast


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
    logger_mod._Logger(name="eve-assistant-test-setdebug")

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


def test_prune_temp_workspaces_spares_unrelated_names_and_files(tmp_path, monkeypatch):
    """捕获「清 %TEMP% 时删了别人的目录 / 删了同名文件」这类破坏性缺陷。"""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    now = time.time()

    old_hit = tmp_path / "eve-shell-check-old"
    old_hit.mkdir()
    os.utime(old_hit, (now - 10 * 86400, now - 10 * 86400))

    fresh_hit = tmp_path / "eve-shell-check-fresh"  # 命中前缀但没到年限 → 留着
    fresh_hit.mkdir()

    unrelated = tmp_path / "some-other-tool"
    unrelated.mkdir()
    os.utime(unrelated, (now - 30 * 86400, now - 30 * 86400))

    same_name_file = tmp_path / "eve-shell-check-file"  # 同名但是文件，不是目录
    same_name_file.write_text("x", encoding="utf-8")
    os.utime(same_name_file, (now - 30 * 86400, now - 30 * 86400))

    removed = prune_temp_workspaces()

    assert removed == 1
    assert not old_hit.exists()
    assert fresh_hit.exists()
    # 负向断言：非白名单前缀的目录、同名文件必须原封不动
    assert unrelated.exists()
    assert same_name_file.exists()

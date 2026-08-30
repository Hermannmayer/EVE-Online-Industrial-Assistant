"""测试崩溃记录与环境信息采集模块（core/diagnostics.py）"""

import sys
import threading

import pytest

from core import paths
from core.diagnostics import (
    _thread_excepthook,
    collect_env_info,
    install_background_hooks,
    write_crash_dump,
)

pytestmark = pytest.mark.fast


def test_collect_env_info_has_expected_keys():
    info = collect_env_info()
    for key in (
        "app_version",
        "frozen",
        "executable",
        "platform",
        "python",
        "log_dir",
        "crashes_dir",
        "database_dir",
        "reference_db",
        "market_db",
        "user_db",
        "blueprint_db",
        "pyside6_version",
    ):
        assert key in info
        assert info[key] != ""


def test_write_crash_dump_contains_header_and_traceback(tmp_path):
    try:
        raise ValueError("syndrome boom")
    except ValueError:
        exc_info = sys.exc_info()

    crash_file = write_crash_dump(exc_info, crash_dir=tmp_path)

    assert crash_file is not None
    assert crash_file.name.startswith("crash_")
    assert crash_file.name.endswith(".log")
    text = crash_file.read_text(encoding="utf-8")
    assert text.startswith("=")
    assert "崩溃转储" in text
    assert "app_version" in text
    assert "ValueError" in text
    assert "syndrome boom" in text


def test_write_crash_dump_accepts_bare_exception(tmp_path):
    crash_file = write_crash_dump(ValueError("bare"), crash_dir=tmp_path)
    assert crash_file is not None
    assert "ValueError" in crash_file.read_text(encoding="utf-8")


def test_thread_excepthook_writes_crash_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "crashes_dir", lambda: tmp_path / "crashes")

    captured = {}

    def spy(args):
        captured["args"] = args

    orig = threading.excepthook
    threading.excepthook = spy
    try:

        def boom():
            raise RuntimeError("thread boom")

        t = threading.Thread(target=boom)
        t.start()
        t.join()
    finally:
        threading.excepthook = orig

    assert "args" in captured, "真实线程异常应触发 threading.excepthook"
    # 不弹窗：_thread_excepthook 只记录落盘
    _thread_excepthook(captured["args"])
    files = list((tmp_path / "crashes").glob("crash_*.log"))
    assert files
    assert "thread boom" in files[0].read_text(encoding="utf-8")


def test_install_background_hooks_registers_thread_excepthook(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "crashes_dir", lambda: tmp_path / "crashes")
    install_background_hooks()
    assert threading.excepthook is _thread_excepthook
    # 幂等：重复安装不抛
    install_background_hooks()

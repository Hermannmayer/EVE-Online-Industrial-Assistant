"""Tests for core.single_instance module."""

import os

import pytest

import core.single_instance as si
from core.single_instance import _is_pid_alive, try_lock, unlock

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def _clean_lock():
    """Ensure lock file is cleaned before and after each test."""
    unlock()
    yield
    unlock()


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    """Redirect the lock file to a temp location so tests never touch the real one."""
    path = tmp_path / "instance.lock"
    monkeypatch.setattr(si, "_LOCK_FILE", path)
    return path


class TestTryLock:
    def test_first_acquire_succeeds(self, lock_path):
        assert try_lock(force=False) is True
        assert lock_path.read_text() == f"{os.getpid()}:{os.name}"

    def test_force_skips_check(self, lock_path):
        # force 只跳过检查：既不写锁文件、也不拥有它
        assert try_lock(force=True) is True
        assert not lock_path.exists()

    def test_same_process_reacquires(self, lock_path):
        try_lock(force=False)
        assert try_lock(force=False) is True

    def test_unlock_releases(self, lock_path):
        try_lock(force=False)
        unlock()
        assert not si._LOCK_FILE.exists()

    def test_another_alive_process_denies(self, lock_path, monkeypatch):
        lock_path.write_text("999999:nt")
        monkeypatch.setattr(si, "_is_pid_alive", lambda pid: True)
        assert try_lock(force=False) is False
        assert lock_path.read_text() == "999999:nt", "不应覆盖存活实例的锁文件"

    def test_dead_process_stale_lock_reacquires(self, lock_path):
        lock_path.write_text("999999:nt")
        assert try_lock(force=False) is True
        assert lock_path.read_text() == f"{os.getpid()}:{os.name}", "残留锁应被本进程 PID 覆盖"

    def test_write_failure_degrades_to_run(self, lock_path, monkeypatch):
        """Windows 瞬时锁冲突：原子建锁失败时应降级运行而非崩溃。"""

        def _boom(*a, **kw):
            raise PermissionError(13, "Permission denied")

        # 生产用 os.open(O_CREAT|O_EXCL) 原子建锁，不是 Path.write_text
        monkeypatch.setattr(si.os, "open", _boom)
        assert try_lock(force=False) is True

    def test_read_failure_degrades_to_run(self, lock_path, monkeypatch):
        """锁文件读取失败（被瞬时占用）时应清理后重建而非崩溃。"""
        lock_path.write_text("999999:nt")

        def _boom(*a, **kw):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(type(lock_path), "read_text", _boom)
        assert try_lock(force=False) is True
        assert si._LOCK_FILE.exists()

    def test_unlink_failure_degrades_to_run(self, lock_path, monkeypatch):
        """删除 stale 锁失败（句柄被占用）时应吞掉错误继续加锁。"""
        lock_path.write_text("999999:nt")

        def _boom(*a, **kw):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(type(lock_path), "unlink", _boom)
        assert try_lock(force=False) is True

    def test_custom_lock_file_isolation(self, lock_path, tmp_path):
        """自定义 lock_file 互相隔离，unlock 只删指定文件。"""
        a = tmp_path / "a.lock"
        b = tmp_path / "b.lock"
        assert try_lock(lock_file=a) is True
        assert try_lock(lock_file=b) is True
        assert a.exists() and b.exists()
        unlock(lock_file=a)
        assert not a.exists()
        assert b.exists()
        unlock(lock_file=b)
        assert not b.exists()

    def test_default_lock_unchanged(self, lock_path):
        """无 lock_file 参数时写入默认 _LOCK_FILE。"""
        assert try_lock() is True
        assert si._LOCK_FILE.exists()

    def test_lock_file_accepts_str(self, lock_path, tmp_path):
        """传 str 路径可被归一化为 Path。"""
        target = tmp_path / "str.lock"
        assert try_lock(lock_file=str(target)) is True
        assert target.exists()
        unlock(lock_file=str(target))
        assert not target.exists()

    def test_unlock_with_custom_then_default(self, lock_path, tmp_path):
        """unlock(lock_file=...) 不误删默认锁。"""
        custom = tmp_path / "custom.lock"
        try_lock()
        try_lock(lock_file=custom)
        unlock(lock_file=custom)
        assert not custom.exists()
        assert si._LOCK_FILE.exists()
        unlock()
        assert not si._LOCK_FILE.exists()


class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_invalid_pid_is_dead(self):
        assert _is_pid_alive(999999) is False

    def test_windows_probe_never_calls_os_kill(self, monkeypatch):
        """回归：Windows 上探活**不得**走 `os.kill(pid, 0)`。

        `os.kill` 在 Windows 不是探活 —— CPython 文档写明任意非控制台信号走
        `TerminateProcess`，实测还会打断整个控制台进程组。修复前这条用例一跑，
        整轮 pytest 在 `test_current_process_is_alive` 那行就没了（无 traceback、
        退出码 0，看着像「跑完了」）。所以这里把 `os.kill` 换成会炸的替身，
        断言探活照样给出正确答案。
        """
        if os.name != "nt":
            pytest.skip("该风险只在 Windows 上存在")

        def _boom(*_a, **_kw):
            raise AssertionError("Windows 上不得用 os.kill 探活（会终止目标进程）")

        monkeypatch.setattr(si.os, "kill", _boom)

        assert _is_pid_alive(os.getpid()) is True
        assert _is_pid_alive(999999) is False

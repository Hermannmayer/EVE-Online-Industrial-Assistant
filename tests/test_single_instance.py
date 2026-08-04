"""Tests for core.single_instance module."""

import pytest

import core.single_instance as si
from core.single_instance import _is_pid_alive, try_lock, unlock


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

    def test_force_skips_check(self, lock_path):
        assert try_lock(force=True) is True

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

    def test_dead_process_stale_lock_reacquires(self, lock_path):
        lock_path.write_text("999999:nt")
        assert try_lock(force=False) is True

    def test_write_failure_degrades_to_run(self, lock_path, monkeypatch):
        """Windows 瞬时锁冲突：写锁失败时应降级运行而非崩溃。"""

        def _boom(*a, **kw):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(type(lock_path), "write_text", _boom)
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
        import os

        assert _is_pid_alive(os.getpid()) is True

    def test_invalid_pid_is_dead(self):
        assert _is_pid_alive(999999) is False

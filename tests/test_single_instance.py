"""Tests for core.single_instance module."""

import pytest

from core.single_instance import _LOCK_FILE, _is_pid_alive, try_lock, unlock


@pytest.fixture(autouse=True)
def _clean_lock():
    """Ensure lock file is cleaned before and after each test."""
    unlock()
    yield
    unlock()


class TestTryLock:
    def test_first_acquire_succeeds(self):
        assert try_lock(force=False) is True

    def test_force_skips_check(self):
        assert try_lock(force=True) is True

    def test_same_process_reacquires(self):
        try_lock(force=False)
        assert try_lock(force=False) is True

    def test_unlock_releases(self):
        try_lock(force=False)
        unlock()
        assert not _LOCK_FILE.exists()


class TestIsPidAlive:
    def test_current_process_is_alive(self):
        import os

        assert _is_pid_alive(os.getpid()) is True

    def test_invalid_pid_is_dead(self):
        assert _is_pid_alive(999999) is False

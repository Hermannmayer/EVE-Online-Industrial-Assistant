"""Single-instance lock using PID file.

默认锁文件为 `~/.eve-assistant/instance.lock`(Main.py 使用)。可传入自定义
`lock_file` 加独立锁,例如 dev.py 用 `~/.eve-assistant/dev.lock`——启动器与
应用实例的锁必须分离,二者才能共存。
"""

import os
from pathlib import Path

from core.logger import log

_LOCK_FILE = Path.home() / ".eve-assistant" / "instance.lock"


def _resolve(lock_file: Path | str | None) -> Path:
    """None → 默认 instance.lock;str → Path 归一化(Path(Path) 幂等)。"""
    return Path(lock_file) if lock_file else _LOCK_FILE


def try_lock(force: bool = False, lock_file: Path | str | None = None) -> bool:
    """Attempt to acquire the single-instance lock.

    Args:
        force: 跳过锁检查直接返回 True。
        lock_file: 自定义锁文件路径;None 使用默认 instance.lock。

    Returns True if the lock is acquired (this instance may run).
    Returns False if another instance is already running.
    """
    if force:
        return True

    target = _resolve(lock_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    own_pid = os.getpid()

    if target.exists():
        try:
            data = target.read_text().strip()
            pid_str, _hostname = data.split(":", 1)
            pid = int(pid_str)
        except (ValueError, OSError):
            # 锁文件损坏或读取失败（可能正被其他进程瞬时占用）→ 清理后重建
            _safe_unlink(target)
            return _acquire(own_pid, target)

        if pid != own_pid:
            if _is_pid_alive(pid):
                return False
            _safe_unlink(target)

    return _acquire(own_pid, target)


def _acquire(own_pid: int, target: Path) -> bool:
    """写入锁文件；失败时降级为允许运行，避免 Windows 瞬时锁冲突导致启动崩溃。"""
    try:
        target.write_text(f"{own_pid}:{os.name}")
        return True
    except OSError as e:
        log.warning("写入单实例锁文件失败 %s: %s — 降级运行", target, e)
        return True


def _safe_unlink(target: Path):
    """删除锁文件；删除失败（句柄被占用）时不抛出。"""
    try:
        target.unlink(missing_ok=True)
    except OSError as e:
        log.warning("删除单实例锁文件失败 %s: %s", target, e)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (AttributeError, OSError):
        return _win32_is_pid_alive(pid)


def _win32_is_pid_alive(pid: int) -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        STILL_ACTIVE = 259
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return True


def unlock(lock_file: Path | str | None = None):
    """Release the single-instance lock.

    Args:
        lock_file: 要释放的自定义锁文件;None 释放默认 instance.lock。
    """
    target = _resolve(lock_file)
    try:
        target.unlink(missing_ok=True)
    except OSError as e:
        log.warning("释放单实例锁失败 %s: %s", target, e)


def show_message():
    """Print a notice to stderr that another instance is already running."""
    print("EVE 商人助手已在运行中。", flush=True)
    print("   如需强制启动新实例，请使用 --force 参数。", flush=True)

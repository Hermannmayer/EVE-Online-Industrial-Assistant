"""Single-instance lock using PID file.

默认锁文件为 `~/.eve-assistant/instance.lock`(Main.py 使用)。可传入自定义
`lock_file` 加独立锁,例如 dev.py 用 `~/.eve-assistant/dev.lock`——启动器与
应用实例的锁必须分离,二者才能共存。
"""

import ctypes
import hashlib
import os
from pathlib import Path

from core.logger import log

_LOCK_FILE = Path.home() / ".eve-assistant" / "instance.lock"

# 本进程持有的命名互斥体句柄（lock 名 → HANDLE）。进程退出时 OS 自动回收，
# 崩溃也无需清理残留——比文件锁更健壮。
_MUTEX_HANDLES: dict[str, int] = {}


def _resolve(lock_file: Path | str | None) -> Path:
    """None → 默认 instance.lock;str → Path 归一化(Path(Path) 幂等)。"""
    return Path(lock_file) if lock_file else _LOCK_FILE


def _mutex_name(target: Path) -> str:
    """锁文件路径 → 命名互斥体名。

    按路径 hash 区分：不同 lock_file（instance/dev/fresh）用不同互斥体，
    与文件锁语义一致；测试 monkeypatch _LOCK_FILE 后也自然隔离。
    """
    digest = hashlib.md5(str(target).encode("utf-8")).hexdigest()[:24]
    return f"EVEAssistant_{digest}"


def _acquire_mutex(name: str) -> bool | None:
    """获取 Windows 命名互斥体。

    Returns:
        True = 本进程持有；False = 另一实例已持有；None = 非 Windows/创建失败（降级回退文件锁）。

    命名互斥体是内核对象，创建不需要文件写权限——受限沙箱 token 下
    （.eve-assistant 目录只读导致文件锁必然 PermissionError）仍能正常防双开。
    """
    if os.name != "nt":
        return None
    if name in _MUTEX_HANDLES:
        return True  # 本进程已持有（重入）
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, name)
    except (AttributeError, OSError):
        return None
    if not handle:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS → 另一实例持有
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _MUTEX_HANDLES[name] = handle
    return True


def _release_mutex(name: str) -> None:
    handle = _MUTEX_HANDLES.pop(name, None)
    if not handle:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass  # 句柄释放失败无碍：进程退出时 OS 会回收


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

    # 0) Windows 命名互斥体优先判定：不依赖文件权限，受限沙箱下文件锁必失败时
    #    仍能正常防双开。mutex_ok False = 另一实例持有 → 直接拒绝。
    mutex_name = _mutex_name(target)
    mutex_ok = _acquire_mutex(mutex_name)
    if mutex_ok is False:
        return False

    # 1) 原子获取（O_CREAT|O_EXCL）：成功即拿到锁，无双开竞态
    got = _try_exclusive_acquire(own_pid, target)
    if got is True:
        return True
    if got is None:
        return True  # IO 失败降级为允许运行

    # 2) 文件已存在：读取 PID 判定是残留还是存活实例
    try:
        data = target.read_text().strip()
        pid_str, _hostname = data.split(":", 1)
        pid = int(pid_str)
    except (ValueError, OSError):
        # 锁文件损坏 → 清理后重试原子获取
        _safe_unlink(target)
        got = _try_exclusive_acquire(own_pid, target)
        return True if got is not False else False

    if pid == own_pid:
        return True  # 自身已持有（重入）
    if _is_pid_alive(pid):
        return False  # 另一实例正在运行
    # 残留 PID（已死进程）→ 清理后原子重取
    _safe_unlink(target)
    got = _try_exclusive_acquire(own_pid, target)
    if got is True or got is None:
        return True
    # 极窄窗口：清理后又被另一进程占住 → 按其是否存活判定
    try:
        data = target.read_text().strip()
        pid = int(data.split(":", 1)[0])
        return not _is_pid_alive(pid)
    except Exception:
        return False


def _try_exclusive_acquire(own_pid: int, target: Path) -> bool | None:
    """原子创建锁文件（O_EXCL），消除 check-then-act 竞态。

    Returns:
        True = 本次成功取得锁；False = 文件已存在（被占/残留）；
        None = IO 失败（调用方降级为允许运行，避免 Windows 瞬时锁冲突导致启动崩溃）。
    """
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, f"{own_pid}:{os.name}".encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError as e:
        log.warning("写入单实例锁文件失败 %s: %s — 降级运行", target, e)
        return None


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
    _release_mutex(_mutex_name(target))
    try:
        target.unlink(missing_ok=True)
    except OSError as e:
        log.warning("释放单实例锁失败 %s: %s", target, e)


def show_message():
    """Print a notice to stderr that another instance is already running."""
    print("EVE 商人助手已在运行中。", flush=True)
    print("   如需强制启动新实例，请使用 --force 参数。", flush=True)

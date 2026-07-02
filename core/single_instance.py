"""Single-instance lock using PID file."""
import os
from pathlib import Path

_LOCK_FILE = Path.home() / ".eve-assistant" / "instance.lock"


def try_lock(force: bool = False) -> bool:
    """Attempt to acquire the single-instance lock.

    Returns True if the lock is acquired (this instance may run).
    Returns False if another instance is already running.
    """
    if force:
        return True

    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    own_pid = os.getpid()

    if _LOCK_FILE.exists():
        try:
            data = _LOCK_FILE.read_text().strip()
            pid_str, _hostname = data.split(":", 1)
            pid = int(pid_str)
        except (ValueError, OSError):
            _LOCK_FILE.write_text(f"{own_pid}:{os.name}")
            return True

        if pid != own_pid:
            if _is_pid_alive(pid):
                return False
            _LOCK_FILE.unlink(missing_ok=True)

    _LOCK_FILE.write_text(f"{own_pid}:{os.name}")
    return True


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


def unlock():
    """Release the single-instance lock."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def show_message():
    """Print a notice to stderr that another instance is already running."""
    print("EVE 商人助手已在运行中。", flush=True)
    print("   如需强制启动新实例，请使用 --force 参数。", flush=True)

"""崩溃记录与环境信息采集 — 开发环境与发行版通用。

只依赖标准库，不依赖 Qt：弹窗等 UI 行为由 Main.py 持有；
本模块负责崩溃文件的落盘、后台线程异常兜底与 faulthandler 原生崩溃捕获。
"""

import faulthandler
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from core import paths, version
from core.logger import log


def collect_env_info() -> dict[str, str]:
    """采集运行环境信息，供崩溃转储表头与排障使用。"""
    info: dict[str, str] = {
        "app_version": version.__version__,
        "frozen": str(paths.is_frozen()),
        "executable": sys.executable,
        "platform": platform.platform(),
        "python": sys.version.replace("\n", " "),
        "log_dir": str(paths.log_dir()),
        "crashes_dir": str(paths.crashes_dir()),
        "database_dir": paths.database_dir(),
        "reference_db": paths.REF_DB_PATH,
        "market_db": paths.MKT_DB_PATH,
        "user_db": paths.USR_DB_PATH,
        "blueprint_db": paths.BP_DB_PATH,
    }
    try:
        import PySide6

        info["pyside6_version"] = PySide6.__version__
    except ImportError:
        info["pyside6_version"] = "N/A"
    return info


def _exception_value(exc_info) -> BaseException | None:
    """兼容 (type, value, tb) 元组与裸异常对象两种入参。"""
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        value = exc_info[1]
        if isinstance(value, BaseException):
            return value
        return None
    if isinstance(exc_info, BaseException):
        return exc_info
    return None


def write_crash_dump(exc_info, crash_dir: Path | None = None) -> Path | None:
    """写崩溃转储文件（环境信息表头 + traceback），返回文件路径；失败返回 None。

    crash_dir 默认为 ~/.eve-assistant/crashes，可传参便于测试。
    文件名带微秒，避免同一秒多线程崩溃互相覆盖。
    """
    target = crash_dir if crash_dir is not None else paths.crashes_dir()
    exc_value = _exception_value(exc_info)
    try:
        target.mkdir(parents=True, exist_ok=True)
        crash_file = target / f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.log"
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("EVE 商人助手 崩溃转储\n")
            f.write(f"时间: {datetime.now().isoformat(timespec='seconds')}\n")
            for key, value in collect_env_info().items():
                f.write(f"{key}: {value}\n")
            f.write("=" * 60 + "\n\n")
            if exc_value is not None:
                traceback.print_exception(exc_value, file=f)
            else:
                f.write("（无异常信息）\n")
        return crash_file
    except Exception:
        log.exception("写入崩溃转储失败")
        return None


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    """后台线程未捕获异常兜底：只记录落盘，不弹窗（避免阻塞 UI / 跨线程建窗）。"""
    log.error("后台线程未捕获异常", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    write_crash_dump((args.exc_type, args.exc_value, args.exc_traceback))


def install_background_hooks() -> None:
    """安装后台诊断钩子：threading.excepthook + faulthandler。

    PySide6 的 QThread.run() 逃逸异常实际上会走 sys.excepthook（由 Main.py 持有），
    threading.excepthook 是防御性兜底（raw threading.Thread 与未来代码）。
    faulthandler 捕获 Qt/C++ 原生段错误，windowed 下 stderr 是 NullWriter 不可用，
    必须写真实文件句柄。
    """
    threading.excepthook = _thread_excepthook

    if faulthandler.is_enabled():
        return
    crash_dir = paths.crashes_dir()
    try:
        crash_dir.mkdir(parents=True, exist_ok=True)
        faulthandler_file = crash_dir / f"crash_faulthandler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        faulthandler.enable(file=open(faulthandler_file, "a"))
    except OSError:
        log.exception("无法启用 faulthandler")

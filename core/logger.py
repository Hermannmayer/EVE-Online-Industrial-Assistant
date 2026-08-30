"""
结构化日志模块 — 统一日志输出

用法:
    from core.logger import log
    log.info("消息")
    log.warning("警告")
    log.error("错误")
    log.debug("调试")
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from core.null_streams import NullWriter, ensure_console_streams
from core.paths import log_dir

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"


class _Logger:
    """轻量日志封装 — 控制台输出 + 文件日志"""

    def __init__(self, name: str = "eve-assistant"):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        # 控制台 handler。--windowed 无控制台时 sys.stdout/stderr 为 None，
        # 先兜底为 NullWriter，避免 StreamHandler 接到 None 在 emit 时抛异常。
        ensure_console_streams()
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        self._logger.addHandler(console)

        # 文件 handler（INFO 及以上级别写入文件）。
        # info 级功能日志落盘，便于发行版定位问题与功能运行情况。
        # 日志文件是发行版诊断的第一手材料，失败绝不静默：写 stderr（已兜底）
        # 暴露问题，避免"日志没生成还不知情"。
        try:
            dir_path = log_dir()
            dir_path.mkdir(parents=True, exist_ok=True)
            log_file = dir_path / f"app_{datetime.now().strftime('%Y%m%d')}.log"
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
            self._logger.addHandler(fh)
        except Exception:
            stream = sys.stderr if sys.stderr is not None else NullWriter()
            stream.write("[logger] 无法创建文件日志，运行信息不会落盘\n")

    def info(self, msg: str, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)


log = _Logger()


def set_debug(enabled: bool = True):
    """切换 debug 模式"""
    level = logging.DEBUG if enabled else logging.INFO
    for h in log._logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(level)


def prune_logs(logs_dir: Path, crashes_dir: Path, retention_days: int = 14) -> int:
    """删除超过 retention_days 天的日志与崩溃转储文件，返回删除数量。

    按 mtime 判定（不用文件名日期，容错）；单文件删除失败静默跳过，
    目录无权限时写 stderr 提示、不抛出。
    """
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for base_dir in (logs_dir, crashes_dir):
        for pattern in ("app_*.log", "crash_*.log"):
            try:
                for path in base_dir.glob(pattern):
                    try:
                        if path.stat().st_mtime < cutoff:
                            path.unlink(missing_ok=True)
                            removed += 1
                    except OSError:
                        pass
            except OSError:
                stream = sys.stderr if sys.stderr is not None else NullWriter()
                stream.write(f"[logger] 无法清理日志目录 {base_dir}\n")
    return removed

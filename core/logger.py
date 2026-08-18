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
from datetime import datetime
from pathlib import Path

from core.null_streams import NullWriter, ensure_console_streams

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

        # 文件 handler（仅 error 及以上级别写入文件）。
        # 日志文件是发行版诊断的第一手材料，失败绝不静默：写 stderr（已兜底）
        # 暴露问题，避免“日志没生成还不知情”。
        try:
            log_dir = Path.home() / ".eve-assistant" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.WARNING)
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

    def exception(self, msg: str, *args, **kwargs):
        self._logger.exception(msg, *args, **kwargs)


log = _Logger()


def set_debug(enabled: bool = True):
    """切换 debug 模式"""
    level = logging.DEBUG if enabled else logging.INFO
    for h in log._logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(level)

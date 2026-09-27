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
import shutil
import sys
import tempfile
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


# 会往 %TEMP% 里造目录的前缀白名单 —— 每一项都能指到造它的那行代码。
# 工具/用例正常退出时自己会删，这里兜的是**被强杀**的残留（进程被 faulthandler
# 杀掉、测试会话被中断时，yield 后面的清理不会执行）。
_TEMP_WORKSPACE_PREFIXES: tuple[str, ...] = (
    "eve-shell-check-",  # scripts/shell_snapshot.py --real 的隔离应用根目录（单份 600~900 MB）
    "eve_test_",  # tests/conftest.py temp_db（另含 test_getitems / test_sde_loader 等）
    "eve_dbmgr_",  # tests/conftest.py db_manager
    "eve_snap_",  # tests/test_asset_snapshot.py
    "eve_planexec_",  # tests/test_plan_execution.py
    "eve_mkt_",  # tests/test_price_history.py
    "eve_proc_",  # tests/test_procurement.py
    "eve_wl_",  # tests/test_watchlist_manager.py
    "inv_test_",  # tests/test_inventory_manager.py
    "inv_import_",  # tests/test_inventory_manager.py
    "init_check_",  # tests/test_init_check.py
)


def prune_temp_workspaces(
    prefixes: tuple[str, ...] = _TEMP_WORKSPACE_PREFIXES,
    max_age_days: int = 3,
) -> int:
    """删除 %TEMP% 下超过 max_age_days 天的临时工作目录，返回删除数量。

    口径与 `prune_logs` 一致：按 `st_mtime` 判定、失败只记日志不抛出。
    区别是这里删的是**目录**且风险更高 —— `%TEMP%` 是共享目录，所以加两道闸：
    名字必须命中 prefixes 白名单，且必须是目录（文件与符号链接一律不碰）。
    """
    temp_dir = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        entries = list(temp_dir.iterdir())
    except OSError:
        log.warning("[logger] 无法读取临时目录 %s，跳过清理", temp_dir)
        return 0

    for entry in entries:
        if not entry.name.startswith(prefixes):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry)
        except OSError:
            # 被占用（另一个实例正在用这个目录）/ 权限不足：留着下次再试
            log.debug("[logger] 临时工作目录删除失败，跳过：%s", entry)
            continue
        removed += 1
    return removed

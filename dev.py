"""
开发模式启动器 — 监听文件变更后自动重启（带防抖，避免连续变更频繁重启）

用法:
    python dev.py              # 普通开发模式（自动重启）
    python dev.py --debug      # 调试日志 + 自动重启
    python dev.py --no-watch   # 仅重启不动监测
    python dev.py --fresh      # 全新开箱：隔离目录模拟发行版环境，走首次初始化
    python dev.py --fresh --keep  # 复用已有隔离环境（模拟二次启动）

依赖:
    pip install watchdog    # 可选，更快的文件监听
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.hot_reload import clear_trigger, write_trigger
from core.single_instance import try_lock, unlock

ROOT = Path(__file__).parent.resolve()
WATCH_DIRS = ["core", "services", "ui_pyside6", "."]
WATCH_EXTS = (".py", ".qss", ".ui")
# 只监听应用运行相关代码。"." 递归覆盖整个仓库，必须排除：
#   .claude/  — agent 的工作树/会话数据（改它们无需重启应用）
#   data/ database/ — 运行时状态（app 自身写入，非源码）
#   docs/ tests/ scripts/ tools/ build/ — 非运行时代码
IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".claude",
    "venv",
    ".venv",
    "build",
    "dist",
    ".pytest_cache",
    "data",
    "database",
    "docs",
    "tests",
    "scripts",
    "tools",
}
RESTART_COOLDOWN = 15.0  # 重启后多少秒内不再重启（保护新进程启动期，防止连环重启）
DEBOUNCE_SECONDS = 12.0  # 距最近一次真实变更安静多少秒后再重启（agent 连续改文件时不断顺延）
FORCE_KILL_SETTLE = 1.5  # 强制终止后等待 OS 释放 SQLite 文件句柄，再启动新进程

# dev.py 自身的单实例锁：与 Main.py 的 instance.lock 分离，启动器才能启动应用子进程
DEV_LOCK = Path.home() / ".eve-assistant" / "dev.lock"

# 全新开箱模式（--fresh）：隔离目录模拟发行版环境。database/data 全部写入该目录，
# 不碰开发仓库；core.paths.app_root() 通过环境变量 EVE_ASSISTANT_APP_ROOT 指向它。
FRESH_ENV_DIR = ROOT / "fresh_env"
FRESH_ENV_VAR = "EVE_ASSISTANT_APP_ROOT"

# 开发模式日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dev")


def get_mtimes():
    """获取所有受监视文件的 mtime 字典"""
    mtimes = {}
    for d in WATCH_DIRS:
        target = ROOT / d
        if not target.exists():
            continue
        for f in target.rglob("*"):
            if f.suffix not in WATCH_EXTS:
                continue
            if any(ign in f.parts for ign in IGNORE_DIRS):
                continue
            mtimes[f] = f.stat().st_mtime
    return mtimes


def _is_watched_path(src_path: Path) -> bool:
    """是否属于受监视的应用源码（排除后台/运行时目录）。"""
    if src_path.suffix not in WATCH_EXTS:
        return False
    if any(ign in src_path.parts for ign in IGNORE_DIRS):
        return False
    return True


def _mtime_changed(known_mtimes: dict[str, float], src_path: Path, epsilon: float = 1e-3) -> bool:
    """是否真实变更：磁盘 mtime 相对基线有变化（并更新基线）。

    Windows 下 watchdog 首次扫描会误报大量 on_modified（文件并未改动），
    mtime 未变 → 返回 False 忽略。真实编辑会改变 mtime → 返回 True 并更新基线。
    """
    try:
        mtime = src_path.stat().st_mtime
    except OSError:
        return False
    key = os.path.normcase(str(src_path.resolve()))
    prev = known_mtimes.get(key)
    if prev is not None and abs(mtime - prev) < epsilon:
        return False
    known_mtimes[key] = mtime
    return True


class RestartState:
    """重启决策状态机 — 安静一段时间后才重启一次。

    - on_change：每次真实变更（无论是否在冷却期）都推进 last_change_time，
      让防抖窗口不断顺延 → agent 连续改文件时不会连环重启，等它真正停下来
      才重启一次（同一批变更只重启一次）。
    - should_restart：距最近变更 ≥ 防抖 且 冷却已过 → 可以重启。
    - mark_restarted：重启后进入冷却期，防止新进程启动期间被再次打断。
    """

    def __init__(self, debounce: float, cooldown: float):
        self.debounce = debounce
        self.cooldown = cooldown
        self.last_change_time = 0.0
        self.cooldown_until = 0.0
        self.restart_scheduled = False

    def on_change(self, now: float) -> None:
        self.last_change_time = now
        self.restart_scheduled = True

    def should_restart(self, now: float) -> bool:
        return self.restart_scheduled and now - self.last_change_time >= self.debounce and now >= self.cooldown_until

    def mark_restarted(self, now: float) -> None:
        self.restart_scheduled = False
        self.cooldown_until = now + self.cooldown


def build_args(debug: bool = False) -> list[str]:
    """构造 Main.py 子进程命令行；恒带 --hot-reload 以启用优雅退出（保存状态）。"""
    args = [sys.executable, str(ROOT / "Main.py")]
    if debug:
        args.append("--debug")
    args.append("--hot-reload")
    return args


def start_app(debug: bool = False):
    """启动 Main.py 子进程"""
    clear_trigger()  # 清除残留 trigger，避免新进程启动即触发热重载退出
    args = build_args(debug)
    log.info("启动: %s", " ".join(args))
    return subprocess.Popen(args, cwd=ROOT)


def start_fresh(keep: bool = False):
    """全新开箱模式：在隔离目录模拟发行版环境，跑真实首次初始化流程。

    模拟发行版路径布局：应用根目录指向 fresh_env/（空的 database/ data/），
    走 Main.py 的 InitWizard 自动初始化（下载 SDE → 建 4 库 → 写入数据）。

    - 默认（--fresh）：清空 fresh_env/ 重建，模拟新用户到手
    - --fresh --keep：保留已有环境，模拟二次启动
    """
    if not keep:
        shutil.rmtree(FRESH_ENV_DIR, ignore_errors=True)
    FRESH_ENV_DIR.mkdir(parents=True, exist_ok=True)

    log.info("全新开箱模式（模拟发行版环境）")
    log.info("  隔离目录: %s", FRESH_ENV_DIR)
    log.info("  %s", "保留已有环境数据（--keep，模拟二次启动）" if keep else "已重置为全新环境")
    log.info("  database/ 与 data/ 将写入该目录，不影响开发仓库")

    # --force：跳过单实例锁（隔离数据下允许与开发实例共存）；
    # 不传 --hot-reload：初始化中途被热重载退出会中断下载流程
    cmd = [sys.executable, str(ROOT / "Main.py"), "--force"]
    env = {**os.environ, FRESH_ENV_VAR: str(FRESH_ENV_DIR)}
    log.info("启动: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env)
    proc.wait()


def _wait_and_cleanup(proc, timeout: int = 5):
    """等待进程优雅退出，超时则强制终止"""
    if proc.poll() is not None:
        log.info("子进程已退出，跳过优雅退出流程")
        return
    write_trigger()
    log.info("等待进程优雅退出...")
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        log.warning("超时，强制终止...")
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(2)
        # 强杀可能让 SQLite WAL 处于中间态、文件句柄未即时释放；缓一缓再启动，
        # 避免新进程刚起来 4 库全报 disk I/O error（数据库随后自动恢复）。
        log.info("等待被终止进程释放资源 (%.1fs)...", FORCE_KILL_SETTLE)
        time.sleep(FORCE_KILL_SETTLE)


def _run():
    debug = "--debug" in sys.argv
    no_watch = "--no-watch" in sys.argv

    if debug:
        log.setLevel(logging.DEBUG)
        for handler in log.handlers:
            handler.setLevel(logging.DEBUG)

    if no_watch:
        proc = start_app(debug)
        proc.wait()
        return

    # 监听模式
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        state = RestartState(DEBOUNCE_SECONDS, RESTART_COOLDOWN)
        # 启动时的文件 mtime 基线。Windows 下 watchdog 首次扫描会误报大量
        # on_modified（文件并未改动），若不比对 mtime，启动约 12s 后会被误触发
        # 一次重启。只对 mtime 真变的文件视为变更。
        _known_mtimes: dict[str, float] = {os.path.normcase(str(p)): m for p, m in get_mtimes().items()}

        class RestartHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                src_path = Path(event.src_path)
                if not _is_watched_path(src_path):
                    return
                if not _mtime_changed(_known_mtimes, src_path):
                    return  # 扫描式误报：磁盘 mtime 未变，忽略
                # 真实变更：无论是否处于冷却期都推进 last_change_time，
                # 让防抖顺延——agent 连续改文件时不会连环重启。
                state.on_change(time.time())
                log.info("变更: %s", src_path.relative_to(ROOT))

        def _do_restart():
            nonlocal proc
            state.mark_restarted(time.time())
            if proc and proc.poll() is None:
                _wait_and_cleanup(proc)
            proc = start_app(debug)

        handler = RestartHandler()
        observer = Observer()
        for d in WATCH_DIRS:
            target = ROOT / d
            if target.exists():
                observer.schedule(handler, str(target), recursive=True)
        observer.start()
        log.info("文件监听已启动 (watchdog) | 防抖 %.1fs | 冷却 %.1fs", DEBOUNCE_SECONDS, RESTART_COOLDOWN)
        log.info("按 Ctrl+C 退出")

        proc = start_app(debug)
        try:
            while True:
                time.sleep(0.2)
                if state.should_restart(time.time()):
                    _do_restart()
        except KeyboardInterrupt:
            log.info("正在退出...")
            observer.stop()
            if proc and proc.poll() is None:
                _wait_and_cleanup(proc)
            observer.join()

    except ImportError:
        log.warning("watchdog 未安装，使用轮询模式 (pip install watchdog 可加速)")
        proc = start_app(debug)
        state = RestartState(DEBOUNCE_SECONDS, RESTART_COOLDOWN)
        try:
            last = get_mtimes()
            while True:
                time.sleep(0.2)
                current = get_mtimes()
                changed = [p for p in current if current.get(p) != last.get(p)]
                now = time.time()
                if changed:
                    # 无论是否冷却都吸收进基线并顺延防抖 → 连续变更不连环重启
                    for p in changed:
                        log.info("变更: %s", p.relative_to(ROOT))
                    last = current
                    state.on_change(now)
                if state.should_restart(now):
                    state.mark_restarted(now)
                    if proc and proc.poll() is None:
                        _wait_and_cleanup(proc)
                    proc = start_app(debug)
        except KeyboardInterrupt:
            log.info("正在退出...")
            if proc and proc.poll() is None:
                _wait_and_cleanup(proc)


def main():
    if not try_lock(lock_file=DEV_LOCK):
        print("检测到另一个 dev.py 已在运行。", file=sys.stderr)
        print(f"  若确认无残留实例，请删除该文件后重试: {DEV_LOCK}", file=sys.stderr)
        sys.exit(1)
    try:
        if "--fresh" in sys.argv:
            start_fresh(keep="--keep" in sys.argv)
        else:
            _run()
    finally:
        unlock(lock_file=DEV_LOCK)


if __name__ == "__main__":
    main()

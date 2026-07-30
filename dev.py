"""
开发模式启动器 — 监听文件变更后自动重启（带防抖，避免连续变更频繁重启）

用法:
    python dev.py              # 普通开发模式（自动重启）
    python dev.py --debug      # 调试日志 + 自动重启
    python dev.py --no-watch   # 仅重启不动监测

依赖:
    pip install watchdog    # 可选，更快的文件监听
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
WATCH_DIRS = ["core", "services", "ui_pyside6", "."]
WATCH_EXTS = (".py", ".qss", ".ui")
IGNORE_DIRS = {"__pycache__", ".git", "venv", ".venv", "build", "dist", ".pytest_cache"}
RESTART_COOLDOWN = 15.0  # 重启后多少秒内忽略变更（agent 连续改文件时不会连环重启）
DEBOUNCE_SECONDS = 12.0  # 变更后等待多久无新变更再重启

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


def start_app(debug: bool = False):
    """启动 Main.py 子进程"""
    args = [sys.executable, str(ROOT / "Main.py")]
    if debug:
        args.append("--debug")
    log.info("启动: %s", " ".join(args))
    return subprocess.Popen(args, cwd=ROOT)


def _wait_and_cleanup(proc, timeout: int = 5):
    """等待进程优雅退出，超时则强制终止"""
    from core.hot_reload import write_trigger

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


def main():
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

        _restart_cooldown_until = 0.0
        _last_change_time = 0.0
        _restart_scheduled = False

        class RestartHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                src_path = Path(event.src_path)
                if src_path.suffix not in WATCH_EXTS:
                    return
                if any(ign in src_path.parts for ign in IGNORE_DIRS):
                    return
                nonlocal _last_change_time, _restart_scheduled
                now = time.time()
                if now < _restart_cooldown_until:
                    return
                _last_change_time = now
                log.info("变更: %s", src_path.relative_to(ROOT))
                _restart_scheduled = True

        def _do_restart():
            nonlocal proc, _restart_cooldown_until
            _restart_cooldown_until = time.time() + RESTART_COOLDOWN
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
                if _restart_scheduled:
                    now = time.time()
                    if now - _last_change_time >= DEBOUNCE_SECONDS and now >= _restart_cooldown_until:
                        _restart_scheduled = False
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
        _poll_cooldown_until = 0.0
        _poll_last_change = 0.0
        try:
            last = get_mtimes()
            while True:
                time.sleep(0.2)
                current = get_mtimes()
                changed = [p for p in current if current.get(p) != last.get(p)]
                now = time.time()
                if changed:
                    if now < _poll_cooldown_until:
                        continue
                    for p in changed:
                        log.info("变更: %s", p.relative_to(ROOT))
                    _poll_last_change = now
                    last = current
                # 防抖：距上次变更超过 DEBOUNCE_SECONDS 且冷却期已过 -> 重启
                if _poll_last_change > 0 and now - _poll_last_change >= DEBOUNCE_SECONDS:
                    if now >= _poll_cooldown_until:
                        _poll_cooldown_until = now + RESTART_COOLDOWN
                        if proc and proc.poll() is None:
                            _wait_and_cleanup(proc)
                        proc = start_app(debug)
                        _poll_last_change = 0
        except KeyboardInterrupt:
            log.info("正在退出...")
            if proc and proc.poll() is None:
                _wait_and_cleanup(proc)


if __name__ == "__main__":
    main()

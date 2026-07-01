"""
开发模式启动器 — 监听文件变更后自动重启

用法:
    python dev.py              # 普通开发模式（自动重启）
    python dev.py --debug      # 调试日志 + 自动重启
    python dev.py --no-watch   # 仅重启不动监测

依赖:
    pip install watchdog    # 可选，更快的文件监听
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
WATCH_DIRS = ["core", "services", "ui_pyside6", "."]
WATCH_EXTS = (".py", ".qss", ".ui")
IGNORE_DIRS = {"__pycache__", ".git", "venv", ".venv", "build", "dist", ".pytest_cache"}


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
    print(f"\n{'=' * 50}")
    print(f"  启动: {' '.join(args)}")
    print(f"{'=' * 50}\n")
    return subprocess.Popen(args, cwd=ROOT)


def main():
    debug = "--debug" in sys.argv
    no_watch = "--no-watch" in sys.argv

    if no_watch:
        # 单次启动
        proc = start_app(debug)
        proc.wait()
        return

    # 监听模式
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class RestartHandler(FileSystemEventHandler):
            def __init__(self):
                self.last_trigger = 0

            def on_modified(self, event):
                if event.is_directory:
                    return
                src_path = Path(event.src_path)
                if src_path.suffix not in WATCH_EXTS:
                    return
                if any(ign in src_path.parts for ign in IGNORE_DIRS):
                    return
                now = time.time()
                if now - self.last_trigger < 1:
                    return
                self.last_trigger = now
                print(f"\n📁 变更: {src_path.relative_to(ROOT)}")
                nonlocal proc
                if proc and proc.poll() is None:
                    print("  终止旧进程...")
                    from core.hot_reload import write_trigger
                    write_trigger()
                    print("  等待进程优雅退出...")
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        print("  超时，强制终止...")
                        proc.terminate()
                        try:
                            proc.wait(3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(2)
                proc = start_app(debug)

        handler = RestartHandler()
        observer = Observer()
        for d in WATCH_DIRS:
            target = ROOT / d
            if target.exists():
                observer.schedule(handler, str(target), recursive=True)
        observer.start()
        print("📡 文件监听已启动 (watchdog)")
        print("  按 Ctrl+C 退出\n")

        proc = start_app(debug)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 正在退出...")
            observer.stop()
            if proc and proc.poll() is None:
                from core.hot_reload import write_trigger
                write_trigger()
                print("  等待进程优雅退出...")
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    print("  超时，强制终止...")
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(2)
            observer.join()

    except ImportError:
        print("⚠ watchdog 未安装，使用轮询模式 (pip install watchdog 可加速)")
        proc = start_app(debug)
        try:
            last = get_mtimes()
            while True:
                time.sleep(1)
                current = get_mtimes()
                changed = [p for p in current if current.get(p) != last.get(p)]
                if changed:
                    for p in changed:
                        print(f"📁 变更: {p.relative_to(ROOT)}")
                    if proc and proc.poll() is None:
                        from core.hot_reload import write_trigger
                        write_trigger()
                        print("  等待进程优雅退出...")
                        try:
                            proc.wait(5)
                        except subprocess.TimeoutExpired:
                            print("  超时，强制终止...")
                            proc.terminate()
                            try:
                                proc.wait(3)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(2)
                    proc = start_app(debug)
                    last = current
        except KeyboardInterrupt:
            print("\n🛑 正在退出...")
            if proc and proc.poll() is None:
                from core.hot_reload import write_trigger
                write_trigger()
                print("  等待进程优雅退出...")
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    print("  超时，强制终止...")
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(2)


if __name__ == "__main__":
    main()

"""QML 外壳快照 —— 批次 6.1 的验证手段。**离屏与真窗口两种模式**。

渲染 `ui_qml.shell_window.ShellWindow`（整页 QML 外壳）到 PNG，并打印关键区域信息。

**为什么要单独一个脚本**：`scripts/ui_snapshot.py` 走的是 `MainWindow`
（Widgets 外壳）——批次 6.1 之后主窗口是 QML，那个工具只能拍到回退路径。
两者都要留着：一个验证新外壳，一个验证回退。

两种模式各有不可替代之处：
- **离屏（默认）**：不弹窗、不抢焦点、不受单实例锁影响，可反复执行；但
  `QT_QPA_PLATFORM=offscreen` 下 **`QFontDatabase.families()` 是 0 个字体**，
  文字全渲染成方框 —— 只能验结构/配色/布局。
- **`--real`**：真窗口 + 真字体 + 真 DWM 毛玻璃，是**唯一**能确认字形与合成效果的方式；
  它会真的在屏幕上开一个窗，所以用**隔离的应用根目录**（复制 database/ 与 data/ 到临时目录），
  绝不会写用户真实的设置与数据库。

用法：
    python scripts/shell_snapshot.py                    # 离屏 → .claude/ui-snapshots/shell.png
    python scripts/shell_snapshot.py --size 1600x1000
    python scripts/shell_snapshot.py --page industry    # 只切到某页再拍
    python scripts/shell_snapshot.py --real             # 真窗口截图（隔离数据目录）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REAL = "--real" in sys.argv
if not _REAL:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from typing import Any  # noqa: E402

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_OUT_DIR = _ROOT / ".claude" / "ui-snapshots"


def _isolate_app_root() -> str:
    """把应用根目录指到临时目录（复制 database/ 与 data/），**不碰用户真实数据**。

    `core.paths.app_root()` 每次调用都读 `EVE_ASSISTANT_APP_ROOT`，所以在这里设就行。
    """
    tmp = tempfile.mkdtemp(prefix="eve-shell-check-")
    for name in ("database", "data"):
        src = _ROOT / name
        if src.is_dir():
            shutil.copytree(src, Path(tmp) / name)
    os.environ["EVE_ASSISTANT_APP_ROOT"] = tmp
    return tmp


def _spin(ms: int) -> None:
    """跑一小段事件循环（页面加载、布局、定时器都要它）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="1400x900", help="窗口尺寸 WxH")
    parser.add_argument("--page", default="", help="切到某个导航 key 再拍")
    parser.add_argument("--out", default="", help="输出 PNG 路径")
    parser.add_argument("--real", action="store_true", help="真窗口截图（隔离数据目录）")
    parser.add_argument(
        "--opaque",
        action="store_true",
        help="真窗口模式下强制不透明底色 —— 排掉「透明窗口合成」的干扰，用于判定重影来源",
    )
    args = parser.parse_args()

    width, _, height = args.size.partition("x")

    if args.real:
        tmp = _isolate_app_root()
        print(f"[外壳] 真窗口模式，应用根目录已隔离到：{tmp}")

    app = QApplication([])
    from ui_qml.shell_window import ShellWindow

    # 掐掉真实价格检查/下载：否则每跑一次都快照都会联网拉 ESI（慢、且结果不确定）。
    # 与 tests/conftest.py 对 MainWindow 的处理同一个理由。
    ShellWindow._init_price_check = lambda self: None  # type: ignore[method-assign]

    win = ShellWindow()
    if args.opaque:
        from PySide6.QtGui import QColor

        from ui_qml.theme import registry as _theme

        win.setColor(QColor(_theme.BG_DARK))
    win.resize(int(width), int(height))
    win.show()

    if args.real:
        # 真窗口：跑真事件循环，等 DWM 合成完再抓。
        # **抓两份**：屏幕像素包含毛玻璃与真字体，但窗口是透明的（非 solid 材质），
        # 屏幕抓图会把**窗口背后的内容**一起框进来 —— 所以再抓一份窗口自己的帧缓冲，
        # 用它判断「外壳本身画得对不对」，用屏幕那份判断「合成效果」。
        grabbed: dict[str, Any] = {}

        def _capture() -> None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                grabbed["screen"] = screen.grabWindow(int(win.winId()))
            grabbed["framebuffer"] = win.grabWindow()
            app.quit()

        QTimer.singleShot(2500, _capture)
        app.exec()
        image = grabbed.get("framebuffer")
        extra = grabbed.get("screen")
    else:
        _spin(1500)  # 页面 QML 是同步加载的，这里留给布局与首帧
        image = win.grabWindow()
        extra = None

    if args.page:
        if not win.navigate_to(args.page):
            print(f"[错误] 没有这个页面：{args.page}（已装载：{sorted(win._pages)}）")
            return 2
        if args.real:
            _spin(600)
            from PySide6.QtGui import QGuiApplication

            # 与上面「抓两份」同一套口径：`image` 要窗口**自己的帧缓冲**
            # （`grabWindow()` 把内容渲染到离屏缓冲，**不受遮挡影响**），
            # 屏幕那份留作 extra 供核对毛玻璃。
            #
            # ⚠️ 这里原先写的是 `image = screen.grabWindow(winId)` —— 那在 Windows 上是
            # 抓**屏幕区域**而不是抓窗口自身像素，窗口被别的窗口挡住时会把遮挡物一起拍进来
            # （实测拍到过整个桌面、把无关窗口当成页面图），而 `image` 的契约恰恰是
            # 「外壳本身画得对不对」。用它核对特定页面时会得到彻底错误的结果。
            image = win.grabWindow()
            screen = QGuiApplication.primaryScreen()
            extra = screen.grabWindow(int(win.winId())) if screen is not None else None
        else:
            _spin(800)
            image = win.grabWindow()

    if image is None or image.isNull():
        print("[错误] 抓到的图是空的 —— 外壳没有渲染出内容")
        return 3

    default_name = "shell.png" if not args.page else f"shell_{args.page}.png"
    if args.real:
        default_name = default_name.replace(".png", "_real.png")
    out = Path(args.out) if args.out else _OUT_DIR / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out)):
        print(f"[错误] 写图失败：{out}")
        return 4
    if extra is not None and not extra.isNull():
        screen_out = out.with_name(out.stem + "_screen.png")
        extra.save(str(screen_out))
        print(f"[外壳] 屏幕像素（含毛玻璃/背后内容）{screen_out}")

    mode = "真窗口" if args.real else "离屏"
    print(f"[外壳] {mode} {out}  {image.width()}x{image.height()}")
    print(f"[外壳] 已装载页面 {len(win._pages)} 个：{sorted(win._pages)}")
    print(f"[外壳] 当前页 = {win.current_page_key()!r}  状态栏 = {win._status_text!r}")

    # 结构性检查：内容区必须真的有页面，且只有一个可见
    area = win._content_area
    visible = [k for k, p in win._pages.items() if p.item.isVisible()]
    print(f"[外壳] 内容区 {int(area.width())}x{int(area.height())}，可见页面 = {visible}")
    if len(visible) != 1:
        print(f"[错误] 可见页面应当恰好 1 个，实际 {len(visible)} 个")
        return 5

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

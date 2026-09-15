"""QML 外壳离屏快照 —— 批次 6.1 的验证手段。

渲染 `ui_qml.shell_window.ShellWindow`（整页 QML 外壳）到 PNG，并打印关键区域信息。
默认走 Qt offscreen 平台：不弹窗、不抢焦点、不受单实例锁影响，可反复执行。

**为什么要单独一个脚本**：`scripts/ui_snapshot.py` 走的是 `MainWindow`
（Widgets 外壳）——批次 6.1 之后主窗口是 QML，那个工具只能拍到回退路径。
两者都要留着：一个验证新外壳，一个验证回退。

用法：
    python scripts/shell_snapshot.py                    # → .claude/ui-snapshots/shell.png
    python scripts/shell_snapshot.py --size 1600x1000
    python scripts/shell_snapshot.py --page industry    # 只切到某页再拍
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_OUT_DIR = _ROOT / ".claude" / "ui-snapshots"


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
    args = parser.parse_args()

    width, _, height = args.size.partition("x")

    app = QApplication([])  # noqa: F841 —— 必须活着，否则 QQuickView 起不来
    from ui_qml.shell_window import ShellWindow

    # 掐掉真实价格检查/下载：否则每跑一次都快照都会联网拉 ESI（慢、且结果不确定）。
    # 与 tests/conftest.py 对 MainWindow 的处理同一个理由。
    ShellWindow._init_price_check = lambda self: None  # type: ignore[method-assign]

    win = ShellWindow()
    win.resize(int(width), int(height))
    win.show()
    _spin(1500)  # 页面 QML 是同步加载的，这里留给布局与首帧

    if args.page:
        if not win.navigate_to(args.page):
            print(f"[错误] 没有这个页面：{args.page}（已装载：{sorted(win._pages)}）")
            return 2
        _spin(800)

    image = win.grabWindow()
    if image.isNull():
        print("[错误] grabWindow() 返回空图 —— 外壳没有渲染出内容")
        return 3

    out = Path(args.out) if args.out else _OUT_DIR / ("shell.png" if not args.page else f"shell_{args.page}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out)):
        print(f"[错误] 写图失败：{out}")
        return 4

    print(f"[外壳] {out}  {image.width()}x{image.height()}")
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

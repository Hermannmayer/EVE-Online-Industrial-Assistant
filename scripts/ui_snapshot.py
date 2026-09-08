"""界面快照工具 — 把 PySide6 界面渲染成 PNG + 控件树，供 Claude/人工审查。

默认以 Qt offscreen 平台运行：不弹窗、不抢焦点、不受单实例锁影响，
因此可以在开发过程中反复执行而不打扰正在使用软件的人。

用法::

    python scripts/ui_snapshot.py                    # 全部页面
    python scripts/ui_snapshot.py --pages query,industry
    python scripts/ui_snapshot.py --theme eve-deep   # 指定主题渲染
    python scripts/ui_snapshot.py --show             # 真窗口（肉眼确认）
    python scripts/ui_snapshot.py --out .claude/ui-snapshots

产物（默认输出到 .claude/ui-snapshots/，已被 .gitignore 忽略）::

    <out>/<page>.png          整窗截图（含导航栏 / 工具栏 / 状态栏）
    <out>/<page>.tree.md      控件树（类名 / objectName / 文本 / 几何 / 状态）
    <out>/index.json          索引：页面列表 + 各页控件数量

只截图不建树：`--no-tree`；只建树不截图：`--no-shot`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染界面快照（PNG + 控件树）")
    parser.add_argument("--out", default=".claude/ui-snapshots", help="输出目录")
    parser.add_argument("--pages", default="", help="逗号分隔的页面 key，默认全部")
    parser.add_argument("--theme", default="", help="主题 id，默认用上次偏好")
    parser.add_argument("--font-scale", type=float, default=0.0, help="字号缩放，默认读设置（1.0=出厂）")
    parser.add_argument("--size", default="1600x1000", help="窗口尺寸 WxH")
    parser.add_argument("--show", action="store_true", help="使用真实窗口平台而非 offscreen")
    parser.add_argument("--no-tree", action="store_true", help="不生成控件树")
    parser.add_argument("--no-shot", action="store_true", help="不生成截图")
    parser.add_argument("--max-depth", type=int, default=0, help="控件树最大深度，0=不限")
    return parser.parse_args(argv)


# ── 控件描述 ──────────────────────────────────────────────


def _text_of(w: Any) -> str:
    """尽力提取控件的可见文本，用于控件树标注。"""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QTableWidget,
        QTabWidget,
        QTreeWidget,
    )

    try:
        if isinstance(w, QGroupBox):
            return w.title()
        if isinstance(w, QTabWidget):
            return " | ".join(w.tabText(i) for i in range(w.count()))
        if isinstance(w, QTableWidget):
            cols = []
            for i in range(w.columnCount()):
                item = w.horizontalHeaderItem(i)
                cols.append(item.text() if item is not None else "")
            return f"{w.rowCount()}行 x {w.columnCount()}列 列头={cols}"
        if isinstance(w, QTreeWidget):
            return f"{w.topLevelItemCount()}个顶级项"
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text() or (f"占位符={w.placeholderText()}" if w.placeholderText() else "")
        if isinstance(w, QLabel):
            return w.text()
        if isinstance(w, QAbstractButton):
            return w.text() or w.toolTip()
    except RuntimeError:
        return ""  # 底层 C++ 对象已销毁
    return ""


def _describe(w: Any) -> str:
    """单行描述：类名 #objectName [几何] 文本 状态标记。"""
    cls = type(w).__name__
    name = w.objectName()
    head = f"{cls} #{name}" if name else cls
    geo = w.geometry()
    parts = [f"{head}  [{geo.x()},{geo.y()} {geo.width()}x{geo.height()}]"]
    text = _text_of(w)
    if text:
        parts.append(f'"{text}"')
    flags = []
    if not w.isVisible():
        flags.append("隐藏")
    if not w.isEnabled():
        flags.append("禁用")
    if flags:
        parts.append("(" + ",".join(flags) + ")")
    return " ".join(parts)


def _walk(w: Any, depth: int, max_depth: int, lines: list[str], counter: list[int]) -> None:
    from PySide6.QtWidgets import QWidget

    indent = "  " * depth
    lines.append(f"{indent}- {_describe(w)}")
    counter[0] += 1
    if max_depth and depth >= max_depth:
        return

    layout = w.layout()
    if layout is not None:
        margins = layout.contentsMargins()
        lines.append(
            f"{indent}  <{type(layout).__name__} "
            f"margins={margins.left()},{margins.top()},{margins.right()},{margins.bottom()} "
            f"spacing={layout.spacing()}>"
        )

    for child in w.children():
        if isinstance(child, QWidget):
            _walk(child, depth + 1, max_depth, lines, counter)


def dump_tree(widget: Any, max_depth: int = 0) -> tuple[str, int]:
    """返回 (控件树 markdown, 控件总数)。"""
    lines: list[str] = []
    counter = [0]
    _walk(widget, 0, max_depth, lines, counter)
    return "\n".join(lines), counter[0]


# ── 主流程 ────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # offscreen 必须在导入/创建 QApplication 之前设置
    if not args.show:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # 快照需要确定性的像素尺寸，禁用高 DPI 缩放带来的尺寸漂移
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

    from PySide6.QtWidgets import QApplication

    import ui_pyside6.theme as theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName("EVE 商人助手")
    if not args.show:
        _load_cjk_fonts(app)

    theme.set_font_scale(args.font_scale if args.font_scale else theme.load_font_scale())
    theme.apply_theme(args.theme or theme.load_theme_preference())

    from ui_pyside6.main_window import MainWindow

    win = MainWindow()
    width, height = (int(v) for v in args.size.lower().split("x"))
    win.resize(width, height)
    win.show()
    _settle(app)

    out_dir = (ROOT / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_keys = list(win._pages.keys())
    wanted = [k.strip() for k in args.pages.split(",") if k.strip()] or all_keys
    unknown = [k for k in wanted if k not in win._pages]
    if unknown:
        print(f"未知页面: {', '.join(unknown)}；可选: {', '.join(all_keys)}", file=sys.stderr)
        return 2

    index: dict[str, Any] = {
        "theme": theme.current_theme(),
        "size": f"{win.width()}x{win.height()}",
        "platform": os.environ.get("QT_QPA_PLATFORM", "default"),
        "pages": [],
    }

    for key in wanted:
        page = win._pages[key]
        win.content_stack.setCurrentWidget(page)
        _settle(app)

        entry: dict[str, Any] = {"key": key, "class": type(page).__name__}

        if not args.no_shot:
            path = out_dir / f"{key}.png"
            if win.grab().save(str(path)):
                entry["png"] = path.name
            else:
                entry["png_error"] = "grab().save() 失败"

        if not args.no_tree:
            tree, count = dump_tree(page, args.max_depth)
            header = f"# {key} — {type(page).__name__}\n\n"
            header += f"- 主题: {theme.current_theme()}\n- 页面尺寸: {page.width()}x{page.height()}\n"
            header += f"- 控件数: {count}\n\n```\n"
            (out_dir / f"{key}.tree.md").write_text(header + tree + "\n```\n", encoding="utf-8")
            entry["widgets"] = count

        index["pages"].append(entry)
        print(f"[快照] {key:12s} {entry.get('png', '')}")

    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n输出目录: {out_dir}")

    win.close()
    _settle(app)
    return 0


def _settle(app: Any, rounds: int = 12) -> None:
    """多轮 processEvents，让布局/延迟定时器/异步信号全部落地。"""
    for _ in range(rounds):
        app.processEvents()


# offscreen 平台不加载 Windows 字体库，中文会渲染成豆腐块（□□）；
# 显式注册系统 CJK 字体文件后再设为默认字体。
_CJK_FONT_FILES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf")
_CJK_FONT_DIRS = (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",)


def _load_cjk_fonts(app: Any) -> None:
    from PySide6.QtGui import QFont, QFontDatabase

    families: list[str] = []
    for directory in _CJK_FONT_DIRS:
        for name in _CJK_FONT_FILES:
            path = directory / name
            if not path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
    if not families:
        print("警告：未找到 CJK 字体，截图中中文将显示为方块", file=sys.stderr)
        return
    for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
        if candidate in families:
            app.setFont(QFont(candidate, 10))
            return
    app.setFont(QFont(families[0], 10))


if __name__ == "__main__":
    raise SystemExit(main())

"""界面结构规范图生成器 — 在真实截图上标注各区域名称，产出可沟通的「结构规范图」。

命名取自代码既有约定（如 `industry_view.py` 的「5 区布局」），不另起一套。
窗口级区域用虚线框，页面级区域用实线框，编号对应右侧图例。

用法::

    python scripts/ui_blueprint.py                 # 工业制造页（区域最完整）
    python scripts/ui_blueprint.py --page query    # 换页面
    python scripts/ui_blueprint.py --out docs/dev/assets/ui-blueprint.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPen  # noqa: E402

from scripts.ui_snapshot import _load_cjk_fonts, _settle  # noqa: E402

LEGEND_WIDTH = 460
BADGE_RADIUS = 11


def _rect_of(win, *widgets) -> QRect:
    """多个控件在窗口坐标系下的并集矩形。"""
    rects = []
    for w in widgets:
        if w is None:
            continue
        rects.append(QRect(w.mapTo(win, QPoint(0, 0)), w.size()))
    if not rects:
        return QRect()
    out = rects[0]
    for r in rects[1:]:
        out = out.united(r)
    return out


def _window_regions(win) -> list[tuple[str, str, QRect]]:
    from PySide6.QtWidgets import QToolBar, QTreeWidget

    nav_panel = win.findChild(type(win.centralWidget()), "nav_panel")
    return [
        ("标题栏", "title_bar", _rect_of(win, win._title_bar)),
        ("主工具栏", "main_toolbar", _rect_of(win, win.findChild(QToolBar, "main_toolbar"))),
        ("左侧导航栏", "nav_panel", _rect_of(win, nav_panel)),
        ("导航树", "nav_tree", _rect_of(win, win.findChild(QTreeWidget, "nav_tree"))),
        (
            "导航底部按钮组",
            "nav_bottom_buttons",
            _rect_of(win, win._hangar_settings_btn, win._char_settings_btn, win._sys_settings_btn),
        ),
        ("内容区", "content_stack", _rect_of(win, win.content_stack)),
        ("状态栏", "status_bar", _rect_of(win, win.status_bar)),
    ]


def _page_regions(page) -> list[tuple[str, str, QRect]]:
    """页面级区域，返回的是**页面局部坐标**，调用方需换算到窗口坐标。

    各页存在性不同，缺失的区域自动跳过。
    """
    regions: list[tuple[str, str, QRect]] = []

    title_label = getattr(page, "_title_label", None)
    toolbar = getattr(page, "_toolbar", None)
    if title_label is not None:
        r = _rect_of(page, title_label, getattr(page, "_plan_count", None))
        r.setLeft(0)
        r.setRight(page.width() - 1)
        if toolbar is not None:
            r.setBottom(toolbar.mapTo(page, QPoint(0, 0)).y() - 1)
        regions.append(("页面标题栏", "page_title_bar", r))

    if toolbar is not None:
        regions.append(("页面工具栏", "page_toolbar", _rect_of(page, toolbar)))

    body = getattr(page, "_view_stack", None) or getattr(page, "_table", None)
    if body is not None:
        regions.append(("主工作区", "page_body", _rect_of(page, body)))

    status = getattr(page, "_status_bar", None)
    if status is not None:
        regions.append(("页面状态栏", "page_status_bar", _rect_of(page, status)))

    actions = getattr(page, "_action_buttons", None)
    if actions is not None:
        regions.append(("页面功能按钮", "page_action_buttons", _rect_of(page, actions)))

    return regions


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成界面结构规范图")
    parser.add_argument("--page", default="industry", help="页面 key，默认 industry")
    parser.add_argument("--theme", default="", help="主题 id")
    parser.add_argument("--size", default="1600x1000", help="窗口尺寸 WxH")
    parser.add_argument("--out", default="docs/public/assets/ui-blueprint.png", help="输出 PNG 路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

    from PySide6.QtWidgets import QApplication

    import ui_pyside6.theme as theme

    app = QApplication(sys.argv[:1])
    _load_cjk_fonts(app)
    theme.apply_theme(args.theme or theme.load_theme_preference())

    from ui_pyside6.main_window import MainWindow

    win = MainWindow()
    width, height = (int(v) for v in args.size.lower().split("x"))
    win.resize(width, height)
    win.show()
    _settle(app)

    if args.page not in win._pages:
        print(f"未知页面: {args.page}；可选: {', '.join(win._pages)}", file=sys.stderr)
        return 2
    page = win._pages[args.page]
    win.content_stack.setCurrentWidget(page)
    _settle(app)

    shot = win.grab()

    # ── 画布：截图 + 右侧图例 ──
    canvas_w = shot.width() + LEGEND_WIDTH
    canvas = shot.__class__(canvas_w, shot.height())
    canvas.fill(QColor(theme.BG_DARK))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, shot)

    accent_cycle = [
        theme.PRIMARY,
        theme.ACCENT_CYAN,
        theme.ACCENT_GREEN,
        theme.ACCENT_ORANGE,
        theme.ACCENT_PURPLE,
        theme.ACCENT_YELLOW,
        theme.ACCENT_RED,
    ]

    legend: list[tuple[str, int, str, str, QColor]] = []
    number = 1

    page_origin = page.mapTo(win, QPoint(0, 0))
    sections = [
        ("窗口级区域", _window_regions(win), True),
        (
            f"页面级区域（{args.page} 页）",
            [(n, k, r.translated(page_origin)) for n, k, r in _page_regions(page)],
            False,
        ),
    ]

    for section, regions, dashed in sections:
        legend.append(("section", 0, section, "", QColor(theme.TEXT_BRIGHT)))
        for name, key, rect in regions:
            if rect.isEmpty():
                continue
            color = QColor(accent_cycle[(number - 1) % len(accent_cycle)])

            # 区域框
            pen = QPen(color, 2)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 26))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

            # 编号徽标：贴区域左上角内缘，并夹在画布内避免被裁切
            badge_x = min(max(rect.left() + BADGE_RADIUS + 2, BADGE_RADIUS + 2), canvas_w - BADGE_RADIUS - 2)
            badge_y = min(max(rect.top() + BADGE_RADIUS + 2, BADGE_RADIUS + 2), canvas.height() - BADGE_RADIUS - 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(badge_x, badge_y), BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor(theme.TEXT_ON_PRIMARY))
            painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold))
            painter.drawText(
                QRect(badge_x - BADGE_RADIUS, badge_y - BADGE_RADIUS, BADGE_RADIUS * 2, BADGE_RADIUS * 2),
                Qt.AlignmentFlag.AlignCenter,
                str(number),
            )

            legend.append(("item", number, name, key, color))
            number += 1

    # ── 右侧图例 ──
    x0 = shot.width() + 24
    y = 28
    painter.setPen(QColor(theme.TEXT_BRIGHT))
    painter.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
    painter.drawText(x0, y, "界面结构规范图")
    y += 26
    painter.setPen(QColor(theme.TEXT_SECONDARY))
    painter.setFont(QFont("Microsoft YaHei UI", 9))
    painter.drawText(x0, y, f"页面: {args.page}   主题: {theme.current_theme()}   虚线=窗口级  实线=页面级")
    y += 30

    for kind, number_, name, key, color in legend:
        if kind == "section":
            y += 10
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold))
            painter.drawText(x0, y, name)
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawLine(x0, y + 8, x0 + LEGEND_WIDTH - 60, y + 8)
            y += 30
            continue

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPoint(x0 + BADGE_RADIUS, y - 5), BADGE_RADIUS, BADGE_RADIUS)
        painter.setPen(QColor(theme.TEXT_ON_PRIMARY))
        painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold))
        painter.drawText(
            QRect(x0, y - 5 - BADGE_RADIUS, BADGE_RADIUS * 2, BADGE_RADIUS * 2),
            Qt.AlignmentFlag.AlignCenter,
            str(number_),
        )

        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
        painter.drawText(x0 + BADGE_RADIUS * 2 + 12, y, name)

        painter.setPen(QColor(theme.TEXT_SECONDARY))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(x0 + 180, y, key)
        y += 30

    painter.end()

    out_path = (ROOT / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out_path)):
        print("保存失败", file=sys.stderr)
        return 1
    print(f"已生成: {out_path}")

    win.close()
    _settle(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

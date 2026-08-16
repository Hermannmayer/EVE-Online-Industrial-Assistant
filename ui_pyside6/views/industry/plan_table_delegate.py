"""生产计划表格 Delegate — 展示职责（染色/图标/类别底色/复选框/按钮外观）。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import load_item_icon
from ui_pyside6.views.industry.plan_table_constants import (
    COL_CATEGORY,
    COL_CHECKBOX,
    COL_ICON,
    COL_PRODUCT,
    COL_PROFIT,
    COL_STATUS,
    COL_TIME,
)


def _remaining(p: dict, now: datetime | None = None) -> int | None:
    """计划剩余秒（进行中）；非进行中/无 started_at 返回 None"""
    from services.plan_execution import remaining_seconds

    return remaining_seconds(p, now=now)


# ═══════════════════════════════════════════════════════════
#  自绘小图标（类别 + 子项层级）— 16×16，QPainter 绘制，theme 色
#  ═══════════════════════════════════════════════════════════


def _make_icon(draw: Callable[[QPainter], None]) -> QIcon:
    """在透明 16×16 QPixmap 上执行 draw(painter) 生成 QIcon。"""
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(painter)
    painter.end()
    return QIcon(pm)


def _draw_gear(p: QPainter) -> None:
    """制造：齿轮（圆 + 8 齿，不挖中孔，16px 下清晰即可）。"""
    color = QColor(theme.TEXT_SECONDARY)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for i in range(8):
        p.save()
        p.translate(8, 8)
        p.rotate(i * 45)
        p.drawRect(QRectF(-1, -6.5, 2, 3))
        p.restore()
    p.drawEllipse(QRectF(3.5, 3.5, 9, 9))


def _draw_bulb(p: QPainter) -> None:
    """发明：灯泡（圆 + 灯座 + 光晕线）。"""
    color = QColor(theme.ACCENT_PURPLE)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(4, 2, 8, 8))
    p.drawRect(QRectF(6.5, 10, 3, 3))
    p.setPen(QPen(color, 1))
    p.drawLine(2, 5, 3, 5)
    p.drawLine(13, 5, 14, 5)
    p.drawLine(2, 8, 3, 8)


def _draw_flask(p: QPainter) -> None:
    """反应：三角烧瓶。"""
    color = QColor(theme.ACCENT_GREEN)
    path = QPainterPath()
    path.moveTo(5, 3.5)
    path.lineTo(5, 8)
    path.lineTo(3, 12.5)
    path.lineTo(13, 12.5)
    path.lineTo(11, 8)
    path.lineTo(11, 3.5)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _draw_clipboard(p: QPainter) -> None:
    """复制：剪贴板（带夹子的板）。"""
    color = QColor(theme.ACCENT_CYAN)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(4, 5, 8, 9), 1.5, 1.5)
    p.drawRect(QRectF(6, 2.5, 4, 3.5))


def _draw_level(p: QPainter) -> None:
    """子项：右拐箭头 ↳（区别于剪贴板，避免视觉混淆）。"""
    color = QColor(theme.TEXT_SECONDARY)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(3, 4), QPointF(13, 4))
    p.drawLine(QPointF(3, 4), QPointF(3, 10.5))
    p.drawLine(QPointF(3, 10.5), QPointF(6, 8.5))
    p.drawLine(QPointF(3, 10.5), QPointF(5, 12.5))


_CATEGORY_ICON_DRAWERS = {
    "manufacturing": _draw_gear,
    "invention": _draw_bulb,
    "reaction": _draw_flask,
    "copying": _draw_clipboard,
}

_icon_cache: dict[str, QIcon] = {}
_icon_theme_token: str | None = None


def _ensure_icons() -> None:
    """主题切换后重建图标缓存（图标色随 theme 变量变化）。"""
    global _icon_theme_token
    token = theme.current_theme()
    if token == _icon_theme_token:
        return
    _icon_theme_token = token
    _icon_cache.clear()
    for cat, drawer in _CATEGORY_ICON_DRAWERS.items():
        _icon_cache[f"cat:{cat}"] = _make_icon(drawer)
    _icon_cache["level"] = _make_icon(_draw_level)


def _category_icon(category: str | None) -> QIcon | None:
    """返回类别自绘图标；未知类别返回 None。"""
    _ensure_icons()
    return _icon_cache.get(f"cat:{category or 'manufacturing'}")


def _level_icon() -> QIcon:
    """返回子项层级箭头图标。"""
    _ensure_icons()
    return _icon_cache["level"]


class ReadyButtonDelegate(QStyledItemDelegate):
    """状态列「待下线」渲染为按钮外观（点击仍走 _on_cell_clicked 单独下线）"""

    def paint(self, painter, option, index):
        if index.column() == COL_STATUS and index.data(Qt.ItemDataRole.DisplayRole) == "待下线":
            self._paint_button(painter, option)
            return
        super().paint(painter, option, index)

    def _paint_button(self, painter, option):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(6, 3, -6, -3)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        bg = QColor(theme.ACCENT_ORANGE)
        if hovered:
            bg = bg.lighter(118)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(theme.TEXT_ON_PRIMARY))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "待下线")
        painter.restore()

    def sizeHint(self, option, index):
        if index.column() == COL_STATUS and index.data(Qt.ItemDataRole.DisplayRole) == "待下线":
            return QSize(64, 22)
        return super().sizeHint(option, index)


class PlanTableDelegate(QStyledItemDelegate):
    """PlanTableModel 渲染 delegate — 染色/图标/类别底色/复选框/对齐/尺寸。

    模型 data() 只暴露 DisplayRole（已算文本）+ UserRole（原始行 dict），
    纯展示职责（前景色/底色/图标/复选框/对齐/尺寸）在此 delegate 完成。
    """

    def _foreground(self, p: dict, c: int) -> QColor | None:
        if c == COL_PROFIT:
            profit = p.get("profit", 0) or 0
            if profit > 0:
                return QColor(theme.GREEN)
            if profit < 0:
                return QColor(theme.RED)
        if c == COL_TIME:
            status = p.get("status", "")
            if status in ("in_progress", "running"):
                rem = _remaining(p)
                if rem is not None and rem <= 0:
                    return QColor(theme.ACCENT_RED)
                return QColor(theme.PRIMARY)
            if status == "ready":
                return QColor(theme.ACCENT_ORANGE)
        if c == COL_STATUS:
            status = p.get("status", "")
            if status in ("completed", "done"):
                return QColor(theme.GREEN)
            if status in ("in_progress", "running"):
                return QColor(theme.PRIMARY)
            if status == "ready":
                return QColor(theme.ACCENT_ORANGE)
            if status == "pending":
                return QColor(theme.TEXT_SECONDARY)
        return None

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        p = index.data(Qt.ItemDataRole.UserRole) or {}
        c = index.column()

        fg = self._foreground(p, c)
        if fg is not None:
            option.palette.setColor(QPalette.ColorRole.Text, fg)

        _CATEGORY_COLORS = {
            "copying": theme.ACCENT_CYAN,
            "invention": theme.ACCENT_PURPLE,
            "reaction": theme.ACCENT_GREEN,
        }
        color = _CATEGORY_COLORS.get(str(p.get("category", "manufacturing")))
        if color:
            option.palette.setColor(QPalette.ColorRole.Base, QColor(color))

        if c == COL_ICON:
            pixmap = load_item_icon(p.get("product_type_id"))
            if pixmap is not None:
                option.icon = QIcon(pixmap)
                option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration

        if c == COL_CATEGORY:
            icon = _category_icon(str(p.get("category", "manufacturing")))
            if icon is not None:
                option.icon = icon
                option.text = ""  # 类别列只显示自绘图标
                option.displayAlignment = Qt.AlignmentFlag.AlignCenter
                option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration

        if c == COL_PRODUCT and int(p.get("child_level") or 0) > 0:
            # 子项：缩进文本前显示层级箭头（母项不显示）
            option.icon = _level_icon()
            option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration

        if c == COL_CHECKBOX:
            option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
            option.checkState = Qt.CheckState.Checked if p.get("materials_ready", 0) else Qt.CheckState.Unchecked
            option.displayAlignment = Qt.AlignmentFlag.AlignCenter

    def sizeHint(self, option, index):
        c = index.column()
        if c == COL_CHECKBOX:
            return QSize(26, 26)
        if c == COL_ICON:
            return QSize(36, 36)
        return super().sizeHint(option, index)

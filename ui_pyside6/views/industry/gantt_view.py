"""甘特图组件 — QPainter 自定义绘制"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

import ui_pyside6.theme as theme


class GanttView(QWidget):
    """生产计划甘特图 — QPainter 自定义绘制"""

    ROW_HEIGHT = 32
    LABEL_WIDTH = 200
    HEADER_HEIGHT = 40
    GRID_COLOR = QColor("#e0e0e0")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._colors = [
            theme.PRIMARY, theme.ACCENT_GREEN, theme.ACCENT_ORANGE,
            theme.ACCENT_CYAN, theme.ACCENT_RED, theme.ACCENT_PURPLE,
        ]
        self._max_hours = 48
        self._bg_color = QColor("#ffffff")

    def set_items(self, items: list[dict]):
        self._items = items
        self._max_hours = max((i.get("duration", 1) + i.get("start", 0) for i in items), default=48)
        self._max_hours = max(self._max_hours, 24)
        # 向上取整到 12 的倍数
        self._max_hours = ((self._max_hours + 11) // 12) * 12
        self.update()

    def clear(self):
        self._items = []
        self._max_hours = 48
        self.update()

    def load_from_plans(self, plans: list[dict]):
        items = []
        for i, plan in enumerate(plans):
            hours = plan.get("runs", 1) * plan.get("parallels", 1) * 2
            items.append({
                "name": plan.get("product_name", f"计划#{plan.get('id', i)}"),
                "start": 0,
                "duration": hours,
                "color": self._colors[i % len(self._colors)],
            })
        self.set_items(items)

    def minimumSizeHint(self):
        w = self.LABEL_WIDTH + self._max_hours * 12
        h = self.HEADER_HEIGHT + len(self._items) * self.ROW_HEIGHT + 10
        return __import__("PySide6.QtCore").QtCore.QSize(max(w, 400), max(h, 200))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        painter.fillRect(self.rect(), self._bg_color)

        if not self._items:
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return

        # 计算时间轴比例
        total_w = self.width() - self.LABEL_WIDTH - 10
        if total_w < 50:
            return
        px_per_hour = total_w / self._max_hours

        # 绘制时间刻度
        painter.setPen(QPen(QColor("#666666"), 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for h in range(0, self._max_hours + 1, 12):
            x = self.LABEL_WIDTH + h * px_per_hour
            painter.drawText(int(x - 15), 5, 30, 15, Qt.AlignmentFlag.AlignCenter, f"{h}h")
            # 垂直网格线
            painter.setPen(QPen(self.GRID_COLOR, 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(x), self.HEADER_HEIGHT, int(x), self.height())
            painter.setPen(QPen(QColor("#666666"), 1))

        # 绘制行
        for row, item in enumerate(self._items):
            y = self.HEADER_HEIGHT + row * self.ROW_HEIGHT

            # 水平网格线
            painter.setPen(QPen(self.GRID_COLOR, 1))
            painter.drawLine(self.LABEL_WIDTH, y, self.width(), y)

            # 标签
            painter.setPen(QColor("#333333"))
            label_rect = QRectF(5, y, self.LABEL_WIDTH - 10, self.ROW_HEIGHT)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item["name"])

            # 条形
            start_x = self.LABEL_WIDTH + item.get("start", 0) * px_per_hour
            bar_w = max(item.get("duration", 1) * px_per_hour, 4)
            bar_h = self.ROW_HEIGHT - 6
            bar_y = y + 3
            color = item.get("color", theme.PRIMARY)
            painter.fillRect(QRectF(start_x, bar_y, bar_w, bar_h), color)

            # 时长文字
            painter.setPen(QColor("#ffffff"))
            if bar_w > 40:
                dur_text = f"{item.get('duration', 0):.0f}h"
                painter.drawText(QRectF(start_x + 2, bar_y, bar_w - 4, bar_h),
                                 Qt.AlignmentFlag.AlignCenter, dur_text)

        painter.end()

    def _on_theme_changed(self):
        pass

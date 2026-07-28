"""Flow Layout — 自动换行的布局，窗口缩小时自动折行"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QStyle


class FlowLayout(QLayout):
    """水平排列 item，空间不足时自动折行"""

    def __init__(self, parent=None, margin: int = -1, h_spacing: int = -1, v_spacing: int = -1):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self) -> int:
        if self._h_spacing >= 0:
            return self._h_spacing
        parent = self.parent()
        if parent is not None:
            s = parent.style()  # type: ignore[attr-defined]
            if s is not None:
                return s.pixelMetric(QStyle.PixelMetric.PM_LayoutHorizontalSpacing, None, parent)  # type: ignore[attr-defined,no-any-return]
        return -1

    def verticalSpacing(self) -> int:
        if self._v_spacing >= 0:
            return self._v_spacing
        parent = self.parent()
        if parent is not None:
            s = parent.style()  # type: ignore[attr-defined]
            if s is not None:
                return s.pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing, None, parent)  # type: ignore[attr-defined,no-any-return]
        return -1

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        h_space = self.horizontalSpacing() if self._h_spacing >= 0 else 0
        v_space = self.verticalSpacing() if self._v_spacing >= 0 else 0

        for item in self._items:
            wid = item.widget()
            if wid and not wid.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + h_space
            if next_x - 1 > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + v_space
                next_x = x + hint.width() + h_space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()

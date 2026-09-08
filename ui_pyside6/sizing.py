"""控件尺寸自适应工具 — 只处理 Qt `sizeHint` 覆盖不到的场景。

Qt 自带的 `sizeHint()` 已包含最宽内容与按钮（实测 `QDoubleSpinBox`≈96px、
`QComboBox`≈90px），这类控件**删掉 `setFixedWidth` 即可**，不要用本模块包装。
本模块只解决两类 Qt 算不准的情况：

1. `QLineEdit` — `sizeHint()` 不随 placeholder / 预期输入长度变化；
2. `QLabel` — 长文本应省略号截断，而不是把父布局撑宽。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QSizePolicy, QWidget

# 输入框左右内边距 + 边框 + 光标余量（与 theme.py 的 QLineEdit padding: 4px 8px 对齐）
_LINE_EDIT_CHROME_PX = 28


def text_width(widget: QWidget, text: str) -> int:
    """按控件当前字体测量文本宽度（随全局字号缩放自动变化）。"""
    return widget.fontMetrics().horizontalAdvance(text)


def fit_line_edit_width(edit: QLineEdit, sample: str = "", *, max_scale: float = 1.8) -> int:
    """按样本文本（默认 placeholder）定宽：最小宽贴合内容，最大宽限制拉伸。

    只设最小宽会让 QLineEdit 在工具栏里横向撑满；只设固定宽又会被字体放大截断。
    这里两者都给，宽度随字号缩放，返回最小宽。样本文本为空时不改动，返回 0。
    """
    probe = sample or edit.placeholderText() or edit.text()
    if not probe:
        return 0
    width = text_width(edit, probe) + _LINE_EDIT_CHROME_PX
    edit.setMinimumWidth(width)
    edit.setMaximumWidth(int(width * max_scale))
    return width


def elide_label(label: QLabel, max_width: int) -> None:
    """按最大宽度省略文本，完整文本保留在 tooltip。

    重复调用安全：首次调用时记住原始文本，之后始终基于原文重新省略，
    避免「省略后的文本再省略」导致信息不可逆丢失。
    """
    stored = label.property("_full_text")
    if stored is None:
        stored = label.text()
        label.setProperty("_full_text", stored)
    full = str(stored)
    elided = label.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, max_width)
    label.setText(elided)
    if elided != full:
        label.setToolTip(full)


class ElidedLabel(QLabel):
    """随宽度自动省略的 QLabel —— 用于右对齐的长状态文字。

    普通 QLabel 被布局挤压时直接裁掉文字且无提示；本控件按可用宽度省略，
    完整文本放 tooltip，宽度变化时自动重算。

    尺寸策略：sizeHint 给足全文宽度（有空间时完整显示），minimumSizeHint 给 0
    （空间不足时允许被压缩到任意宽度），两者之差正是「可省略」的空间。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._apply_elide()

    def setText(self, text: str) -> None:
        self._full_text = text
        self.updateGeometry()
        self._apply_elide()

    def fullText(self) -> str:
        return self._full_text

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._full_text), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(self.width(), 0))
        super().setText(elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")

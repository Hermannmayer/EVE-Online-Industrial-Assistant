"""部分启动对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/partial_start_dialog.py`：
选择本次启动几条并行产线（1 .. total-1），其余留在「待生产」行里。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["PartialStartBridge", "PartialStartQmlDialog"]

_QML_FILE = "dialogs/PartialStartDialog.qml"


class PartialStartBridge(DialogBridge):
    """部分启动的 QML 后端。"""

    valueChanged = Signal()

    def __init__(self, product_name: str, total_lines: int) -> None:
        super().__init__()
        self._total = max(int(total_lines), 2)
        self._lines = self._total - 1
        self._product = str(product_name)
        self.set_title("部分启动")

    tipText = Property(
        str,
        lambda self: f"「{self._product}」共 {self._total} 条并行产线，本次启动几条？",
        constant=True,
    )
    #: 可选上限（其余留在待生产行里）
    maxLines = Property(int, lambda self: self._total - 1, constant=True)
    lines = Property(int, lambda self: self._lines, notify=valueChanged)
    summaryText = Property(
        str,
        lambda self: (
            f"启动 {self._lines} 条，剩余 {self._total - self._lines} 条留在「待生产」行里；"
            f"材料只按本次启动的 {self._lines} 条扣减"
        ),
        notify=valueChanged,
    )

    @Slot(int)
    def setLines(self, value: int) -> None:
        clamped = max(1, min(self._total - 1, int(value)))
        if clamped != self._lines:
            self._lines = clamped
            self.valueChanged.emit()

    def lines_value(self) -> int:
        """给 Python 侧读（`lines` 是 Property，mypy 读不出 int）。"""
        return self._lines


class PartialStartQmlDialog(QmlDialog):
    """QML 版「部分启动」。对外 API 与 Widgets 版一致（`exec()` + `lines()`）。"""

    def __init__(self, product_name: str, total_lines: int, parent: Any = None) -> None:
        bridge = PartialStartBridge(product_name, total_lines)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(360, 220))

    def lines(self) -> int:
        return self.bridge.lines_value()  # type: ignore[no-any-return]

"""取值对话框 —— `QInputDialog` 的 QML 替代（阶段 4b）。

原先代码里散着 `QInputDialog.getItem/getInt/getDouble`：它们弹的是**原生 Qt 窗口**，
样式完全不跟主题，而且是"从 QML 页面里冒出来的 Widgets 窗口"里最扎眼的一类
（连 `QMessageBox` 都不如 —— 后者至少有个统一收敛的计划）。

静态方法刻意**照抄 Qt 的签名与返回值形状**（`(value, ok)` 元组），
所以调用方只需要把 `QInputDialog.getItem(...)` 换成 `InputQmlDialog.get_item(...)`，
其余一行不改。

三种形态共用一个桥：`mode` 决定 QML 里显示哪个输入控件。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtWidgets import QDialog

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["InputBridge", "InputQmlDialog", "MODE_CHOICE", "MODE_DOUBLE", "MODE_INT", "MODE_TEXT"]

_QML_FILE = "dialogs/InputDialog.qml"

MODE_TEXT = "text"
MODE_INT = "int"
MODE_DOUBLE = "double"
MODE_CHOICE = "choice"


class InputBridge(DialogBridge):
    """一个取值对话框的后端。`mode` 决定取的是文本 / 整数 / 小数 / 下拉选中项。"""

    valueChanged = Signal()

    def __init__(
        self,
        title: str,
        label: str,
        mode: str,
        *,
        text: str = "",
        value: float = 0.0,
        minimum: float = 0.0,
        maximum: float = 100.0,
        decimals: int = 1,
        step: float = 1.0,
        choices: list[str] | None = None,
        choice_index: int = 0,
    ) -> None:
        super().__init__()
        self.set_title(title)
        self._label = label
        self._mode = mode
        self._text = text
        self._value = float(value)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._decimals = int(decimals)
        self._step = float(step)
        self._choices = list(choices or [])
        self._choice_index = max(0, int(choice_index))
        #: 点「确定」那一刻定格的返回值；取消则保持 None
        self._result: str | float | int | None = None

    # ── QML 读的属性 ──────────────────────────────────────────

    @Property(str, constant=True)
    def label(self) -> str:
        return self._label

    @Property(str, constant=True)
    def mode(self) -> str:
        return self._mode

    @Property(str, notify=valueChanged)
    def text(self) -> str:
        return self._text

    @Property(float, notify=valueChanged)
    def value(self) -> float:
        return self._value

    @Property(float, constant=True)
    def minimum(self) -> float:
        return self._minimum

    @Property(float, constant=True)
    def maximum(self) -> float:
        return self._maximum

    @Property(int, constant=True)
    def decimals(self) -> int:
        return self._decimals

    @Property(float, constant=True)
    def stepSize(self) -> float:
        return self._step

    @Property(list, constant=True)
    def choices(self) -> list[str]:
        return list(self._choices)

    @Property(int, notify=valueChanged)
    def choiceIndex(self) -> int:
        return self._choice_index

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(str)
    def setText(self, text: str) -> None:
        self._text = str(text)
        self.valueChanged.emit()

    @Slot(float)
    def setValue(self, value: float) -> None:
        self._value = float(value)
        self.valueChanged.emit()

    @Slot(int)
    def setChoiceIndex(self, index: int) -> None:
        if not 0 <= index < len(self._choices):
            return
        self._choice_index = index
        self.valueChanged.emit()

    @Slot()
    def accept(self) -> None:
        """定格返回值再关窗。**先定格再 emit** —— 宿主收到 `accepted` 就会 `exec()` 返回，
        读取方在 `exec()` 之后立刻取值，这里晚一步就是 None。"""
        if self._mode == MODE_CHOICE:
            self._result = self._choices[self._choice_index] if self._choices else ""
        elif self._mode == MODE_INT:
            self._result = int(round(self._value))
        elif self._mode == MODE_DOUBLE:
            self._result = float(self._value)
        else:
            self._result = self._text
        self.accepted.emit()

    # ── 给 Python 调用方取值 ──────────────────────────────────

    def text_value(self) -> str:
        return str(self._result or "")

    def number(self) -> float:
        return float(self._result or 0.0)

    def integer(self) -> int:
        return int(self._result or 0)

    def value_now(self) -> float:
        """当前输入值（不等点确定）。

        给 Python 侧读的普通方法：直接读 `self.value` 在 mypy 眼里是 `Property`
        描述符而不是 float（PySide 的桩没把描述符协议建模出来），同
        `PlanTableBridge.scroll_position` 的理由。
        """
        return self._value


class InputQmlDialog(QmlDialog):
    """QML 版取值对话框。静态方法对齐 `QInputDialog` 的签名与 `(value, ok)` 返回值。"""

    def __init__(self, bridge: InputBridge, parent: Any = None, size: tuple[int, int] = (440, 210)) -> None:
        super().__init__(_QML_FILE, bridge, parent=parent, size=size)
        self._input_bridge = bridge

    @classmethod
    def _ask(cls, bridge: InputBridge, parent: Any, size: tuple[int, int]) -> tuple[InputBridge, bool]:
        """开一次对话框，返回（桥, 是否点了确定）。"""
        dlg = cls(bridge, parent=parent, size=size)
        return bridge, dlg.exec() == int(QDialog.DialogCode.Accepted)

    @staticmethod
    def get_text(parent: Any, title: str, label: str, text: str = "") -> tuple[str, bool]:
        bridge, ok = InputQmlDialog._ask(InputBridge(title, label, MODE_TEXT, text=text), parent, (440, 200))
        return (bridge.text_value(), ok)

    @staticmethod
    def get_int(
        parent: Any,
        title: str,
        label: str,
        value: int = 0,
        minimum: int = -2147483647,
        maximum: int = 2147483647,
        step: int = 1,
    ) -> tuple[int, bool]:
        bridge = InputBridge(
            title,
            label,
            MODE_INT,
            value=float(value),
            minimum=float(minimum),
            maximum=float(maximum),
            step=float(step),
        )
        bridge, ok = InputQmlDialog._ask(bridge, parent, (440, 200))
        return (bridge.integer(), ok)

    @staticmethod
    def get_double(
        parent: Any,
        title: str,
        label: str,
        value: float = 0.0,
        minimum: float = -2147483647.0,
        maximum: float = 2147483647.0,
        decimals: int = 1,
    ) -> tuple[float, bool]:
        """默认 `decimals=1` 是**照抄 `QInputDialog.getDouble` 的默认值**，不是随便定的：
        原调用点没传该参数，改成 2 会静默改变实际存进库的数值。"""
        bridge = InputBridge(
            title,
            label,
            MODE_DOUBLE,
            value=float(value),
            minimum=float(minimum),
            maximum=float(maximum),
            decimals=int(decimals),
        )
        bridge, ok = InputQmlDialog._ask(bridge, parent, (440, 200))
        return (bridge.number(), ok)

    @staticmethod
    def get_item(parent: Any, title: str, label: str, items: list[str], current: int = 0) -> tuple[str, bool]:
        bridge = InputBridge(title, label, MODE_CHOICE, choices=list(items), choice_index=int(current))
        bridge, ok = InputQmlDialog._ask(bridge, parent, (440, 220))
        return (bridge.text_value(), ok)

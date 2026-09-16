"""批量设置 ME/TE 对话框的桥（批次 7.3）。

对照原版 `ui_pyside6/views/industry/plan_table.py::_batch_set_me_te` 里那一整块
手搭的 `QDialog`（两个 `QSlider` ↔ 两个 `QSpinBox` 双向联动 + 手写 QSS + 一条
主题监听器）：

    ME 0..10 / TE 0..20，各有一根滑杆与一个数字框，**两者双向联动**；
    首行若已绑产线，还要多一句「此处只影响未绑定的产线」的说明。

QSS 与 `add_theme_listener` 随 Widgets 一起退役 —— 配色由 QML 侧读 `Theme`
（属性绑定自动重绘），桥只负责两个 int 的取值与范围，不碰画的事。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtWidgets import QDialog

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["MeTeBridge", "MeTeQmlDialog"]

_QML_FILE = "dialogs/MeTeDialog.qml"

#: 与原版 `QSlider.setRange(0, 10)` / `setRange(0, 20)` 逐字一致
ME_MIN, ME_MAX = 0, 10
TE_MIN, TE_MAX = 0, 20


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


class MeTeBridge(DialogBridge):
    """ME/TE 两个取值的 QML 后端。"""

    #: 任一取值变化 —— QML 侧靠它把两个控件一起回填（见 `MeTeDialog.qml` 的 Connections）
    valuesChanged = Signal()

    def __init__(self, me: int, te: int, *, hint: str = "") -> None:
        super().__init__()
        self.set_title("设置蓝图等级")
        self._me = _clamp(me, ME_MIN, ME_MAX)
        self._te = _clamp(te, TE_MIN, TE_MAX)
        self._hint = str(hint)

    # ── QML 读的属性 ──────────────────────────────────────────

    @Property(int, notify=valuesChanged)
    def meValue(self) -> int:
        return self._me

    @Property(int, notify=valuesChanged)
    def teValue(self) -> int:
        return self._te

    @Property(int, constant=True)
    def meMin(self) -> int:
        return ME_MIN

    @Property(int, constant=True)
    def meMax(self) -> int:
        return ME_MAX

    @Property(int, constant=True)
    def teMin(self) -> int:
        return TE_MIN

    @Property(int, constant=True)
    def teMax(self) -> int:
        return TE_MAX

    #: 已绑产线时的说明；空串 = 不显示（原版是按 `bound_blueprint_ids` 决定加不加 QLabel）
    @Property(str, constant=True)
    def hint(self) -> str:
        return self._hint

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(int)
    def setMe(self, value: int) -> None:
        clamped = _clamp(value, ME_MIN, ME_MAX)
        if clamped != self._me:
            self._me = clamped
            self.valuesChanged.emit()

    @Slot(int)
    def setTe(self, value: int) -> None:
        clamped = _clamp(value, TE_MIN, TE_MAX)
        if clamped != self._te:
            self._te = clamped
            self.valuesChanged.emit()

    # ── 给 Python 调用方取值 ──────────────────────────────────

    def result(self) -> tuple[int, int]:
        """确定那一刻的两个值。取消时调用方不看它（见 `ask`）。"""
        return (self._me, self._te)


class MeTeQmlDialog(QmlDialog):
    """QML 版「设置蓝图等级」。"""

    def __init__(self, bridge: MeTeBridge, parent: Any = None) -> None:
        super().__init__(_QML_FILE, bridge, parent=parent, size=(400, 280))

    @staticmethod
    def ask(parent: Any, me: int, te: int, *, hint: str = "") -> tuple[int, int] | None:
        """开一次对话框。返回 `(me, te)`；取消 / Esc / 关闭按钮一律 `None`。

        `bridge` 与 `dlg` 都留在局部变量里直到取完值：桥是对话框的子对象
        （`QmlDialog.__init__` 里的 `bridge.setParent(self)`），对话框先一步被回收
        就会留下一个悬空包装器 —— 见 `message_dialog.FMessageDialog` 里记的那次
        `Fatal Python error: Aborted`。
        """
        bridge = MeTeBridge(me, te, hint=hint)
        dlg = MeTeQmlDialog(bridge, parent=parent)
        if dlg.exec() != int(QDialog.DialogCode.Accepted):
            return None
        return bridge.result()

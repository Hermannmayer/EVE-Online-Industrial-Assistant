"""发明结果回填对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/invention_outcome_dialog.py`：
发明是概率作业，期望值只适合事前估算，完成后必须由用户回填实际结果 ——
否则产出记不准、后续成本与库存全错（见 `docs/dev/flows.md`「科研计划」）。

`outcome()` 与 Widgets 版同义：确认 → 实际流程数（可为 0）；取消 → None。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["InventionOutcomeBridge", "InventionOutcomeQmlDialog"]

_QML_FILE = "dialogs/InventionOutcomeDialog.qml"


class InventionOutcomeBridge(DialogBridge):
    """发明结果回填的 QML 后端。"""

    valueChanged = Signal()

    def __init__(
        self,
        *,
        plan_name: str,
        expected_runs: int,
        attempts: int = 0,
        decryptor_name: str = "",
        runs_per_bpc: int = 0,
    ) -> None:
        super().__init__()
        self._plan_name = str(plan_name)
        self._expected = max(0, int(expected_runs))
        self._runs = self._expected
        self._actual: int | None = None
        self.set_title(f"发明结果回填 — {plan_name}")

        rows = [{"label": "产物:", "value": self._plan_name}]
        if runs_per_bpc:
            rows.append({"label": "每次成功产出:", "value": f"{runs_per_bpc} 流程"})
        if attempts:
            rows.append({"label": "计划尝试次数:", "value": str(attempts)})
        if decryptor_name:
            rows.append({"label": "解码器:", "value": decryptor_name})
        rows.append({"label": "期望产出:", "value": f"{self._expected} 流程（按成功率估算）"})
        self._rows = rows

    #: 只读信息行 [{label, value}]
    rows = Property(list, lambda self: list(self._rows), constant=True)
    expectedRuns = Property(int, lambda self: self._expected, constant=True)

    actualRuns = Property(int, lambda self: self._runs, notify=valueChanged)

    @Slot(int)
    def setActualRuns(self, value: int) -> None:
        clamped = max(0, min(1_000_000, int(value)))
        if clamped != self._runs:
            self._runs = clamped
            self.valueChanged.emit()

    @Property(str, notify=valueChanged)
    def hintText(self) -> str:
        """提示随实际产出实时变（失败 / 与期望差太多 / 正常）。"""
        runs = self._runs
        if runs <= 0:
            return "⚠ 发明失败：本次消耗的数据核心、解码器与输入蓝图流程不会退还，该计划将记为「0 流程」且不产出蓝图。"
        if self._expected and abs(runs - self._expected) > max(1, self._expected // 5):
            return f"⚠ 与期望值 {self._expected} 相差较大，确认游戏里实际就是这个数？"
        return f"成功后产出 {runs} 流程的蓝图拷贝；点击「确认并完成」写入库存。"

    @Slot()
    def markFailed(self) -> None:
        """「发明失败」：把实际产出置 0（材料与输入流程已被消耗，这是游戏事实）。"""
        self.setActualRuns(0)

    @Slot()
    def accept(self) -> None:
        self._actual = self._runs
        self.accepted.emit()

    def outcome(self) -> int | None:
        """用户确认的实际产出；取消 → None（与 Widgets 版同义）。"""
        return self._actual


class InventionOutcomeQmlDialog(QmlDialog):
    """QML 版「发明结果回填」。对外 API 与 Widgets 版一致。"""

    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        bridge = InventionOutcomeBridge(**kwargs)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(460, 320))

    def outcome(self) -> int | None:
        return self.bridge.outcome()  # type: ignore[no-any-return]

"""发明结果回填对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/invention_outcome_dialog.py`：
发明是概率作业，期望值只适合事前估算，完成后必须由用户回填实际结果 ——
否则产出记不准、后续成本与库存全错（见 `docs/dev/flows.md`「科研计划」）。

**回填的是「成功产线数」**：游戏里每条产线独立成功/失败，成功一次产一张 T2 BPC。
实际产出流程数 = 成功数 × 每次成功的流程数。以前问「实际产出流程数」，入库只能记成
「1 张 BPC × 总流程」，与游戏里拿到的「N 张各 R 流程」不符。

`outcome()` → `(实际产出流程数, BPC 张数)`；取消 → None。
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
        expected_runs: int = 0,
        expected_bpc: int = 0,
        attempts: int = 0,
        decryptor_name: str = "",
        runs_per_bpc: int = 0,
    ) -> None:
        super().__init__()
        self._plan_name = str(plan_name)
        self._runs_per_bpc = max(0, int(runs_per_bpc))
        self._attempts = max(0, int(attempts))
        self._expected_bpc = max(0, int(expected_bpc))
        self._expected_runs = max(0, int(expected_runs))
        self._successes = self._expected_bpc
        self._actual: tuple[int, int] | None = None
        self.set_title(f"发明结果回填 — {plan_name}")

        rows = [{"label": "产物:", "value": self._plan_name}]
        if self._runs_per_bpc:
            rows.append({"label": "每次成功产出:", "value": f"{self._runs_per_bpc} 流程"})
        if self._attempts:
            rows.append({"label": "本计划尝试次数:", "value": str(self._attempts)})
        if decryptor_name:
            rows.append({"label": "解码器:", "value": decryptor_name})
        rows.append({"label": "期望成功:", "value": f"约 {self._expected_bpc} 条产线（按成功率估算）"})
        self._rows = rows

    #: 只读信息行 [{label, value}]
    rows = Property(list, lambda self: list(self._rows), constant=True)
    attempts = Property(int, lambda self: self._attempts, constant=True)
    expectedBpc = Property(int, lambda self: self._expected_bpc, constant=True)
    expectedRuns = Property(int, lambda self: self._expected_runs, constant=True)
    runsPerBpc = Property(int, lambda self: self._runs_per_bpc, constant=True)

    def _actual_runs(self) -> int:
        """按成功数换算实际产出流程数（成功几次 × 每次流程）。"""
        return self._successes * self._runs_per_bpc

    successes = Property(int, lambda self: self._successes, notify=valueChanged)
    #: 只读展示：由成功数换算出来的实际产出流程数
    actualRuns = Property(int, lambda self: self._actual_runs(), notify=valueChanged)

    @Slot(int)
    def setSuccesses(self, value: int) -> None:
        upper = self._attempts if self._attempts > 0 else 1_000_000
        clamped = max(0, min(upper, int(value)))
        if clamped != self._successes:
            self._successes = clamped
            self.valueChanged.emit()

    @Property(str, notify=valueChanged)
    def hintText(self) -> str:
        """提示随回填实时变（失败 / 与期望差太多 / 正常）。"""
        if self._successes <= 0:
            return "⚠ 发明失败：本次消耗的数据核心、解码器与输入蓝图流程不会退还，该计划将记为「0 流程」且不产出蓝图。"
        if self._expected_bpc and abs(self._successes - self._expected_bpc) > max(1, self._expected_bpc // 5):
            return f"⚠ 与期望的 {self._expected_bpc} 条相差较大，确认游戏里实际就是这个数？"
        return (
            f"成功后产出 {self._successes} 张蓝图拷贝（每张 {self._runs_per_bpc} 流程，"
            f"共 {self._actual_runs()} 流程）；点击「确认并完成」写入库存。"
        )

    @Slot()
    def markFailed(self) -> None:
        """「发明失败」：把成功数置 0（材料与输入流程已被消耗，这是游戏事实）。"""
        self.setSuccesses(0)

    @Slot()
    def accept(self) -> None:
        self._actual = (self._actual_runs(), self._successes)
        self.accepted.emit()

    def outcome(self) -> tuple[int, int] | None:
        """(实际产出流程数, BPC 张数)；取消 → None。"""
        return self._actual


class InventionOutcomeQmlDialog(QmlDialog):
    """QML 版「发明结果回填」。"""

    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        bridge = InventionOutcomeBridge(**kwargs)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(460, 320))

    def outcome(self) -> tuple[int, int] | None:
        return self.bridge.outcome()  # type: ignore[no-any-return]

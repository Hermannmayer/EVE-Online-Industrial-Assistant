"""子项并行配置对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/child_parallel_dialog.py`：
只需设置每个子项的「并行产线数」，「每条流程」自动按 需求/(并行×单流程产出)
向上取整生成，总产出实时显示并校验是否覆盖母项需求。

**计算与校验逻辑一字未改**（`_compute_runs` / `_validate_row` 原样搬过来），
只是从「往 QTableWidget 塞 QSpinBox」换成「把每行算成视图模型 dict」。
保存仍走 `plan_repo.update_batch`（逐条 UPDATE parallels/runs）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["ChildParallelBridge", "ChildParallelQmlDialog"]

_QML_FILE = "dialogs/ChildParallelDialog.qml"


class ChildParallelBridge(DialogBridge):
    """子项并行配置的 QML 后端。"""

    rowsChanged = Signal()

    def __init__(self, plans: list[dict]) -> None:
        super().__init__()
        from services.industry_dialog_queries import get_child_parallel_data

        self._all_plans = plans
        self._plans = [p for p in plans if int(p.get("sub_level") or 0) > 0]
        self._demand: dict[int, int] = {}
        self._output_per_run: dict[int, int] = {}
        self._durations: dict[int, str] = {}
        self._demand, self._output_per_run, self._durations = get_child_parallel_data(
            get_container().db, plans, self._plans
        )
        #: 每行：{planId, name, duration, demand, output, runs, check, checkToken, parallels}
        self._rows: list[dict] = []
        self._can_accept = True
        self.set_title("子项并行配置")
        self._build_rows()

    tipText = Property(
        str,
        lambda self: (
            "只需设置每个子项的「并行产线数」；「每条流程」自动生成以覆盖母项需求，"
            "总产出（并行×流程×单流程产出）会实时显示。"
        ),
        constant=True,
    )
    headers = Property(
        list, lambda self: ["子项", "母项需求", "总产出", "并行产线数", "每条流程(自动)", "校验"], constant=True
    )
    rows = Property(list, lambda self: self._rows, notify=rowsChanged)
    canAccept = Property(bool, lambda self: self._can_accept, notify=rowsChanged)

    def _build_rows(self) -> None:
        from services.industry_dialog_queries import get_item_name

        self._rows = []
        for plan in self._plans:
            pid = plan["product_type_id"]
            name = get_item_name(get_container().db, pid)
            demand = self._demand.get(pid, 0)
            parallels = int(plan.get("parallels") or 1)
            per_run = self._output_per_run.get(pid, 1)
            runs = self._compute_runs(parallels, per_run, demand)
            self._rows.append(
                {
                    "planId": plan["id"],
                    "name": name,
                    "duration": self._durations.get(pid, ""),
                    "demand": demand,
                    "output": parallels * runs * per_run,
                    "runs": runs,
                    "parallels": parallels,
                    "check": "",
                    "checkToken": "",
                }
            )
        self._validate()

    # ── 计算 / 校验（与原版逐行一致）─────────────────────────

    @staticmethod
    def _compute_runs(parallels: int, per_run: int, demand: int) -> int:
        """自动生成每条流程数：向上取整覆盖母项需求，至少 1。"""
        if demand <= 0:
            return 1
        per = max(per_run, 1) * max(parallels, 1)
        return max(1, -(-demand // per))  # ceil(demand / per)

    def _per_run(self, row: dict) -> int:
        plan = next((p for p in self._plans if p["id"] == row["planId"]), None)
        pid = int((plan or {}).get("product_type_id") or 0)
        return int(self._output_per_run.get(pid, 1))

    def _validate(self) -> None:
        ok = True
        for row in self._rows:
            per_run = self._per_run(row)
            total = row["parallels"] * row["runs"] * per_run
            row["output"] = total
            demand = row["demand"]
            if demand and total < demand:
                row["check"] = f"不足（还差 {demand - total:,}）"
                row["checkToken"] = "ACCENT_RED"
                ok = False
            else:
                row["check"] = "✓"
                row["checkToken"] = "ACCENT_GREEN"
        self._can_accept = ok

    @Slot(int, int)
    def setParallels(self, index: int, value: int) -> None:
        """并行产线数变化 → 该行重新生成流程数，再整体重校验。"""
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        row["parallels"] = max(1, min(1000, int(value)))
        row["runs"] = self._compute_runs(row["parallels"], self._per_run(row), row["demand"])
        self._validate()
        self.rowsChanged.emit()

    @Slot()
    def accept(self) -> None:
        if not self._can_accept:
            return
        updates = []
        for row in self._rows:
            updates.append((row["planId"], {"parallels": row["parallels"], "runs": row["runs"]}))
            plan = next((p for p in self._plans if p["id"] == row["planId"]), None)
            if plan is not None:
                plan["parallels"] = row["parallels"]
                plan["runs"] = row["runs"]
        get_container().plan_repo.update_batch(updates)
        self.accepted.emit()

    def row_count(self) -> int:
        return len(self._rows)


class ChildParallelQmlDialog(QmlDialog):
    """QML 版「子项并行配置」。`ChildParallelDialog(plans, parent)` 的调用方原样可用。"""

    def __init__(self, plans: list[dict], parent: Any = None) -> None:
        super().__init__(_QML_FILE, ChildParallelBridge(plans), parent=parent, size=(820, 520))

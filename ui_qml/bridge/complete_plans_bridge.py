"""下线确认对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/complete_plans_dialog.py` 里的
`CompletePlansDialog`：展示待下线清单 + 选产出机库。

**产出量与流水号的计算留在 `complete_plans_dialog` 的既有函数里**
（`complete_plans` / `complete_one_plan` / `_ask_invention_outcome` 都是模块级业务函数，
不随对话框迁移），本桥只负责把它算好的清单画出来并回传选中的机库。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["CompletePlansBridge", "CompletePlansQmlDialog"]

_QML_FILE = "dialogs/CompletePlansDialog.qml"


class CompletePlansBridge(DialogBridge):
    """下线确认的 QML 后端。"""

    selectionChanged = Signal()

    def __init__(
        self,
        plans: list[dict],
        hangars: list[dict],
        default_hangar_id: int | None,
        *,
        count_text: str,
        rows: list[dict],
        total_qty: int,
    ) -> None:
        super().__init__()
        self._plans = plans
        self._hangars = [{"id": -1, "name": "不自动入库"}] + [dict(h) for h in hangars]
        self._rows = rows
        self._total_qty = int(total_qty)
        self.set_title("下线确认")

        index = -1
        if default_hangar_id and default_hangar_id > 0 and any(h["id"] == default_hangar_id for h in self._hangars):
            index = next(i for i, h in enumerate(self._hangars) if h["id"] == default_hangar_id)
        if index < 0 and len(self._hangars) > 1:
            index = 1  # 第一个真实机库
        self._hangar_index = max(index, 0)
        self._count_text = count_text
        self._plans = plans

    # ── 只读展示 ──

    tipText = Property(
        str,
        lambda self: "以下「待下线」计划将被下线（产出成品入库，不可逆）：",
        constant=True,
    )
    #: 列标题（与 Widgets 版一致）
    headers = Property(list, lambda self: ["产物", "流程", "产出量", "当前机库"], constant=True)
    #: 清单行 [{name, runs, qty, deposit}]
    rows = Property(list, lambda self: list(self._rows), constant=True)
    summaryText = Property(
        str,
        lambda self: f"{self._count_text}，产出 {self._total_qty:,} 件",
        constant=True,
    )

    # ── 产出机库 ──

    hangarNames = Property(list, lambda self: [h["name"] for h in self._hangars], constant=True)
    hangarIndex = Property(int, lambda self: self._hangar_index, notify=selectionChanged)

    @Slot(int)
    def setHangarIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars) and index != self._hangar_index:
            self._hangar_index = index
            self.selectionChanged.emit()

    def selected_hangar_id(self) -> int:
        """选中的机库 id（-1 = 不自动入库）。"""
        if 0 <= self._hangar_index < len(self._hangars):
            return int(cast(int, self._hangars[self._hangar_index]["id"]))
        return -1


class CompletePlansQmlDialog(QmlDialog):
    """QML 版「下线确认」。对外 API 与 Widgets 版一致（`exec()` + `selected_hangar_id()`）。"""

    def __init__(
        self,
        plans: list[dict],
        hangars: list[dict],
        default_hangar_id: int | None,
        parent: Any = None,
    ) -> None:
        from services import plan_execution

        hangar_by_id = {h["id"]: h["name"] for h in hangars}
        rows: list[dict] = []
        total_qty = 0
        for plan in plans:
            name = str(plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}")
            runs = int(plan.get("runs") or 1)
            parallels = int(plan.get("parallels") or 1)
            qty = runs * parallels * plan_execution.output_per_run(plan.get("product_type_id") or 0)
            total_qty += qty
            deposit = plan.get("deposit_hangar_id")
            # 机库 id 在表里查不到时也回落到「不自动入库」——
            # Widgets 版这里是 `str(None)`，界面上会直接显示「None」（顺带修掉）
            deposit_name = "不自动入库"
            if deposit and deposit > 0:
                deposit_name = hangar_by_id.get(deposit) or "不自动入库"
            rows.append(
                {
                    "name": name,
                    "runs": f"{parallels}X{runs}",
                    "qty": f"{qty:,}",
                    "deposit": deposit_name,
                }
            )

        bridge = CompletePlansBridge(
            plans,
            hangars,
            default_hangar_id,
            count_text=f"共 {len(plans)} 项计划",
            rows=rows,
            total_qty=total_qty,
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(640, 480))

    def selected_hangar_id(self) -> int:
        return self.bridge.selected_hangar_id()  # type: ignore[no-any-return]

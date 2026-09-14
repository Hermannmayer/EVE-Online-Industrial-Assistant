"""子项大规模产线并行对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/mass_parallel_dialog.py`：
按「可用产线数」或「目标工期」反推每个子项的并行数，先出预览表再落库。

两个分配算法是**纯函数**，原样搬到这里（`_compute_parallel_by_lines` 用最大余数法
按需求轮次权重分配、`_compute_parallel_by_duration` 按工期反推），单测直接打它们。
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "MassParallelBridge",
    "MassParallelQmlDialog",
    "compute_parallel_by_lines",
    "compute_parallel_by_duration",
]

_QML_FILE = "dialogs/MassParallelDialog.qml"

_MODES = [{"key": "lines", "label": "按可用产线数"}, {"key": "duration", "label": "按目标工期"}]


def compute_parallel_by_lines(subitems: list[dict], total_lines: int) -> list[dict]:
    """按可用产线数分配并行数（纯函数）。

    subitems: [{id, demand, per_run, ...}]；返回 [{id, parallels}]。
    每子项至少 1 条；剩余产线按需求轮次权重（最大余数法）分配。
    """
    n = len(subitems)
    if n == 0 or total_lines <= 0:
        return [{"id": s["id"], "parallels": 1} for s in subitems]
    weights = [max(1, math.ceil(s.get("demand", 1) / max(s.get("per_run", 1), 1))) for s in subitems]
    remaining = max(0, total_lines - n)  # 先保证每子项 1 条
    total_w = sum(weights)
    if total_w <= 0 or remaining <= 0:
        return [{"id": s["id"], "parallels": 1} for s in subitems]
    ratios = [w / total_w for w in weights]
    exact = [r * remaining for r in ratios]
    alloc = [int(e) for e in exact]
    leftover = remaining - sum(alloc)
    order = sorted(range(n), key=lambda i: exact[i] - alloc[i], reverse=True)
    for k in range(leftover):
        alloc[order[k % n]] += 1
    return [{"id": s["id"], "parallels": 1 + alloc[i]} for i, s in enumerate(subitems)]


def compute_parallel_by_duration(subitems: list[dict], target_days: int) -> list[dict]:
    """按目标工期反推并行数（纯函数）。

    subitems: [{id, duration_sec(单线总时长), ...}]；返回 [{id, parallels}]。
    parallels = max(1, ceil(duration_sec / (target_days × 86400))）。
    """
    target_secs = max(int(target_days), 1) * 86400
    result = []
    for item in subitems:
        duration = int(item.get("duration_sec") or 0)
        parallels = 1 if duration <= 0 else max(1, math.ceil(duration / target_secs))
        result.append({"id": item["id"], "parallels": parallels})
    return result


class MassParallelBridge(DialogBridge):
    """子项大规模并行的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, plans: list[dict]) -> None:
        super().__init__()
        from services.industry_dialog_queries import get_mass_parallel_data

        self._plans = [p for p in plans if int(p.get("sub_level") or 0) > 0]
        self._demand: dict[int, int] = {}
        self._per_run: dict[int, int] = {}
        self._duration: dict[int, int] = {}
        # 与 Widgets 版同一个查询：第三项就是**单线总时长的秒数**（按工期反推要用它）
        self._demand, self._per_run, self._duration = get_mass_parallel_data(get_container().db, plans, self._plans)

        self._mode_index = 0
        self._param = 10
        self._preview: list[dict] = []
        self._rows: list[dict] = []
        self._any_short = False
        self.set_title("子项大规模产线并行")

    # ── 选项 ──────────────────────────────────────────────────

    modes = Property(list, lambda self: [m["label"] for m in _MODES], constant=True)
    modeIndex = Property(int, lambda self: self._mode_index, notify=stateChanged)
    paramLabel = Property(str, lambda self: "产线数" if self._is_lines() else "目标工期", notify=stateChanged)
    paramSuffix = Property(str, lambda self: " 条产线" if self._is_lines() else " 天", notify=stateChanged)
    #: 上限随模式变（产线数 / 天数）—— **不能标 constant**，否则 QML 换模式后读到的还是旧值
    paramMax = Property(int, lambda self: self._param_max(), notify=stateChanged)
    paramValue = Property(int, lambda self: self._param, notify=stateChanged)

    def _is_lines(self) -> bool:
        return _MODES[self._mode_index]["key"] == "lines"

    def _param_max(self) -> int:
        """参数上限：产线数 1000 / 工期 3650 天（与 Widgets 版一致）。

        单独开一个方法而不是让 Property 里现算：`self.paramMax` 在类型层面是
        `Property` 描述符，直接参与 `min()` 过不了 mypy。
        """
        return 1000 if self._is_lines() else 3650

    @Slot(int)
    def setModeIndex(self, index: int) -> None:
        if 0 <= index < len(_MODES) and index != self._mode_index:
            self._mode_index = index
            self._param = 10  # 与 Widgets 版一致：换模式后参数回到 10
            self._preview = []
            self._rows = []
            self.stateChanged.emit()

    @Slot(int)
    def setParamValue(self, value: int) -> None:
        clamped = max(1, min(self._param_max(), int(value)))
        if clamped != self._param:
            self._param = clamped
            self.stateChanged.emit()

    # ── 预览 ──────────────────────────────────────────────────

    headers = Property(
        list, lambda self: ["子项", "母项需求", "当前产出", "调整后并行", "调整后产出", "校验"], constant=True
    )
    rows = Property(list, lambda self: self._rows, notify=stateChanged)
    hasPreview = Property(bool, lambda self: bool(self._preview), notify=stateChanged)
    anyShort = Property(bool, lambda self: self._any_short, notify=stateChanged)

    @Slot()
    def computePreview(self) -> None:
        if not self._plans:
            return
        subitems = [
            {
                "id": p["id"],
                "demand": self._demand.get(p["product_type_id"], 0),
                "per_run": self._per_run.get(p["product_type_id"], 1),
                "duration_sec": self._duration.get(p["product_type_id"], 0),
            }
            for p in self._plans
        ]
        if self._is_lines():
            self._preview = compute_parallel_by_lines(subitems, self._param)
        else:
            self._preview = compute_parallel_by_duration(subitems, self._param)

        from services.industry_dialog_queries import get_item_name

        par_by_id = {r["id"]: r["parallels"] for r in self._preview}
        rows: list[dict] = []
        any_short = False
        for plan in self._plans:
            pid = plan["product_type_id"]
            runs = int(plan.get("runs") or 1)
            parallels = par_by_id.get(plan["id"], 1)
            per_run = self._per_run.get(pid, 1)
            demand = self._demand.get(pid, 0)
            output = runs * parallels * per_run
            short = bool(demand and output < demand)
            any_short = any_short or short
            rows.append(
                {
                    "cells": [
                        cell(get_item_name(get_container().db, pid)),
                        cell(f"{demand:,}"),
                        cell(f"{runs * int(plan.get('parallels') or 1) * per_run:,}"),
                        cell(str(parallels)),
                        cell(f"{output:,}"),
                        cell(
                            "✓" if not short else f"不足（还差 {demand - output:,}）",
                            "ACCENT_RED" if short else "ACCENT_GREEN",
                        ),
                    ]
                }
            )

        self._rows = rows
        self._any_short = any_short
        self.stateChanged.emit()

    @Slot()
    def accept(self) -> None:
        """「确认应用」：没算过预览就不落库（QML 侧按钮也是禁用的，这里是兜底）。"""
        if not self._preview:
            self.set_error("请先点「计算预览」")
            return
        get_container().plan_repo.update_batch([(r["id"], {"parallels": r["parallels"]}) for r in self._preview])
        for result in self._preview:
            for plan in self._plans:
                if plan["id"] == result["id"]:
                    plan["parallels"] = result["parallels"]
                    break
        self.accepted.emit()


class MassParallelQmlDialog(QmlDialog):
    """QML 版「子项大规模产线并行」。`MassParallelDialog(plans, parent)` 的调用方原样可用。"""

    def __init__(self, plans: list[dict], parent: Any = None) -> None:
        super().__init__(_QML_FILE, MassParallelBridge(plans), parent=parent, size=(860, 560))

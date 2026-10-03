"""子项大规模产线并行对话框的桥（阶段 4）。

按「可用产线数」或「目标工期」反推每个子项的并行数，先出预览表再落库。

两个分配算法是**纯函数**（`compute_parallel_by_lines` 用最大余数法
按**净需求线·轮数**权重分配、`compute_parallel_by_duration` 按工期反推），单测直接打它们。
净需求口径与 `plan_rebuild.plan_net_runs` 同一真源（毛需求 − 母项材料机库里的成品库存），
校验也按「调整后产出 + 库存 ≥ 毛需求」判 —— 旧版按毛需求，库存已覆盖的子项会白占产线。
分配出的并行数是**上限**：每行的 `runs` 再由 `plan_net_runs` 按净缺口重排（零多余优先，
可能低于分配到的并行数），可写行的 `parallels` 与 `runs` **两列一起**写回。
**在产行完全只读**：不参与分配、预览显示库中现值、`accept` 也不写（口径同
`_finalize_runs`「已投产产线不砍流程」）。
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from services.plan_rebuild import plan_net_runs
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

#: 在产状态：这两个状态的行**完全只读**（`parallels` 与 `runs` 都不写、也不参与并行分配）—— 口径同
#: `services.plan_rebuild._LOCKED_RUNS_STATUSES`（「已投产产线不砍流程」）。
#: 为什么连 `parallels` 也不写：整批产出 = `parallels × runs × 单轮产出`，在产行的 `runs`
#: 冻死时改并行数照样把产出成倍放大（实测 346 冻结 runs=4、拖到 10 条 → 40 件，净缺口 12）。
_LOCKED_STATUSES = ("in_progress", "running")


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
        self._available: dict[int, int] = {}
        # 第三项是**单线总时长的秒数**（按工期反推要用它）；第四项是成品库存（净口径用）
        (
            self._demand,
            self._per_run,
            self._duration,
            self._available,
        ) = get_mass_parallel_data(get_container().db, plans, self._plans)
        #: 在产行（`runs` 冻结，只写 parallels）：plan id → bool
        self._locked = {
            int(p["id"]): (p.get("status") or "").lower() in _LOCKED_STATUSES for p in self._plans if p.get("id")
        }

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
        list,
        lambda self: ["子项", "毛需求", "库存", "净缺口", "当前产出", "调整后并行", "调整后产出", "校验"],
        constant=True,
    )
    rows = Property(list, lambda self: self._rows, notify=stateChanged)
    hasPreview = Property(bool, lambda self: bool(self._preview), notify=stateChanged)
    anyShort = Property(bool, lambda self: self._any_short, notify=stateChanged)

    @Slot()
    def computePreview(self) -> None:
        if not self._plans:
            return
        subitems = []
        for p in self._plans:
            if self._locked.get(p["id"]):
                continue  # 在产行只读：不参与并行分配（也别占线数预算）
            pid = p["product_type_id"]
            demand = self._demand.get(pid, 0)
            per_run = max(self._per_run.get(pid, 1), 1)
            available = self._available.get(pid, 0)
            _par, _runs, net_lines = plan_net_runs(demand, per_run, available, int(p.get("parallels") or 1))
            subitems.append(
                {
                    "id": p["id"],
                    #: 分配权重用**净需求线·轮数**（÷per_run 恰好是 net_lines，与 `_finalize_runs` 同口径）
                    "demand": net_lines * per_run,
                    "per_run": per_run,
                    "duration_sec": self._duration.get(pid, 0),
                }
            )
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
            per_run = self._per_run.get(pid, 1)
            demand = self._demand.get(pid, 0)
            available = self._available.get(pid, 0)
            locked = bool(self._locked.get(plan["id"]))
            if locked:
                # 在产：整行只读 —— 并行数与流程数都显示库中现值，accept 也不写
                # （整批产出 = parallels × runs × 单轮产出，只改并行数照样成倍放大产出）
                parallels = int(plan.get("parallels") or 1)
                runs = int(plan.get("runs") or 1)
            else:
                allocated = par_by_id.get(plan["id"], 1)
                # `parallels` = 「几条线同时做**同一批**活」（提并行数是为了缩短工期，不是多产出），
                # 所以 runs 必须按分配到的并行数**重排**：只改 parallels 会让整批产出放大 parallels 倍
                # （旧实现把 348 从 1 条提到 7 条 → 7×1360 = 9520，是净缺口 1360 的 7 倍）。
                # `allocated` 是上限：`plan_net_runs` 可能因「零多余优先」把并行数降得更低（照它的结果）。
                parallels, runs, _net_lines = plan_net_runs(demand, per_run, available, allocated)
            output = parallels * runs * per_run
            # 净口径：库存能顶掉的部分不用再排产线（旧版按毛需求判，永远显得不够）
            short = bool(demand and output + available < demand)
            gap = demand - available - output
            any_short = any_short or short
            if locked:
                # 在产行的缺口不是本对话框能修的（整行只读）—— 只标注，不阻断应用
                check_text = f"在产，并行/流程数均只读（还差 {gap:,}）" if short else "在产，并行/流程数均只读"
                check_token = "ACCENT_RED" if short else "ACCENT_YELLOW"
            else:
                check_text = "✓" if not short else f"不足（还差 {gap:,}）"
                check_token = "ACCENT_RED" if short else "ACCENT_GREEN"
            rows.append(
                {
                    "planId": plan["id"],
                    "parallels": parallels,
                    "runs": runs,
                    "locked": locked,
                    "cells": [
                        cell(get_item_name(get_container().db, pid)),
                        cell(f"{demand:,}"),
                        cell(f"{available:,}"),
                        cell(f"{max(0, demand - available):,}"),
                        # 「当前产出」= 调整前：库里的 runs × 库里的 parallels × 单轮产出
                        cell(f"{int(plan.get('runs') or 1) * int(plan.get('parallels') or 1) * per_run:,}"),
                        cell(str(parallels)),
                        cell(f"{output:,}"),
                        cell(check_text, check_token),
                    ],
                }
            )

        self._rows = rows
        self._any_short = any_short
        self.stateChanged.emit()

    @Slot()
    def accept(self) -> None:
        """「确认应用」：没算过预览就不落库（QML 侧按钮也是禁用的，这里是兜底）。

        **可写行的 `parallels` 与 `runs` 必须一起写**：`runs` 的语义是「每条产线的流程数」，
        整批产出 = `parallels × runs × 单轮产出`。只写 `parallels` 会把产出放大 `parallels` 倍
        （旧实现把 348 从 1 条提到 7 条 → `7×1360 = 9520`，是净缺口 1360 的 7 倍），
        与「并行只为缩短工期、不多造」冲突。

        **在产行（`in_progress`/`running`）不进写库集合** —— 整行只读，`parallels` 与 `runs`
        都不写（口径同 `plan_rebuild._LOCKED_RUNS_STATUSES`「已投产产线不砍流程」）。
        内存 plan 只对可写行同步。
        """
        if not self._preview:
            self.set_error("请先点「计算预览」")
            return
        updates = []
        for row in self._rows:
            if row.get("locked"):
                continue
            updates.append((row["planId"], {"parallels": row["parallels"], "runs": row["runs"]}))
            for plan in self._plans:
                if plan["id"] == row["planId"]:
                    plan["parallels"] = row["parallels"]
                    plan["runs"] = row["runs"]
                    break
        if updates:
            get_container().plan_repo.update_batch(updates)
        self.accepted.emit()


class MassParallelQmlDialog(QmlDialog):
    """QML 版「子项大规模产线并行」。`MassParallelDialog(plans, parent)` 的调用方原样可用。"""

    def __init__(self, plans: list[dict], parent: Any = None) -> None:
        super().__init__(_QML_FILE, MassParallelBridge(plans), parent=parent, size=(860, 560))

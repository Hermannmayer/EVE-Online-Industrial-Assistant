"""所需蓝图清单对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/blueprint_dialog.py`：
展开所有活跃计划的 BOM，列出蓝图需求与拥有情况（BPO 无限 / BPC 按可用流程），
三色状态：足够（绿）/ 不足（黄）/ 缺少（红）。

展示走通用的 `SummaryTableBridge`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Slot

from core.container import get_container
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell

__all__ = ["BlueprintRequirementsBridge", "BlueprintRequirementsQmlDialog"]

_COLUMNS = [
    {"title": "蓝图名称", "width": 0},
    {"title": "类型", "width": 70},
    {"title": "材料等级", "width": 90},
    {"title": "时间等级", "width": 90},
    {"title": "所需流程数", "width": 110},
    {"title": "可用流程数", "width": 110},
    {"title": "状态", "width": 80},
]


class BlueprintRequirementsBridge(SummaryTableBridge):
    """所需蓝图清单的 QML 后端。"""

    def __init__(self) -> None:
        super().__init__(title="所需蓝图清单", columns=[dict(c) for c in _COLUMNS])

    @Slot()
    def reload(self) -> None:
        from services.industry_dialog_queries import get_blueprint_requirements

        result = get_blueprint_requirements(get_container().db)
        if result["status"] == "no_active":
            self.set_content([], "没有活跃计划")
            return
        if result["status"] == "no_needed":
            self.set_content([], "没有蓝图需求")
            return

        needed = result["needed"]
        bp_inv = result["bp_inv"]

        rows: list[dict] = []
        for bp_tid, info in sorted(needed.items(), key=lambda x: x[1].get("name", str(x[0]))):
            inv = bp_inv.get(bp_tid, {})
            if inv.get("is_bpo"):
                bp_type, me, te = "BPO", str(inv.get("best_me", 0)), str(inv.get("best_te", 0))
                available, status, token = "无限", "足够", "ACCENT_GREEN"
            elif inv.get("available_runs", 0) >= info["needed_runs"]:
                avail_runs = int(inv.get("available_runs", 0))
                bp_type, me, te = "BPC", str(inv.get("best_me", 0)), str(inv.get("best_te", 0))
                available, status, token = f"{avail_runs:,}", "足够", "ACCENT_GREEN"
            elif inv.get("available_runs", 0) > 0:
                avail_runs = int(inv.get("available_runs", 0))
                bp_type, me, te = "BPC", str(inv.get("best_me", 0)), str(inv.get("best_te", 0))
                available, status, token = f"{avail_runs:,}", "不足", "ACCENT_YELLOW"
            else:
                bp_type, me, te = "—", "—", "—"
                available, status, token = "—", "缺少", "ACCENT_RED"

            rows.append(
                {
                    "cells": [
                        cell(info["name"]),
                        cell(bp_type),
                        cell(me),
                        cell(te),
                        cell(f"{info['needed_runs']:,}"),
                        cell(available),
                        cell(status, token),
                    ]
                }
            )

        # 计数口径必须与**行级分类**一致：BPO 的「可用流程数」是「无限」而不是 0，
        # 原 Widgets 版的 `available_runs <= 0` 会把 BPO 也算进「缺少」，
        # 于是状态行与表格里的绿字自相矛盾（顺带修掉）。
        def _bucket(bp_tid: int) -> str:
            inv = bp_inv.get(bp_tid, {})
            if inv.get("is_bpo"):
                return "enough"
            available = inv.get("available_runs", 0)
            if available <= 0:
                return "missing"
            return "enough" if available >= needed[bp_tid]["needed_runs"] else "insufficient"

        total = len(needed)
        buckets = [_bucket(bp_tid) for bp_tid in needed]
        missing = buckets.count("missing")
        insufficient = buckets.count("insufficient")
        enough = buckets.count("enough")

        self.set_content(
            rows,
            f"共 {total} 类蓝图，足够 {enough} 种，不足 {insufficient} 种，缺少 {missing} 种",
        )


class BlueprintRequirementsQmlDialog(SummaryTableQmlDialog):
    """QML 版「所需蓝图清单」。`BlueprintRequirementsDialog(parent)` 的调用方原样可用。

    只读查看器 → **非模态独立窗**（`modeless=True`），调用方用 `show()` 而非 `exec()`。
    """

    def __init__(self, parent: Any = None) -> None:
        super().__init__(BlueprintRequirementsBridge(), parent=parent, size=(900, 520), modeless=True)

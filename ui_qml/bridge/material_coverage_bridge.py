"""材料覆盖对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/inventory/material_coverage_dialog.py`：
以某个机库为材料机库的**活跃生产计划**聚合材料需求，展示 需求 / 现有 / 缺口，
缺口 > 0 的行标红。空态提示该机库未被任何计划用作材料机库。

展示复用通用的 `SummaryTableBridge`（与产出总表同一份），本类只负责算。

Widgets 版把空态做成**另起一个居中 QLabel**、表格同时留空；QML 版改用
`FSummaryTable` 自带的空态文案，少一个控件、也不会出现「空标签 + 空表格」两块空。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell

__all__ = ["MaterialCoverageBridge", "MaterialCoverageQmlDialog", "coverage_rows", "plans_summary"]

#: 列宽与 Widgets 版同口径（材料列吃满剩余空间）
_COLUMNS = [
    {"title": "材料", "width": 0},
    {"title": "需求", "width": 110},
    {"title": "现有", "width": 110},
    {"title": "缺口", "width": 110},
]

_STATUS_CN = {"pending": "待生产", "in_progress": "生产中", "ready": "待完成"}

_EMPTY_HINT = "该机库未被任何计划用作材料机库"


def plans_summary(plans: list[dict]) -> str:
    """顶部说明行：关联计划条数与名称列表（逐字对齐原 `_plans_summary`）。

    超过 6 条只列前 6 个再补一句总数 —— 原实现如此，避免这一行把表格挤下去。
    """
    if not plans:
        return "关联计划 0 条"
    names = []
    for plan in plans:
        status = plan.get("status", "")
        label = _STATUS_CN.get(status, status)
        names.append(f"「{plan.get('product_name') or plan.get('product_type_id', '')}」({label})")
    head = " | ".join(names[:6])
    if len(plans) > 6:
        head += f" 等 {len(plans)} 条计划"
    else:
        head += f" · 共 {len(plans)} 条计划"
    return head


def coverage_rows(rows: list[dict]) -> list[dict]:
    """聚合结果 → 单元格行。纯函数，便于单测。

    缺口 > 0 用强调红（对齐原 `CoverageModel` 的 `ForegroundRole`）；需求/现有/缺口
    一律千分位，与原 `f"{...:,}"` 同口径。
    """
    return [
        {
            "cells": [
                cell(row.get("name", "")),
                cell(f"{row['need']:,}"),
                cell(f"{row['owned']:,}"),
                cell(f"{row['missing']:,}", "ACCENT_RED" if (row.get("missing") or 0) > 0 else ""),
            ]
        }
        for row in rows
    ]


class MaterialCoverageBridge(SummaryTableBridge):
    """材料覆盖的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, hangar_id: int, hangar_name: str) -> None:
        super().__init__(title=f"材料覆盖 — {hangar_name}", columns=[dict(c) for c in _COLUMNS])
        self._hangar_id = int(hangar_id)
        self._has_plans = False

    @Property(str, notify=stateChanged)
    def emptyText(self) -> str:
        """空表提示随「有没有关联计划」变，覆盖基类那句通用的「没有数据」。"""
        return "没有数据" if self._has_plans else _EMPTY_HINT

    @Slot()
    def reload(self) -> None:
        """聚合该机库的材料需求（本地计算，无 IO，不必起线程）。"""
        from services.plan_execution import aggregate_material_requirements, get_plans_for_mat_hangar

        plans = get_plans_for_mat_hangar(self._hangar_id)
        self._has_plans = bool(plans)
        header = plans_summary(plans)

        if not plans:
            self.set_content([], "关联计划 0 条", header)
        else:
            rows = aggregate_material_requirements(plans, self._hangar_id)
            missing_kind = sum(1 for r in rows if (r.get("missing") or 0) > 0)
            missing_total = sum(int(r.get("missing") or 0) for r in rows)
            self.set_content(
                coverage_rows(rows),
                f"缺 {missing_kind} 种 / 共 {missing_total:,} 件",
                header,
            )
        # 放在最后：emptyText 的绑定要等 _has_plans 与内容都定下来再重算
        self.stateChanged.emit()


class MaterialCoverageQmlDialog(SummaryTableQmlDialog):
    """QML 版「材料覆盖」。`MaterialCoverageDialog(hangar_id, name, parent)` 的调用方原样可用。

    只读查看器 → **非模态独立窗**（`modeless=True`），调用方用 `show()` 而非 `exec()`。
    """

    def __init__(self, hangar_id: int, hangar_name: str, parent: Any = None) -> None:
        super().__init__(MaterialCoverageBridge(hangar_id, hangar_name), parent=parent, size=(640, 500), modeless=True)

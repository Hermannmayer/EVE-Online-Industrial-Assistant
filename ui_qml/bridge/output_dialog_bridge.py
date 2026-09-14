"""产出总表对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/output_dialog.py`：
每个计划展开 BOM 树，算产出数量/价值/利润，并标出材料溢出。
展示走通用的 `SummaryTableBridge`（只读表 + 状态行），颜色规则留在本类里。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Slot

from core.container import get_container
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell, fmt_isk

__all__ = ["OutputSummaryBridge", "OutputSummaryQmlDialog"]

_STATUS_MAP = {
    "pending": "待开始",
    "in_progress": "进行中",
    "running": "运行中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
    "cancelled": "已取消",
    "paused": "已暂停",
}

#: 列标题 → 宽度（0 = 吃满剩余空间）。与 Widgets 版的 Stretch + 首列自适应同口径。
_COLUMNS = [
    {"title": "计划名称", "width": 0},
    {"title": "产出物品", "width": 110},
    {"title": "计划数量", "width": 100},
    {"title": "产出价值", "width": 100},
    {"title": "成本", "width": 100},
    {"title": "利润", "width": 100},
    {"title": "利润率", "width": 80},
    {"title": "材料溢出", "width": 0},
    {"title": "状态", "width": 90},
]


class OutputSummaryBridge(SummaryTableBridge):
    """产出总表的 QML 后端。"""

    def __init__(self) -> None:
        super().__init__(title="产出总表", columns=[dict(c) for c in _COLUMNS])

    @Slot()
    def reload(self) -> None:
        from services.industry_dialog_queries import get_output_summary

        results = get_output_summary(get_container().db)
        if results is None:
            self.set_content([], "没有生产计划")
            return

        rows: list[dict] = []
        total_value = 0.0
        total_profit = 0.0
        overflow_plans = 0

        for result in results:
            profit = result["profit"]
            margin = result["margin_pct"]
            status_raw = result["status"]
            has_overflow = bool(result["has_overflow"])

            if has_overflow:
                overflow_plans += 1
            total_value += result["plan_value"]
            total_profit += profit

            profit_token = "ACCENT_GREEN" if profit > 0 else ("ACCENT_RED" if profit < 0 else "")
            status_token = {
                "completed": "ACCENT_GREEN",
                "done": "ACCENT_GREEN",
                "cancelled": "ACCENT_RED",
                "in_progress": "PRIMARY",
                "running": "PRIMARY",
                "ready": "ACCENT_ORANGE",
            }.get(status_raw, "")

            rows.append(
                {
                    "cells": [
                        cell(result["plan_name"]),
                        cell(result["product_type_id"]),
                        cell(f"{result['total_qty']:,}"),
                        cell(fmt_isk(result["plan_value"])),
                        cell(fmt_isk(result["material_cost"])),
                        cell(fmt_isk(profit), profit_token),
                        cell(f"{margin:.1f}%" if margin else "—"),
                        cell(result["overflow_text"], "ACCENT_ORANGE" if has_overflow else ""),
                        cell(_STATUS_MAP.get(status_raw, status_raw), status_token),
                    ]
                }
            )

        self.set_content(
            rows,
            f"共 {len(results)} 个计划，总产出价值 {fmt_isk(total_value)}，"
            f"总利润 {fmt_isk(total_profit)}，{overflow_plans} 个计划存在材料溢出",
        )


class OutputSummaryQmlDialog(SummaryTableQmlDialog):
    """QML 版「产出总表」。`OutputSummaryDialog(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(OutputSummaryBridge(), parent=parent, size=(1000, 560))

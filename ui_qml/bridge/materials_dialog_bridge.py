"""材料总表（填料总表）对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/materials_dialog.py`：
活跃计划的 BOM 汇总 + 库存比对 → 缺口 / 单价 / 总价 / 体积 / 状态，
外加「行内复制采购」与「一键复制全部」。

展示走通用的 `SummaryTableBridge`（多了一个行内动作列与一个顶栏动作按钮）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QApplication

from core.container import get_container
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell, fmt_isk

__all__ = ["MaterialsSummaryBridge", "MaterialsSummaryQmlDialog"]

_COLUMNS = [
    {"title": "材料名称", "width": 0},
    {"title": "层级", "width": 70},
    {"title": "总需求", "width": 110},
    {"title": "库存", "width": 110},
    {"title": "缺口", "width": 110},
    {"title": "单价", "width": 100},
    {"title": "总价", "width": 100},
    {"title": "体积", "width": 90},
    {"title": "状态", "width": 90},
    {"title": "复制采购", "width": 80},
]


class MaterialsSummaryBridge(SummaryTableBridge):
    """材料总表的 QML 后端。"""

    def __init__(self) -> None:
        super().__init__(title="填料总表", columns=[dict(c) for c in _COLUMNS])
        self._top_action_text = "一键复制全部"
        self._has_action_column = True
        #: 供「一键复制」用的行数据（与原版 `_data_rows` 同结构）
        self._data_rows: list[dict] = []

    @Slot()
    def reload(self) -> None:
        # 函数内导入：与本项目其他桥一致，也让调用方/测试好替换数据源
        from services.industry_dialog_queries import get_materials_summary

        data = get_materials_summary(get_container().db)
        if data is None:
            self.set_content([], "没有活跃计划")
            return
        materials = data["materials"]
        if not materials:
            self.set_content([], "没有材料需求")
            return

        inventory = data["inventory"]
        prices = data["prices"]
        sorted_mats = sorted(materials.items(), key=lambda x: (x[1].get("_level", 0), x[1]["name"]))

        rows: list[dict] = []
        self._data_rows = []
        total_cost = 0.0

        for type_id, info in sorted_mats:
            needed = info["total_qty"]
            owned = inventory.get(type_id, 0)
            gap = max(0, int(needed) - owned)
            unit_price = prices.get(type_id, {}).get("sell", 0.0)
            line_cost = gap * unit_price
            if unit_price:
                total_cost += line_cost
            volume = info.get("volume", 0)

            if gap <= 0:
                status_text, status_token = "已到位", "ACCENT_GREEN"
            elif owned > 0:
                status_text, status_token = "部分到位", "ACCENT_YELLOW"
            else:
                status_text, status_token = "未到位", "ACCENT_RED"
            gap_token = "ACCENT_RED" if gap > 0 else "ACCENT_GREEN"

            rows.append(
                {
                    "cells": [
                        cell(info["name"]),
                        cell("0"),  # 所有叶子节点层级为 0（原料）
                        cell(f"{needed:,.0f}"),
                        cell(f"{owned:,}"),
                        cell(f"{gap:,}", gap_token),
                        cell(fmt_isk(unit_price)),
                        cell(fmt_isk(line_cost)),
                        cell(f"{volume:.2f}" if volume else "—"),
                        cell(status_text, status_token),
                        cell(""),  # 行内动作列（QML 渲染成「复制」按钮）
                    ]
                }
            )
            self._data_rows.append({"name": info["name"], "gap": gap, "unit_price": unit_price})

        total_types = len(sorted_mats)
        ready_count = sum(1 for r in self._data_rows if r["gap"] <= 0)
        partial_count = sum(
            1
            for tid, info in sorted_mats
            if 0 < max(0, int(info["total_qty"]) - inventory.get(tid, 0)) < int(info["total_qty"])
        )
        missing_count = total_types - ready_count - partial_count

        self.set_content(
            rows,
            f"共 {total_types} 种材料，已到位 {ready_count} 种，"
            f"部分到位 {partial_count} 种，未到位 {missing_count} 种，缺口总价 {fmt_isk(total_cost)}",
        )

    @Slot(int)
    def copyRow(self, row: int) -> None:
        """行内「复制」：把「名称 + 需购量」写进剪贴板（制表符分隔，对齐原版）。"""
        if not 0 <= row < len(self._data_rows):
            return
        item = self._data_rows[row]
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(f"{item['name']}\t{item['gap']:,.0f}")
        self.set_error(f"已复制：{item['name']} 需购 {item['gap']:,.0f}")

    @Slot()
    def topAction(self) -> None:
        """一键复制全部待采购材料。"""
        pending = [r for r in self._data_rows if r["gap"] > 0]
        if not pending:
            self.set_error("所有材料已到位，无需采购")
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(f"{r['name']}* {r['gap']:.0f}" for r in pending))
        self.set_error(f"已复制 {len(pending)} 种待采购材料（共 {sum(r['gap'] for r in pending):,.0f} 个）")


class MaterialsSummaryQmlDialog(SummaryTableQmlDialog):
    """QML 版「填料总表」。`MaterialsSummaryDialog(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(MaterialsSummaryBridge(), parent=parent, size=(1100, 600))

"""人物占用对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/char_usage_dialog.py`：
按人物统计活跃计划数并列出占用详情。

**顺带修掉一处会崩的调用**：Widgets 版 `CharacterUsageDialog` 继承的是 `QWidget`，
而调用方 `industry_view.open_char_usage()` 对它调 `.exec()` —— `QWidget` 没有 `exec`，
点那个按钮必然 AttributeError。迁到 `QmlDialog`（真 QDialog）后这条路径才成立。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Slot

from core.container import get_container
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell

__all__ = ["CharacterUsageBridge", "CharacterUsageQmlDialog"]

_COLUMNS = [
    {"title": "角色名称", "width": 140},
    {"title": "活跃计划数", "width": 110},
    {"title": "队列时长", "width": 100},
    {"title": "技能等级", "width": 100},
    {"title": "占用详情", "width": 0},
]


def _load_token(plan_count: int) -> str:
    """活跃计划数越多越警示（与 Widgets 版同一组阈值）。"""
    if plan_count >= 5:
        return "ACCENT_RED"
    if plan_count >= 3:
        return "ACCENT_YELLOW"
    return "ACCENT_GREEN"


class CharacterUsageBridge(SummaryTableBridge):
    """人物占用的 QML 后端。"""

    def __init__(self) -> None:
        super().__init__(title="人物占用情况", columns=[dict(c) for c in _COLUMNS])

    @Slot()
    def reload(self) -> None:
        from services.industry_dialog_queries import get_character_usage

        rows = get_character_usage(get_container().db) or []
        if not rows:
            self.set_content([], "没有活跃计划")
            return

        content: list[dict] = []
        total_plans = 0
        for row in rows:
            char_name = row[0] or "(未分配)"
            plan_count = int(row[1] or 0)
            details = row[2] or "—"
            total_plans += plan_count
            content.append(
                {
                    "cells": [
                        cell(char_name),
                        cell(plan_count, _load_token(plan_count)),
                        cell("N/A"),
                        cell("N/A"),
                        cell(details),
                    ]
                }
            )

        self.set_content(content, f"共 {len(rows)} 个角色，{total_plans} 个活跃计划")


class CharacterUsageQmlDialog(SummaryTableQmlDialog):
    """QML 版「人物占用情况」。`CharacterUsageDialog(parent)` 的调用方原样可用。

    只读查看器 → **非模态独立窗**（`modeless=True`），调用方用 `show()` 而非 `exec()`。
    """

    def __init__(self, parent: Any = None) -> None:
        super().__init__(CharacterUsageBridge(), parent=parent, size=(820, 480), modeless=True)

"""物品搜索对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/inventory/item_search_dialog.py`：
搜索 item 表（含 terminology 里注册的基础矿物），选中后返回
`{type_id, zh_name, en_name}`。库存修正 / 移库对话框用它处理「未匹配」行 ——
这两个对话框自己也在本批次迁 QML，所以它是二级弹出。

布局复用 `FPickList`（与星系搜索同一份）；本类只负责查与选。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from core.container import get_container
from services.terminology import term
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["ItemSearchBridge", "ItemSearchQmlDialog", "search_rows"]

_QML_FILE = "dialogs/ItemSearchDialog.qml"

_DEBOUNCE_MS = 200

#: Widgets 版的列宽 {0: 70, 1: 180, 2: 180}；名字列改成吃满剩余空间
_COLUMNS = [
    {"title": "type_id", "width": 90},
    {"title": "中文", "width": 0},
    {"title": "英文", "width": 0},
]

_PLACEHOLDER = "输入物品名称（中文/英文）..."


def search_rows(results: list[dict]) -> list[dict]:
    """搜索结果 → 单元格行。纯函数，便于单测。"""
    return [
        {
            "cells": [
                cell(str(r["type_id"])),
                cell(r.get("zh_name", "")),
                cell(r.get("en_name", "")),
            ]
        }
        for r in results
    ]


def find_items(text: str) -> list[dict]:
    """item 表模糊匹配 + terminology 基础矿物反向匹配（逐条对齐原 `_search_items`）。

    基础矿物（34-40 等）不在 item 表里，只在 `terminology.item_overrides` 注册，
    所以要走一遍反向匹配补齐；`seen` 防止同一个 type_id 出两条。
    """
    results: list[dict] = list(get_container().item_repo.search_by_name(text, limit=20))
    term._ensure()
    overrides = term._data.get("item_overrides") or {}
    seen = {r["type_id"] for r in results}
    for tid_str, name in overrides.items():
        if text.lower() in str(name).lower() and int(tid_str) not in seen:
            results.append({"type_id": int(tid_str), "zh_name": name, "en_name": ""})
    return results


class ItemSearchBridge(DialogBridge):
    """物品搜索的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, title: str = "搜索匹配物品") -> None:
        super().__init__()
        self.set_title(title)
        self._query = ""
        self._results: list[dict] = []
        self._rows: list[dict] = []
        self._current_row = -1
        self._selected: dict | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.runSearch)

    # ── FPickList 的契约 ──────────────────────────────────────

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        return [dict(c) for c in _COLUMNS]

    @Property(list, notify=stateChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    @Property(int, notify=stateChanged)
    def currentRow(self) -> int:
        return self._current_row

    @Property(bool, notify=stateChanged)
    def hasSelection(self) -> bool:
        return self._selected is not None

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        if not self._query:
            return "输入名称开始搜索"
        return f"共 {len(self._results)} 个匹配项"

    @Slot(str)
    def setQuery(self, text: str) -> None:
        """过滤框每次变化都调它；真正的查询由防抖定时器触发。"""
        self._query = str(text)
        self._debounce.start()

    @Slot()
    def runSearch(self) -> None:
        """立刻查一次（防抖到期时走这里；测试也直接调它跳过等待）。"""
        text = self._query.strip()
        if not text:
            self._results = []
        else:
            try:
                self._results = find_items(text)
            except Exception:
                self._results = []
        self._rows = search_rows(self._results)
        # 结果换了，之前的选中行就指向了别的物品 —— 先清掉，再由下面重新选第一条
        self._current_row = -1
        self._selected = None
        self.set_error("")
        self.stateChanged.emit()
        # 搜到结果就自动选中第一条（对齐 Widgets 版 `_set_results` 的 `selectRow(0)`）：
        # 用户可以直接点「选定」，不必每次都先点一行
        if self._results:
            self.selectRow(0)

    @Slot(int)
    def selectRow(self, row: int) -> None:
        if not 0 <= row < len(self._results):
            return
        self._current_row = row
        self._selected = dict(self._results[row])
        self.set_error("")
        self.stateChanged.emit()

    @Slot(int)
    def activateRow(self, row: int) -> None:
        """双击一行 = 选中并确定（与 Widgets 版 `doubleClicked → _on_activate` 一致）。"""
        self.selectRow(row)
        self.accept()

    @Slot()
    def accept(self) -> None:
        """只搜到一条时直接采用它（原 `_on_accept` 的便利行为，保留）。"""
        if self._selected is None and len(self._results) == 1:
            self._current_row = 0
            self._selected = dict(self._results[0])
        if self._selected is None:
            self.set_error("请先在搜索结果中选择物品")
            return
        self.accepted.emit()

    def selected_item(self) -> dict | None:
        """返回选中的 {type_id, zh_name, en_name} 或 None。"""
        return dict(self._selected) if self._selected else None


class ItemSearchQmlDialog(QmlDialog):
    """QML 版「物品搜索」。`ItemSearchDialog(parent, title)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None, title: str = "搜索匹配物品") -> None:
        bridge = ItemSearchBridge(title)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(620, 460))
        self._search_bridge = bridge

    def selected_item(self) -> dict | None:
        return self._search_bridge.selected_item()

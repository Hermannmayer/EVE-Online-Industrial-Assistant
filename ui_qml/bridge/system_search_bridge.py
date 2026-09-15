"""星系搜索选择对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/dialogs/system_search_dialog.py`：输入名称 → 选一行 →
确定，返回 `(solar_system_id, 星系名)`。供机库设置 / 生产计划设施选择复用，
返回值的形状与 `get_selected()` 的名字都没变，两个调用方一行不用改。

搜库是本地 SQLite 查询，但**保留 200ms 防抖**（原实现如此）：每敲一个键就查一次
reference.db，输入快时白查多次；防抖放在桥里，QML 侧只管 `setQuery(text)`。
测试要确定性地拿到结果就跳过等待，直接调 `runSearch()`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from core.container import get_container
from services.ui_data_service import has_solar_system_data, search_solar_systems
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["SystemSearchBridge", "SystemSearchQmlDialog", "system_rows"]

_QML_FILE = "dialogs/SystemSearchDialog.qml"

_DEBOUNCE_MS = 200

#: 星系名吃满剩余空间（Widgets 版是 Stretch + ResizeToContents，QML 没有按内容自适应）
_COLUMNS = [
    {"title": "星系", "width": 0},
    {"title": "安全等级", "width": 90},
]

_NO_DATA_HINT = "⚠ 星系数据尚未加载，请先在 设置 → 数据初始化 重跑 SDE 扩展数据"


def system_rows(data: list[tuple[int, str, float]]) -> list[dict]:
    """`search_solar_systems` 的输出 → 单元格行。纯函数，便于单测。

    名字缺失时退回 id（与 Widgets 版 `name or str(sid)` 同口径）；安全等级为 0
    时留空而不是显示 0.0 —— 与 Widgets 版一致。
    """
    return [
        {
            "cells": [
                cell(name or str(sid)),
                cell(f"{sec:.1f}" if sec else ""),
            ]
        }
        for sid, name, sec in data
    ]


class SystemSearchBridge(DialogBridge):
    """星系搜索对话框的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, title: str = "选择星系") -> None:
        super().__init__()
        self.set_title(title)
        self._query = ""
        self._data: list[tuple[int, str, float]] = []
        self._rows: list[dict] = []
        self._current_row = -1
        self._selected: tuple[int, str] | None = None
        self._data_ready = self._check_data()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.runSearch)

    @staticmethod
    def _check_data() -> bool:
        return has_solar_system_data(db=get_container().db)

    # ── 给 QML 的只读状态 ──────────────────────────────────────

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        return [dict(c) for c in _COLUMNS]

    @Property(list, notify=stateChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    @Property(int, notify=stateChanged)
    def rowCount(self) -> int:
        """结果条数（QML 用 `rows.length`，这里给 Python 侧和测试一个直读入口）。"""
        return len(self._rows)

    @Property(int, notify=stateChanged)
    def currentRow(self) -> int:
        return self._current_row

    @Property(bool, notify=stateChanged)
    def hasSelection(self) -> bool:
        return self._selected is not None

    @Property(bool, constant=True)
    def dataReady(self) -> bool:
        return self._data_ready

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        if not self._data_ready:
            return _NO_DATA_HINT
        return f"共 {len(self._data)} 个星系"

    # ── 搜索 ──────────────────────────────────────────────────

    @Slot(str)
    def setQuery(self, text: str) -> None:
        """输入框每次变化都调它；真正的查询由防抖定时器触发。"""
        self._query = str(text)
        if not self._data_ready:
            return
        self._debounce.start()

    @Slot()
    def runSearch(self) -> None:
        """立刻查一次（防抖到期、以及打开对话框时的首次加载都走这里）。"""
        if not self._data_ready:
            return
        try:
            self._data = list(search_solar_systems(self._query.strip(), db=get_container().db))
        except Exception:
            self._data = []
        self._rows = system_rows(self._data)
        # 结果换了，之前的选中行就指向了别的星系 —— 必须清掉，否则「确定」会把
        # 上一次的星系名落库（原实现每次重建模型后 currentIndex 也失效，同效）
        self._current_row = -1
        self._selected = None
        self.stateChanged.emit()

    # ── 选中 / 确定 ───────────────────────────────────────────

    @Slot(int)
    def selectRow(self, row: int) -> None:
        if not 0 <= row < len(self._data):
            return
        sid, name, _sec = self._data[row]
        self._current_row = row
        self._selected = (int(sid), name or str(sid))
        self.set_error("")
        self.stateChanged.emit()

    @Slot(int)
    def activateRow(self, row: int) -> None:
        """双击一行 = 选中并确定（与 Widgets 版 `doubleClicked → _accept_current` 一致）。"""
        self.selectRow(row)
        self.accept()

    @Slot()
    def accept(self) -> None:
        """没选行就不让关 —— 原实现是「点了没反应」，这里给一句原因。"""
        if self._selected is None:
            self.set_error("请先选择一个星系")
            return
        self.accepted.emit()

    def get_selected(self) -> tuple[int, str] | None:
        """返回 (solar_system_id, 星系名)；未选择返回 None。"""
        return self._selected


class SystemSearchQmlDialog(QmlDialog):
    """QML 版「星系搜索」。`SystemSearchDialog(parent, title)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None, title: str = "选择星系") -> None:
        bridge = SystemSearchBridge(title)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(560, 480))
        self._system_bridge = bridge
        bridge.runSearch()  # 打开时先列一批（对齐 Widgets 版构造末尾的 _run_search）

    def get_selected(self) -> tuple[int, str] | None:
        return self._system_bridge.get_selected()

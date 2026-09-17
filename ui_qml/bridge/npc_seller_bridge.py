"""蓝图 NPC 卖家对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/dialogs/npc_seller_dialog.py`：选贸易中心 → 从 ESI 拉
该蓝图的卖单 → 筛出 NPC 公司的直售单（BPO）。取数在 `NpcOrderWorker` 里跑，
本类只负责组织与文案；行构造是纯函数 `npc_seller_rows`（已随线程挪到 workers）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.constants import TRADE_HUB_IDS
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell
from ui_qml.workers.lifecycle import detach_worker
from ui_qml.workers.npc_seller_workers import NpcOrderWorker

__all__ = ["NpcSellerBridge", "NpcSellerQmlDialog"]

_QML_FILE = "dialogs/NpcSellerDialog.qml"

#: 贸易中心候选（与 Widgets 版同一份，含中文简称）
_HUBS = [("吉他", "Jita"), ("艾玛", "Amarr"), ("多迪", "Dodixie"), ("伦斯", "Rens")]

#: 空间站那一列吃满剩余空间（Widgets 版是 ResizeToContents，QML 没有按内容自适应）
_COLUMNS = [
    {"title": "NPC 公司", "width": 180},
    {"title": "空间站", "width": 0},
    {"title": "价格", "width": 110},
    {"title": "剩余量", "width": 90},
]

_EMPTY_HINT = "该蓝图在当前贸易中心没有 NPC 直售单（可能为 T2/高级蓝图，请到市场找玩家订单）"


def order_rows(rows: list[dict]) -> list[dict]:
    """`npc_seller_rows` 的输出 → 单元格行。纯函数，便于单测。"""
    return [
        {
            "cells": [
                cell(r["corp"]),
                cell(r["location"]),
                cell(f"{r['price']:,.2f}", "PRIMARY"),
                cell(f"{r['volume']:,}"),
            ]
        }
        for r in rows
    ]


class NpcSellerBridge(SummaryTableBridge):
    """蓝图 NPC 卖家的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, blueprint_type_id: int, blueprint_name: str = "") -> None:
        name = blueprint_name or str(blueprint_type_id)
        super().__init__(title=f"蓝图 NPC 卖家 — {name}", columns=[dict(c) for c in _COLUMNS])
        self._type_id = int(blueprint_type_id)
        self._name = name
        self._hub_index = 0
        self._loading = False
        self._worker: NpcOrderWorker | None = None
        self.set_content([], "")

    # ── 静态文案 ──────────────────────────────────────────────

    @Property(str, constant=True)
    def headerText(self) -> str:
        return f"{self._name}  (type_id: {self._type_id})"

    @Property(str, constant=True)
    def noteText(self) -> str:
        return (
            "T1 蓝图原版(BPO) 由 NPC 公司在其空间站直售；此处列出该蓝图在当前贸易中心的 NPC 直售单。\n"
            "若列表为空：该蓝图可能非 NPC 直售（如 T2 蓝图），请到市场找玩家订单。"
        )

    @Property(list, constant=True)
    def hubs(self) -> list[dict]:
        return [{"label": f"{zh} ({en})"} for zh, en in _HUBS]

    # ── 贸易中心选择 + 拉取 ────────────────────────────────────

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        return self._hub_index

    @Property(bool, notify=stateChanged)
    def loading(self) -> bool:
        return self._loading

    @Slot(int)
    def setHub(self, index: int) -> None:
        """换贸易中心 —— 与原实现一致：选完立刻重新拉取。"""
        if not 0 <= index < len(_HUBS):
            return
        if index == self._hub_index:
            return
        self._hub_index = index
        self.stateChanged.emit()
        self.refresh()

    @Slot()
    def reload(self) -> None:
        """宿主打开对话框时调它（`SummaryTableQmlDialog.__init__`）。"""
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        region_id = int(TRADE_HUB_IDS[_HUBS[self._hub_index][1]])
        self._loading = True
        self.stateChanged.emit()
        self.set_content([], "正在从 ESI 获取卖单…")

        worker = NpcOrderWorker(region_id, self._type_id, self)
        self._worker = worker
        worker.result.connect(self._on_result)
        worker.start()

    def _on_result(self, rows: list, error: str) -> None:
        self._loading = False
        self.stateChanged.emit()
        if error:
            self.set_content([], error)
        elif not rows:
            self.set_content([], _EMPTY_HINT)
        else:
            self.set_content(order_rows(rows), f"共 {len(rows)} 条 NPC 直售单")

    def stop(self) -> None:
        """关窗收尾：拉单中断不了，那就别让它随对话框一起被销毁。

        ESI 拉单是网络请求，`requestInterruption()` 对它无效（原 Widgets 版的
        `closeEvent` 也是只请求中断）。而 `QThread` 在运行中被析构时 Qt 直接 abort ——
        整个进程静默死掉、无日志。收尾逻辑见 `ui_qml.workers.lifecycle.detach_worker`。
        """
        detach_worker(self._worker)


class NpcSellerQmlDialog(SummaryTableQmlDialog):
    """QML 版「蓝图 NPC 卖家」。`NpcSellerDialog(type_id, name, parent)` 的调用方原样可用。"""

    def __init__(self, blueprint_type_id: int, blueprint_name: str = "", parent: Any = None) -> None:
        super().__init__(
            NpcSellerBridge(blueprint_type_id, blueprint_name),
            parent=parent,
            size=(760, 520),
            qml_file=_QML_FILE,
        )

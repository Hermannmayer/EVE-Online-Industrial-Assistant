"""合同详情对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/dialogs/contract_detail_dialog.py`：上半是合同字段，
下半是合同内物品表。物品走后台线程加载（`ContractItemsLoadWorker`），
表格渲染复用通用的 `FSummaryTable`（与产出总表同一份）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell
from ui_qml.models.contract_models import _ITEM_COLUMNS, CONTRACT_STATUS_CN, CONTRACT_TYPE_CN

__all__ = ["ContractDetailBridge", "ContractDetailQmlDialog", "contract_item_rows"]

_QML_FILE = "dialogs/ContractDetailDialog.qml"

#: 「英文名」列在下标 2；把它设成弹性列，理由见 `_columns()`。
_FLEX_COLUMN = 2

_LOADING_TEXT = "正在加载物品列表…"


def _columns() -> list[dict]:
    """列定义 —— 与 Widgets 版同源于 `_ITEM_COLUMNS`，只把弹性列从最后一列换到「英文名」。

    Widgets 版是 `setStretchLastSection(True)`，于是被拉伸的是最后一列「PE」：
    一个两位数宽的窄列吃掉了右侧整片空白，而真正长的英文名被截断。
    QML 版把弹性给最长的「英文名」。列名、顺序、其余宽度一字未改。
    """
    return [
        {"title": title, "width": 0 if i == _FLEX_COLUMN else width} for i, (title, width) in enumerate(_ITEM_COLUMNS)
    ]


def contract_item_rows(items: list[dict]) -> list[dict]:
    """合同物品 → 单元格行。纯函数，便于单测。

    取值与配色对齐 `ContractItemTableModel._get_display` / `ForegroundRole`：
    数量列为主题色，其余默认；空缺的中英文名与效率值显示为「—」。
    """
    rows: list[dict] = []
    for item in items:
        me = item.get("material_efficiency", 0)
        te = item.get("time_efficiency", 0)
        rows.append(
            {
                "cells": [
                    cell(item.get("type_id", "")),
                    cell(item.get("zh_name", "") or "—"),
                    cell(item.get("en_name", "") or "—"),
                    cell(str(item.get("quantity", 0)), "PRIMARY"),
                    cell("是" if item.get("is_blueprint_copy") else "否"),
                    cell("是" if item.get("is_included", True) else "否"),
                    cell(str(me) if me else "—"),
                    cell(str(te) if te else "—"),
                ]
            }
        )
    return rows


class ContractDetailBridge(SummaryTableBridge):
    """合同详情的 QML 后端。"""

    itemsChanged = Signal()

    def __init__(self, contract: dict) -> None:
        super().__init__(title=f"合同详情 — #{contract.get('contract_id', '')}", columns=_columns())
        self._contract = dict(contract)
        self._items: list[dict] = []
        self._loaded = False
        self._worker: Any = None
        self.set_content([], _LOADING_TEXT)

    # ── 合同字段（打开后不变，故 constant）──────────────────────

    @Property(str, constant=True)
    def headerText(self) -> str:
        info = self._contract
        title = info.get("title", "") or "无标题"
        return f"#{info.get('contract_id', '')}  {title}"

    @Property(str, constant=True)
    def detailText(self) -> str:
        info = self._contract
        type_cn = CONTRACT_TYPE_CN.get(info.get("type", ""), info.get("type", ""))
        status_cn = CONTRACT_STATUS_CN.get(info.get("status", ""), info.get("status", ""))
        return (
            f"类型: {type_cn}  |  状态: {status_cn}  |  "
            f"价格: {info.get('price', 0):,.2f} ISK  |  "
            f"抵押: {info.get('collateral', 0):,.2f} ISK  |  "
            f"体积: {info.get('volume', 0):,.1f} m³  |  "
            f"运输天数: {info.get('days_completed', 0)}"
        )

    @Property(str, constant=True)
    def datesText(self) -> str:
        info = self._contract
        return (
            f"签发: {info.get('date_issued', '—')}  |  "
            f"过期: {info.get('date_expired', '—')}  |  "
            f"起始站: {info.get('start_location_id', '—')}  |  "
            f"终点站: {info.get('end_location_id', '—')}  |  "
            f"企业合同: {'是' if info.get('for_corporation') else '否'}"
        )

    @Property(str, notify=itemsChanged)
    def emptyText(self) -> str:
        return "正在加载…" if not self._loaded else "合同内没有物品"

    # ── 物品 ──────────────────────────────────────────────────

    @Slot()
    def reload(self) -> None:
        """开始加载物品列表（宿主的 `SummaryTableQmlDialog.__init__` 会调它）。

        重复调用（例如用户重新打开）不会叠线程：上一个还在跑就直接返回。
        """
        if self._worker is not None and self._worker.isRunning():  # type: ignore[attr-defined]
            return
        from ui_qml.workers.contract_workers import ContractItemsLoadWorker

        worker = ContractItemsLoadWorker(int(self._contract.get("contract_id") or 0), self)
        self._worker = worker
        worker.finished_signal.connect(self._on_items_loaded)
        worker.start()

    def _on_items_loaded(self, items: list[dict]) -> None:
        self._items = list(items)
        self._loaded = True
        self.set_content(contract_item_rows(self._items), f"共 {len(self._items)} 件物品")
        self.itemsChanged.emit()

    def stop(self) -> None:
        """关窗时等在跑的加载线程收尾（`QmlDialog._stop_bridge` 会调它）。

        不等的话，线程是桥的子对象、桥随对话框一起销毁 —— `QThread` 在运行中被析构
        Qt 直接 abort。物品读取是本地查询，几毫秒的事，等一下是安全的。
        """
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)


class ContractDetailQmlDialog(SummaryTableQmlDialog):
    """QML 版「合同详情」。`ContractDetailDialog(contract, parent)` 的调用方原样可用。"""

    def __init__(self, contract: dict, parent: Any = None) -> None:
        super().__init__(
            ContractDetailBridge(contract),
            parent=parent,
            size=(880, 540),
            qml_file=_QML_FILE,
        )

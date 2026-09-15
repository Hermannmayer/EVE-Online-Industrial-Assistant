"""移库对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/inventory/transfer_dialog.py`：从源机库按剪贴板
数量把材料移到当前机库。剪贴板数量超过源库现有时自动 clamp（按源库现有量移动，
该行标「源库不足」）；未匹配行可右键「搜索匹配物品…」接一个 type_id 后纳入移库计划。

表的形状是「勾选框 + 每行一个数量微调框」的**异质表**，不是只读汇总表，所以不复用
`SummaryTableBridge` / `FSummaryTable`；行渲染照 `BlueprintPickerDialog.qml` 那份
（同为「勾选框 + 每行可交互」的表），只是在每行末尾多挂一个 `FSpinBox`。
**业务判定（clamp / 统计 / 未匹配）留在桥里**，与 Widgets 版逐条对齐；颜色也从
`ui_pyside6.theme` 取 hex（QML 只负责画，不自己算规则）。

「选中哪些行」是纯 UI 状态（右键菜单的作用对象），留在 QML 的 `selRows`；桥只管
「哪几行被勾上 / 每行搬多少」这个业务事实。这与 `BlueprintPickerBridge` 同一分工。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Property, QUrl, Signal, Slot

import ui_pyside6.theme as theme
from services.inventory_import import compute_transfer_rows
from services.inventory_manager import get_hangar_stock, get_hangars, get_items, move_quantity
from ui_pyside6.icon_cache import item_icon_path
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "HangarTransferBridge",
    "HangarTransferQmlDialog",
    "matched_row",
    "transfer_summary",
    "unmatched_row",
]

_QML_FILE = "dialogs/TransferDialog.qml"

#: 列标题（逐字照搬原 `_HEADERS`）
_HEADERS = ["", "图标", "名称", "剪贴板数量", "源库现有", "移动数量", "单位成本", "目标现有"]

#: clamp 行的名称后缀（原 `_fill_matched_row` 里的字面量）—— 统计与确认都靠它识别
_CAPPED_SUFFIX = "（源库不足）"

#: 未匹配行的名称后缀
_UNMATCHED_SUFFIX = "（未匹配）"


def _icon_url(type_id: Any) -> str:
    """物品图标 URL（文件不存在返回空串，QML 的 Image 拿到空串不刷警告）。"""
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


def matched_row(index: int, parsed: dict, transfer: dict, cost_price: float) -> dict:
    """已匹配行的视图模型（纯函数，便于单测）。

    名称优先级与列格式逐条对齐原 `_fill_matched_row`：zh → en → raw → `ID:<id>`，
    数字一律千分位，成本两位小数；`capped` 行加后缀并染强调橙。
    """
    type_id = int(transfer["type_id"])
    name = parsed.get("zh_name") or parsed.get("en_name") or parsed.get("raw_name") or f"ID:{type_id}"
    capped = bool(transfer["capped"])
    return {
        "index": index,
        "type_id": type_id,
        "matched": True,
        "checked": True,  # 原版新填的勾选框一律 `setChecked(True)`
        "capped": capped,
        "nameText": f"{name}{_CAPPED_SUFFIX}" if capped else name,
        "nameColor": theme.ACCENT_ORANGE if capped else "",
        "icon": _icon_url(type_id),
        "clipText": f"{transfer['clipboard_qty']:,}",
        "srcText": f"{transfer['source_avail']:,}",
        "moveQty": int(transfer["move_qty"]),
        "maxQty": max(int(transfer["source_avail"]), 0),
        "costText": f"{cost_price:,.2f}",
        "targetText": f"{transfer['target_avail']:,}",
    }


def unmatched_row(index: int, parsed: dict) -> dict:
    """未匹配行的视图模型：灰显、名称加后缀、数值列一律「-」。"""
    raw = parsed.get("raw_name") or "?"
    return {
        "index": index,
        "type_id": None,
        "matched": False,
        "checked": False,
        "capped": False,
        "nameText": f"{raw}{_UNMATCHED_SUFFIX}",
        "nameColor": theme.TEXT_SECONDARY,
        "icon": "",
        "clipText": "-",
        "srcText": "-",
        "moveQty": 0,
        "maxQty": 0,
        "costText": "-",
        "targetText": "-",
    }


def transfer_summary(
    row_count: int,
    checked: int,
    total_move: int,
    capped: int,
    unmatched: int,
    filtered_note: int,
) -> str:
    """统计行文案（逐字对齐原 `_update_summary` 的拼接顺序与判据）。"""
    parts = [f"共 {row_count} 项"]
    if filtered_note:
        parts.append(f"已过滤 {filtered_note} 行蓝图")
    if checked:
        parts.append(f"勾选 {checked} 项")
        parts.append(f"将移动 {total_move:,} 件")
    if capped:
        parts.append(f"源库不足 {capped} 项")
    if unmatched:
        parts.append(f"未匹配 {unmatched} 项")
    return " / ".join(parts)


class HangarTransferBridge(DialogBridge):
    """移库的 QML 后端。"""

    #: 行集/来源变化（需要重建整张表）
    contentChanged = Signal()
    #: 只改了勾选/数量（表不用重建，只有统计行要重算）—— 否则用户敲微调框时
    #: 会因模型重置被抢焦点
    summaryChanged = Signal()

    def __init__(
        self,
        rows: list[dict],
        target_hangar_id: int,
        hangar_name: str,
        *,
        filtered_note: int = 0,
    ) -> None:
        super().__init__()
        self._parsed: list[dict] = rows
        self._filtered_note = max(int(filtered_note or 0), 0)
        self._target_hangar_id = int(target_hangar_id)

        self._hangars: list[dict] = []
        self._source_index = -1
        self._source_items: dict[int, dict] = {}
        self._source_stock: dict[int, int] = {}
        self._target_stock: dict[int, int] = {}

        self._rows: list[dict] = []
        self._checked: list[bool] = []
        self._qty: list[int] = []
        self._summary_text = ""
        self._result: dict[str, int] = {"moved": 0, "capped": 0}

        #: 承载它的 `QmlDialog`（开物品搜索子对话框时当 parent），由 QmlDialog 侧回填
        self.owner: Any = None

        self.set_title(f"移库 → {hangar_name}")
        self._load_hangars()

    # ── 只读输出 ──────────────────────────────────────────────

    headers = Property(list, lambda self: list(_HEADERS), constant=True)
    rows = Property(list, lambda self: list(self._rows), notify=contentChanged)
    summaryText = Property(str, lambda self: self._summary_text, notify=summaryChanged)
    #: 来源机库下拉的选项 [{label, id}]
    sources = Property(list, lambda self: [{"label": h["name"], "id": h["id"]} for h in self._hangars], constant=True)
    sourceIndex = Property(int, lambda self: self._source_index, notify=contentChanged)
    #: 有没有可用的来源机库 —— 没有就禁掉「确定移库」（原 `_ok_btn.setEnabled(False)`）
    canAccept = Property(bool, lambda self: bool(self._hangars), notify=contentChanged)

    # ── 数据加载 ──────────────────────────────────────────────

    def _load_hangars(self) -> None:
        others = [h for h in get_hangars() if h["id"] != self._target_hangar_id]
        self._hangars = others
        if not others:
            self._source_index = -1
            self._rows = []
            self._summary_text = "没有其他机库可移动"
            self.contentChanged.emit()
            self.summaryChanged.emit()
            return
        self._source_index = 0
        self._load_source()

    def _load_source(self) -> None:
        """按当前来源机库重取库存并重填（原 `_on_source_changed`）。"""
        if not 0 <= self._source_index < len(self._hangars):
            return
        src_id = self._hangars[self._source_index]["id"]
        self._source_items = {it["type_id"]: it for it in get_items(src_id)}
        self._source_stock = get_hangar_stock(src_id)
        self._target_stock = get_hangar_stock(self._target_hangar_id)
        self._rebuild()

    @Slot(int)
    def setSourceIndex(self, index: int) -> None:
        if not 0 <= index < len(self._hangars):
            return
        self._source_index = index
        self._load_source()

    # ── 表格填充 ──────────────────────────────────────────────

    def _rebuild(self) -> None:
        """按来源库存重算移库计划并重建行（原 `_populate_rows`）。

        行序 = 已匹配在前、未匹配在后，与 Widgets 版一致。
        """
        matched = [r for r in self._parsed if r.get("type_id")]
        unmatched = [r for r in self._parsed if not r.get("type_id")]
        transfers = compute_transfer_rows(matched, self._source_stock, self._target_stock)

        rows: list[dict] = []
        for i, (r, t) in enumerate(zip(matched, transfers, strict=True)):
            cost = self._source_items.get(int(t["type_id"]), {}).get("cost_price") or 0
            rows.append(matched_row(i, r, t, float(cost)))
        for j, r in enumerate(unmatched):
            rows.append(unmatched_row(len(matched) + j, r))

        self._rows = rows
        # 每次重填都重建勾选/数量状态（原版每次 `setCellWidget` 都新建勾选框与微调框，
        # 勾选恒为 True、数量恒为 clamp 后的 move_qty）
        self._checked = [bool(row["matched"]) for row in rows]
        self._qty = [int(row["moveQty"]) for row in rows]
        self._update_summary()
        self.contentChanged.emit()
        # 统计行的 notify 是 `summaryChanged`（见属性定义）——重填后必须一并发，
        # 否则换来源 / 删行 / 接物品之后 QML 上那句统计还是旧的
        self.summaryChanged.emit()

    # ── 行内交互 ──────────────────────────────────────────────

    @Slot(int, bool)
    def setRowChecked(self, index: int, checked: bool) -> None:
        if not 0 <= index < len(self._checked) or not self._rows[index]["matched"]:
            return
        self._checked[index] = bool(checked)
        self._update_summary()
        self.summaryChanged.emit()

    @Slot(int, int)
    def setRowQty(self, index: int, qty: int) -> None:
        if not 0 <= index < len(self._qty) or not self._rows[index]["matched"]:
            return
        self._qty[index] = int(qty)
        self._update_summary()
        self.summaryChanged.emit()

    @Slot(list)
    def deleteRows(self, indices: list) -> None:
        """删行（原 `_on_context_menu` 的删除分支）。行号即 `_parsed` 下标。"""
        for r in sorted({int(i) for i in indices}, reverse=True):
            if 0 <= r < len(self._parsed):
                del self._parsed[r]
        self._rebuild()

    @Slot(int)
    def searchMatch(self, row: int) -> None:
        """右键「搜索匹配物品…」：弹物品搜索，选中后接上 type_id 并重填。"""
        from PySide6.QtWidgets import QDialog, QWidget

        from ui_qml.bridge.item_search_bridge import ItemSearchQmlDialog

        parent = self.owner if isinstance(self.owner, QWidget) else None
        dlg = ItemSearchQmlDialog(parent, title="搜索匹配物品")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.selected_item()
        if not sel:
            return
        self.apply_match(row, sel)

    def apply_match(self, row: int, sel: dict) -> None:
        """把未匹配行接到选中的物品上（原 `_search_match` 的落地部分，抽出来便于单测）。

        行号即 `_parsed` 下标 —— 与 Widgets 版同一假设（表行序 = `_parsed` 序）。
        """
        if not (0 <= row < len(self._parsed)) or self._parsed[row].get("type_id"):
            return
        self._parsed[row].update(
            {
                "type_id": sel["type_id"],
                "zh_name": sel["zh_name"],
                "en_name": sel["en_name"],
                "status": "matched",
            }
        )
        self._load_source()  # 重取源库存并重填

    # ── 统计与确认 ────────────────────────────────────────────

    def _update_summary(self) -> None:
        count = 0
        total_move = 0
        capped = 0
        unmatched = 0
        for row in self._rows:
            if not row["matched"]:
                unmatched += 1
                continue
            if not self._checked[row["index"]]:
                continue
            count += 1
            total_move += self._qty[row["index"]]
            if row["capped"]:
                capped += 1
        self._summary_text = transfer_summary(
            len(self._rows), count, total_move, capped, unmatched, self._filtered_note
        )

    @Slot()
    def accept(self) -> None:
        """「确定移库」：逐行落库并汇总（原 `_on_accept`，QMessageBox 换成桥的提示）。"""
        if not self._hangars:
            self.set_error("没有可用的来源机库")
            return
        src_id = self._hangars[self._source_index]["id"]
        moved = 0
        capped = 0
        for row in self._rows:
            type_id = row["type_id"]
            if not row["matched"] or not type_id:
                continue
            if not self._checked[row["index"]]:
                continue
            qty = self._qty[row["index"]]
            if qty <= 0:
                continue
            moved += move_quantity(src_id, int(type_id), int(qty), self._target_hangar_id)
            if row["capped"]:
                capped += 1
        if moved == 0:
            self.set_error("没有可移动的物品")
            return
        self._result = {"moved": moved, "capped": capped}
        self.accepted.emit()

    def result_summary(self) -> dict:
        """返回 {"moved": 实际移动件数, "capped": 源库不足条目数"}。"""
        return dict(self._result)


class HangarTransferQmlDialog(QmlDialog):
    """QML 版「移库」。`HangarTransferDialog(rows, target_hangar_id, hangar_name, parent, filtered_note=)` 的调用方原样可用。

    原版 `setMinimumSize(880, 480)` + `resize(1000, 560)`：这里用后者做初始尺寸。
    """

    def __init__(
        self,
        rows: list[dict],
        target_hangar_id: int,
        hangar_name: str,
        parent: Any = None,
        *,
        filtered_note: int = 0,
    ) -> None:
        bridge = HangarTransferBridge(rows, target_hangar_id, hangar_name, filtered_note=filtered_note)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(1000, 560))
        self._transfer_bridge = bridge
        # 物品搜索是二级弹出，要一个 QWidget 当 parent（与蓝图选择器同一手法）
        bridge.owner = self

    def result_summary(self) -> dict:
        return self._transfer_bridge.result_summary()

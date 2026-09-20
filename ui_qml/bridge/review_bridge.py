"""剪贴板导入审阅链路的 QML 版（阶段 4b-3）。

对照 Widgets 版 `ui_pyside6/views/inventory/review_dialog.py`，一次迁三样：

- `ImportReviewDialog`  → `ImportReviewBridge` + `ImportReviewQmlDialog`
- `ImportChangeDialog`  → `ImportChangeBridge` + `ImportChangeQmlDialog`（复用汇总表骨架）
- `run_clipboard_import` → 同名同签名的编排函数（换的只是对话框实现）

外加原文件里 `_add_from_hangar` 现搭的那个「选择要移动的物品」QDialog —— 它是
「来自其他机库」右键项的第二级弹出，不迁就会从 QML 对话框里冒出一个纯 Widgets 窗口，
所以一并做成 `HangarPickBridge` + `HangarPickQmlDialog`。

**业务逻辑只有一份**：增减计算 `compute_row_delta`、导入前后对比 `compute_import_diff`、
剪贴板解析 `parse_clipboard`、落库 `apply_inventory_import`、市价取数 `market_repo` —— 全部
调用既有 services，桥只负责「取数 + 整形成 QML 能画的行/状态」。原类留在原文件里不动，
等调用点由主流程切过来后随该文件一并删除。

与原版的**刻意差异**（其余逐条对齐）：
- 表格列宽由「ResizeToContents + 最小宽」改为固定宽 + 名称列吃满 —— QML 这边
  表格是自绘的，没有 QHeaderView 的自动量宽；列宽单点放在桥的 `columns` 里便于断言。
- 「变化」列在有值时是 `FSpinBox`：输入不出非法值。原版是可编辑单元格，非数字
  在 `_on_final_changed` 里被 `except ValueError: return` 吞掉（保持原值不变），
  这里等价于「根本输入不进去」。
- 「来自其他机库」子菜单与它前面的分隔线**恒显示**：`FMenu` 没有「不可见即压高度」
  的兄弟组件（`FMenuItem` / `FMenuSeparator` 才有），空列表时是一个空子菜单。
  原版是无其他机库时整块不出现（`get_hangars()` 只排除目标机库，实际基本非空）。
- 4 处消息框改走 `FMessageDialog`（自绘 QML，批次 7.1）：
  「没有勾选」「N 行未匹配」「无物品」「无价格数据」。前两条**尤其不能**改成桥的
  `error` 通道 —— 原版是弹完继续 `accept()`／`return`，走 error 通道会在
  「确定导入」关窗后无人看见。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.inventory_clipboard_service import parse_clipboard, parse_purchase_clipboard
from services.inventory_import import compute_import_diff, compute_row_delta
from services.inventory_manager import apply_inventory_import, get_hangars, get_items
from services.user_settings import get_material_price_mult, set_material_price_mult
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.icon_cache import icon_url as _png_url

__all__ = [
    "HangarPickBridge",
    "HangarPickQmlDialog",
    "ImportChangeBridge",
    "ImportChangeQmlDialog",
    "ImportReviewBridge",
    "ImportReviewQmlDialog",
    "review_row",
    "run_clipboard_import",
    "run_purchase_import",
]

_REVIEW_QML = "dialogs/ImportReviewDialog.qml"
_CHANGE_QML = "dialogs/ImportChangeDialog.qml"
_HANGAR_PICK_QML = "dialogs/HangarPickDialog.qml"

#: 贸易中心（顺序与 Widgets 版的 combo 一致）
_HUB_ORDER = ["Jita", "Amarr", "Dodixie", "Rens"]
#: 贸易中心英文 → 中文（原 `ImportReviewDialog._HUB_NAMES`）
_HUB_NAMES = {"Jita": "吉他", "Amarr": "艾玛", "Dodixie": "多迪", "Rens": "伦斯"}

#: 导入模式：值 → 下拉显示名（原 combo 的两项）
_MODES: list[tuple[str, str]] = [("incremental", "增量累加"), ("full", "全量同步")]

#: 预览表列定义。width = 0 表示吃满剩余空间（与 `FSummaryTable` 同一约定）。
#: 标题照抄原 `_HEADERS`；勾选列在 QML 里是复选框、图标列是图片，标题留空/「图标」。
_REVIEW_COLUMNS = [
    {"title": "", "width": 30},
    {"title": "图标", "width": 46},
    {"title": "名称", "width": 0},
    {"title": "数量", "width": 92},
    {"title": "比原纪录", "width": 92},
    {"title": "变化", "width": 116},
    {"title": "成本价", "width": 132},
]

_CHANGE_COLUMNS = [
    {"title": "名称", "width": 0},
    {"title": "数量（前 → 后）", "width": 170},
    {"title": "成本（前 → 后）", "width": 170},
]

#: 数量/价格控件上限（原 `QDoubleSpinBox.setRange(0, 1e12)`）
_MAX_PRICE = 1e12
_MAX_QTY = 2_000_000_000


def _delta_token(delta: int) -> str:
    """增减着色：正绿负红，0 用默认前景色（原版 0 时不设 `ForegroundRole`）。"""
    if delta > 0:
        return "ACCENT_GREEN"
    if delta < 0:
        return "ACCENT_RED"
    return ""


def review_row(
    item: dict,
    *,
    current: int,
    sell_price: float,
    mode: str,
    source_hangar_id: int | None,
) -> dict:
    """一行预览数据 → QML 行字典（纯函数，便于单测）。

    Args:
        item: 解析后的一行 `{type_id|None, zh_name, en_name, qty, raw_name...}`
        current: 目标机库现有数量
        sell_price: 当前贸易中心的卖单价
        mode: 该行生效的导入模式（跨机库移动行恒为 ``incremental``）
        source_hangar_id: 该行的来源机库 id（非空 = 跨机库移动行）
    """
    type_id = item.get("type_id")
    if not type_id:
        raw = item.get("raw_name") or item.get("zh_name") or item.get("en_name") or "?"
        return {
            "typeId": None,
            "name": f"{raw}（未匹配）",
            "iconUrl": "",
            "current": 0,
            "currentText": "0",
            "delta": 0,
            "deltaText": "0",
            "deltaToken": "TEXT_SECONDARY",
            "final": 0,
            "price": 0.0,
            "checked": False,
            "checkable": False,
            "unmatched": True,
        }
    delta, final = compute_row_delta(mode, int(item.get("qty") or 0), int(current))
    return {
        "typeId": int(type_id),
        "name": str(item.get("display_name") or item.get("zh_name") or item.get("en_name") or f"ID:{type_id}"),
        "iconUrl": _png_url(type_id),
        "current": int(current),
        "currentText": f"{int(current):,}",
        "delta": delta,
        "deltaText": f"+{delta:,}" if delta >= 0 else f"{delta:,}",
        "deltaToken": _delta_token(delta),
        "final": final,
        "price": float(sell_price or 0.0),
        "checked": True,
        "checkable": True,
        "unmatched": False,
    }


def change_rows(changes: list[dict]) -> list[dict]:
    """变动汇总 → 单元格行（纯函数，便于单测）。

    数量列按增减染绿/红（与 `ImportChangeDialog` 逐条对齐），成本列不染色。
    """
    rows: list[dict] = []
    for ch in changes:
        delta = int(ch["qty_delta"])
        token = "ACCENT_GREEN" if delta > 0 else ("ACCENT_RED" if delta < 0 else "")
        rows.append(
            {
                "cells": [
                    cell(ch["name"]),
                    cell(f"{ch['qty_before']:,} → {ch['qty_after']:,}", token),
                    cell(f"{ch['cost_before']:,.2f} → {ch['cost_after']:,.2f}"),
                ]
            }
        )
    return rows


def change_summary(changes: list[dict], added: int, moved: int) -> str:
    """汇总文案（原 `ImportChangeDialog._build_summary`，逐字对齐）。"""
    if not changes:
        return f"成功导入 {added} 条，数量/成本均无变化"
    inc = sum(1 for c in changes if c["qty_delta"] > 0)
    dec = sum(1 for c in changes if c["qty_delta"] < 0)
    parts = [f"共 {len(changes)} 项变化"]
    if inc:
        parts.append(f"增加 {inc}")
    if dec:
        parts.append(f"减少 {dec}")
    if added:
        parts.append(f"成功导入 {added} 条")
    if moved:
        parts.append(f"跨机库移动 {moved} 条")
    return "，".join(parts)


# ══════════════════════════════════════════════════════════════
#  选择要移动的物品（原 `ImportReviewDialog._add_from_hangar` 现搭的那个对话框）
# ══════════════════════════════════════════════════════════════


class HangarPickBridge(DialogBridge):
    """另一机库的物品清单 —— 勾选要移入的物品。"""

    stateChanged = Signal()

    def __init__(self, source_items: list[dict]) -> None:
        super().__init__()
        self.set_title("选择要移动的物品")
        self._rows: list[dict] = [
            {
                "typeId": int(it["type_id"]),
                "name": str(it.get("display_name") or it.get("zh_name") or it.get("en_name") or f"ID:{it['type_id']}"),
                "qtyText": f"{int(it['quantity']):,}",
                "qty": int(it["quantity"]),
                "checked": True,  # 原版新勾选框默认全选
            }
            for it in source_items
        ]

    @Property(list, notify=stateChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    @Slot(int, bool)
    def setChecked(self, row: int, checked: bool) -> None:
        if not 0 <= row < len(self._rows):
            return
        self._rows[row]["checked"] = bool(checked)
        self.stateChanged.emit()

    def selected_items(self) -> list[tuple[int, int]]:
        """勾选的 `(type_id, 数量)`；没勾任何一项返回空表（调用方据此决定要不要重填）。"""
        picked: list[tuple[int, int]] = []
        for row in self._rows:
            if row["checked"]:
                picked.append((int(row["typeId"]), int(row["qty"])))
        return picked


class HangarPickQmlDialog(QmlDialog):
    """QML 版「选择要移动的物品」。"""

    def __init__(self, source_items: list[dict], parent: Any = None) -> None:
        bridge = HangarPickBridge(source_items)
        super().__init__(_HANGAR_PICK_QML, bridge, parent=parent, size=(500, 380))
        self._pick_bridge = bridge

    def selected_items(self) -> list[tuple[int, int]]:
        return self._pick_bridge.selected_items()


# ══════════════════════════════════════════════════════════════
#  导入预览
# ══════════════════════════════════════════════════════════════


class ImportReviewBridge(DialogBridge):
    """粘贴导入预览的 QML 后端：勾选 / 改数量 / 改成本价 / 右键批量。"""

    stateChanged = Signal()

    #: 宿主窗口 —— 二级弹出（搜索匹配 / 选物品）与消息框都拿它当父窗口。
    #: 由宿主在 `super().__init__()` **之后**写入（同 `parent_decompose_bridge` 的做法）：
    #: 那之前 QDialog 的 C++ 对象还没建出来，把半成品 QObject 挂到别的 QObject 上会挂死。

    def __init__(
        self,
        items: list[dict],
        hangar_name: str,
        target_hangar_id: int,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
    ) -> None:
        super().__init__()
        self.set_title(f"导入预览 → {hangar_name}")
        self._items = list(items)  # 工作副本（对应原 `_parsed_items`，与 _rows 同长同序）
        self._filtered_note = max(int(filtered_note or 0), 0)
        self._target_hangar_id = int(target_hangar_id)
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._hub_index = 0
        self._sell_prices: dict[int, float] = {}
        self._existing_qty: dict[int, int] = {}
        self._source_hangar: dict[int, int] = {}
        self._mode = default_mode if default_mode in {value for value, _ in _MODES} else "full"
        self._discount = float(get_material_price_mult())
        self._rows: list[dict] = []
        self._summary = ""
        self._menu_rows: list[int] = []

        # 预加载数据（顺序同原 `__init__`）
        self._fetch_existing_inventory()
        self._fetch_sell_prices()
        self._populate_rows()

    # ── QML 读的属性 ──────────────────────────────────────────

    modes = Property(list, lambda self: [{"label": label} for _value, label in _MODES], constant=True)
    hubs = Property(
        list,
        lambda self: [{"label": f"{h} ({_HUB_NAMES[h]})"} for h in _HUB_ORDER],
        constant=True,
    )
    columns = Property(list, lambda self: [dict(c) for c in _REVIEW_COLUMNS], constant=True)
    #: 成本价 / 数量控件上限（写死不在 QML：测试要断言，也只有一个来源）
    maxPrice = Property(float, lambda self: _MAX_PRICE, constant=True)
    maxQty = Property(int, lambda self: _MAX_QTY, constant=True)
    discountMin = Property(float, lambda self: 0.1, constant=True)
    discountMax = Property(float, lambda self: 10.0, constant=True)

    rows = Property(list, lambda self: list(self._rows), notify=stateChanged)
    summaryText = Property(str, lambda self: self._summary, notify=stateChanged)

    @Property(int, notify=stateChanged)
    def modeIndex(self) -> int:
        return next((i for i, (value, _label) in enumerate(_MODES) if value == self._mode), 0)

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        return self._hub_index

    @Property(float, notify=stateChanged)
    def discount(self) -> float:
        return self._discount

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(int)
    def setModeIndex(self, index: int) -> None:
        """导入模式切换：整表重算（原 `_on_mode_changed`）。"""
        if not 0 <= index < len(_MODES):
            return
        self._mode = _MODES[index][0]
        self._populate_rows()

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        """换贸易中心：重取卖单价并刷进各行成本价（原 `_on_hub_changed`）。"""
        if not 0 <= index < len(_HUB_ORDER):
            return
        self._hub_index = index
        self._region_id = TRADE_HUB_IDS.get(_HUB_ORDER[index], TRADE_HUB_IDS["Jita"])
        self._sell_prices = {}
        self._fetch_sell_prices()
        for row in self._rows:
            type_id = row["typeId"]
            if type_id:
                row["price"] = float(self._sell_prices.get(type_id, 0.0))
        self._update_summary()
        self.stateChanged.emit()

    @Slot(float)
    def setDiscount(self, value: float) -> None:
        """材料倍率（与生产规划页工具栏同一个设置，确认时写回）。"""
        self._discount = float(value)

    @Slot(int, bool)
    def setChecked(self, row: int, checked: bool) -> None:
        if not 0 <= row < len(self._rows) or not self._rows[row]["checkable"]:
            return
        self._rows[row]["checked"] = bool(checked)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(bool)
    def setAllChecked(self, checked: bool) -> None:
        """全选 / 取消全选（未匹配行的勾选框是禁用的，跳过）。"""
        for row in self._rows:
            if row["checkable"]:
                row["checked"] = bool(checked)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(int, int)
    def setFinal(self, row: int, value: int) -> None:
        """「变化」列被改：重算该行增减并着色（原 `_on_final_changed`）。"""
        if not 0 <= row < len(self._rows):
            return
        target = self._rows[row]
        if target["unmatched"]:
            return
        final = int(value)
        delta = final - int(target["current"])
        target["final"] = final
        target["delta"] = delta
        target["deltaText"] = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
        # 原版手改后 delta == 0 用次要色（与整表重填时的「默认前景」不同，这里照做）
        target["deltaToken"] = _delta_token(delta) or "TEXT_SECONDARY"
        self._update_summary()
        self.stateChanged.emit()

    @Slot(int, float)
    def setPrice(self, row: int, value: float) -> None:
        if not 0 <= row < len(self._rows):
            return
        self._rows[row]["price"] = float(value)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(result=bool)
    def ctrlHeld(self) -> bool:
        """Ctrl 是否按下 —— 修饰键在 Python 侧读（QML 的 `FTableClickArea` 只发行列号）。"""
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    # ── 右键菜单 ──────────────────────────────────────────────

    @Slot(list)
    def openMenu(self, rows: list[int]) -> None:
        """记录菜单作用行（QML 的选中集传进来）—— 原版是读表格的 selectionModel。"""
        self._menu_rows = [int(r) for r in rows]

    @Slot(list, result=dict)
    def menuState(self, rows: list[int]) -> dict:
        """右键菜单状态（对齐 `inventory_bridge.itemMenuState` 的形状：槽返回、QML 赋给 state）。"""
        other = [h for h in get_hangars() if h["id"] != self._target_hangar_id]
        return {
            "count": len(rows),
            "single": len(rows) == 1,
            "canSearchMatch": len(rows) == 1 and self._is_unmatched(int(rows[0])),
            "hangars": [{"id": h["id"], "name": h["name"]} for h in other],
            "discountText": f"{self._discount:.0%}",
        }

    @Slot(str)
    def setPriceFromMarket(self, price_type: str) -> None:
        """右键「设置为卖价/买价/均价」：逐行取所选区域市价（原 `_batch_set_price`）。

        原 `_set_price_from_market` 的 avg 分支与 else 分支做的事完全相同（都是
        `get_price_by_region`），这里合成一条；取不到价时逐行提示，与原来一致。
        """
        repo = get_container().market_repo
        for row in self._menu_rows:
            target = self._row(row)
            if target is None or not target["typeId"]:
                continue
            price = repo.get_price_by_region(target["typeId"], price_type, self._region_id)
            if price is None:
                FMessageDialog.information(self.host_widget(), "提示", "未找到该物品在所选区域的价格数据")
            else:
                target["price"] = float(price)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(str)
    def applyDiscount(self, price_type: str) -> None:
        """右键「卖价/买价 × 倍率」：先取市价再乘系数（原 disc_sell / disc_buy 分支）。"""
        self.setPriceFromMarket(price_type)
        for row in self._menu_rows:
            target = self._row(row)
            if target is not None:
                target["price"] = round(float(target["price"]) * self._discount, 2)
        self._update_summary()
        self.stateChanged.emit()

    @Slot()
    def deleteRows(self) -> None:
        """删除右键选中的行（表与数据同步删，倒序以免下标位移）。"""
        for row in sorted(set(self._menu_rows), reverse=True):
            if 0 <= row < len(self._rows):
                del self._rows[row]
                del self._items[row]
        self._menu_rows = []
        self._update_summary()
        self.stateChanged.emit()

    @Slot()
    def filterNoChange(self) -> None:
        """取消勾选「比原纪录」为 0 的行（原 `_filter_no_change`）。

        **保留原版的口径**：未匹配行的增量也是 "0"，它们本就未勾选、`setChecked(False)`
        是空操作，但原版照样计入「已过滤 N 项」——这里同样计入，避免文案悄悄变样。
        """
        filtered = 0
        for row in self._rows:
            if row["delta"] != 0:
                continue
            if row["checkable"] and row["checked"]:
                row["checked"] = False
            filtered += 1
        self._update_summary()
        if filtered:
            self._summary += f"  [已过滤 {filtered} 项无变化]"
            self.stateChanged.emit()

    @Slot()
    def searchMatch(self) -> None:
        """未匹配行手动搜索匹配：搜到后重取库存/市价并整表重填（原 `_search_match`）。"""
        if len(self._menu_rows) != 1:
            return
        row = self._menu_rows[0]
        if not self._is_unmatched(row):
            return

        from ui_qml.bridge.item_search_bridge import ItemSearchQmlDialog

        dlg = ItemSearchQmlDialog(self.host_widget(), title="搜索匹配物品")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.selected_item()
        if not sel:
            return
        if not 0 <= row < len(self._items) or self._items[row].get("type_id"):
            return
        self._items[row].update(
            {
                "type_id": sel["type_id"],
                "zh_name": sel["zh_name"],
                "en_name": sel["en_name"],
                "status": "matched",
            }
        )
        self._fetch_existing_inventory()
        self._fetch_sell_prices()
        self._populate_rows()

    @Slot(int)
    def addFromHangar(self, source_hangar_id: int) -> None:
        """从其他机库移入：勾选后按增量语义加入列表（原 `_add_from_hangar`）。"""
        source_items = get_items(source_hangar_id)
        if not source_items:
            FMessageDialog.information(self.host_widget(), "提示", "该机库中无物品")
            return

        dlg = HangarPickQmlDialog(source_items, self.host_widget())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        added = 0
        for type_id, qty in dlg.selected_items():
            name = next((it for it in source_items if it["type_id"] == type_id), {}).get("zh_name") or ""
            self._items.append({"type_id": type_id, "zh_name": name, "en_name": "", "qty": qty})
            self._source_hangar[type_id] = source_hangar_id
            added += 1

        if added:
            self._fetch_existing_inventory()
            self._fetch_sell_prices()
            self._populate_rows()

    # ── 确认 ──────────────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        """确定导入：先校验（两个消息框），再把倍率写回共享设置。"""
        checked = [row for row in self._rows if row["checked"]]
        if not checked:
            FMessageDialog.warning(self.host_widget(), "提示", "没有勾选的物品，无法导入")
            return
        unmatched = sum(1 for row in checked if not row["typeId"])
        if unmatched:
            FMessageDialog.information(
                self.host_widget(),
                "提示",
                f"{unmatched} 行未匹配物品未指定 type_id，导入时将跳过（可右键搜索匹配）",
            )
        # 倍率写回共享设置（与生产规划页工具栏同一个值），下次打开仍是它
        set_material_price_mult(self._discount)
        self.accepted.emit()

    # ── 给调用方取值（名字与原版一致）────────────────────────

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_import_data(self) -> list[tuple[int, int, float, int | None]]:
        """最终导入数据 list[(type_id, delta_qty, cost_price, source_hangar_id)]。"""
        result: list[tuple[int, int, float, int | None]] = []
        for row in self._rows:
            if not row["checked"] or not row["typeId"]:
                continue
            type_id = int(row["typeId"])
            result.append((type_id, int(row["delta"]), float(row["price"]), self._source_hangar.get(type_id)))
        return result

    def get_sync_targets(self) -> dict[int, int]:
        """全量模式下 {type_id: 目标数量}；跨机库移动行不参与全量 set。"""
        targets: dict[int, int] = {}
        for row in self._rows:
            type_id = row["typeId"]
            if not row["checked"] or not type_id or type_id in self._source_hangar:
                continue
            targets[int(type_id)] = int(row["final"])
        return targets

    # ── 内部 ──────────────────────────────────────────────────

    def _row(self, index: int) -> dict | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def _is_unmatched(self, index: int) -> bool:
        row = self._row(index)
        return bool(row and row["unmatched"])

    def _fetch_existing_inventory(self) -> None:
        """查询剪贴板涉及物品在目标机库里的现存量（只取基础字段）。

        `get_items` 默认还会算研究成本 / 计划占用 / 价格列，预览一个都不用 —— 走
        `include_derived=False` + `need_ids` 避免打开对话框时白算一整库。
        """
        try:
            need = {int(it["type_id"]) for it in self._items if it.get("type_id")}
            for it in get_items(self._target_hangar_id, include_derived=False, need_ids=need):
                self._existing_qty[it["type_id"]] = it["quantity"]
        except Exception:
            log.exception("获取现有库存失败")

    def _fetch_sell_prices(self) -> None:
        """预加载所有物品在当前贸易中心的卖单价。"""
        type_ids = list({it["type_id"] for it in self._items if it.get("type_id")})
        if not type_ids:
            return
        self._sell_prices = get_container().market_repo.get_sell_prices(type_ids, self._region_id)

    def _populate_rows(self) -> None:
        """按当前模式 / 库存 / 市价重算所有行（原 `_populate_rows`）。

        原版在这里重建整张表：勾选全部回到 True、手改的数量与价格被市价覆盖。
        `_on_mode_changed` 与「搜索匹配」都依赖这一重置行为，故照做。
        """
        rows: list[dict] = []
        for item in self._items:
            # 未匹配行的 type_id 是 None —— 归一到 0 只为了查表（`existing_qty` / `source_hangar`
            # 里不会有 0 号物品），行的分支由 `review_row` 按 type_id 真假决定
            tid = int(item["type_id"]) if item.get("type_id") else 0
            # 跨机库移动行始终按增量语义（不参与全量 set）；其余按当前导入模式
            row_mode = "incremental" if tid in self._source_hangar else self._mode
            rows.append(
                review_row(
                    item,
                    current=self._existing_qty.get(tid, 0),
                    sell_price=self._sell_prices.get(tid, 0.0),
                    mode=row_mode,
                    source_hangar_id=self._source_hangar.get(tid),
                )
            )
        self._rows = rows
        self._update_summary()
        self.stateChanged.emit()

    def _update_summary(self) -> None:
        """统计行（原 `_update_summary`，含「已过滤 N 行蓝图」前缀）。"""
        checked = 0
        total_delta = 0
        total_value = 0.0
        for row in self._rows:
            if not row["checked"]:
                continue
            checked += 1
            total_delta += int(row["delta"])
            total_value += float(row["price"]) * int(row["delta"])
        text = (
            f"已勾选 {checked} 项 / 总计 {len(self._rows)} 项 / "
            f"总增减 {total_delta:,} / 预估成本 {total_value:,.0f} ISK"
        )
        if self._filtered_note:
            text = f"[已过滤 {self._filtered_note} 行蓝图] {text}"
        self._summary = text


class ImportReviewQmlDialog(QmlDialog):
    """QML 版「粘贴导入预览」。

    `ImportReviewDialog(items, hangar_name, target_hangar_id, parent, default_mode=…, filtered_note=…)`
    的调用方原样可用。
    """

    def __init__(
        self,
        items: list[dict],
        hangar_name: str,
        target_hangar_id: int,
        parent: Any = None,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
    ) -> None:
        bridge = ImportReviewBridge(
            items,
            hangar_name,
            target_hangar_id,
            default_mode=default_mode,
            filtered_note=filtered_note,
        )
        super().__init__(_REVIEW_QML, bridge, parent=parent, size=(900, 560))
        # 桥的 `dialog` 必须在 `super().__init__()` **之后**才写：那之前 QDialog 的
        # C++ 对象还没建出来，挂上去会挂死（同 `parent_decompose_bridge` 的踩坑记录）
        self._review_bridge = bridge

    def mode(self) -> str:
        return self._review_bridge.mode()

    def get_import_data(self) -> list[tuple[int, int, float, int | None]]:
        return self._review_bridge.get_import_data()

    def get_sync_targets(self) -> dict[int, int]:
        return self._review_bridge.get_sync_targets()


# ══════════════════════════════════════════════════════════════
#  导入完成变动汇总
# ══════════════════════════════════════════════════════════════


class ImportChangeBridge(SummaryTableBridge):
    """导入完成后的变动汇总 —— 只读表 + 汇总行（复用汇总表骨架，本类只负责算）。"""

    def __init__(self, changes: list[dict], added: int, moved: int, hangar_name: str) -> None:
        super().__init__(title=f"导入完成 — {hangar_name}", columns=[dict(c) for c in _CHANGE_COLUMNS])
        self._changes = list(changes)
        self._summary = change_summary(self._changes, int(added), int(moved))
        self.set_empty_text("数量/成本均无变化" if not self._changes else "没有数据")

    @Slot()
    def reload(self) -> None:
        # 汇总文案放说明行（`headerText`）；状态行留空 —— 原版就是把汇总放在表格上方
        self.set_content(change_rows(self._changes), "", self._summary)


class ImportChangeQmlDialog(SummaryTableQmlDialog):
    """QML 版「导入完成变动汇总」。`ImportChangeDialog(changes, added, moved, hangar_name, parent)` 原样可用。"""

    def __init__(
        self,
        changes: list[dict],
        added: int,
        moved: int,
        hangar_name: str,
        parent: Any = None,
    ) -> None:
        super().__init__(
            ImportChangeBridge(changes, added, moved, hangar_name),
            parent=parent,
            size=(620, 460),
            qml_file=_CHANGE_QML,
        )


# ══════════════════════════════════════════════════════════════
#  剪贴板导入正式编排（仓库 / 采购共用）
# ══════════════════════════════════════════════════════════════


def _item_display_name(item: dict) -> str:
    """统一显示名：display_name（terminology 覆盖优先）→ zh → en → str(type_id)。"""
    return str(item.get("display_name") or item.get("zh_name") or item.get("en_name") or item.get("type_id", ""))


def run_clipboard_import(
    target_hangar_id: int,
    hangar_name: str,
    parent: Any,
    *,
    mode: str = "incremental",
) -> None:
    """读剪贴板 → 解析 → 导入预览 → 应用 → 变动汇总。仓库/采购共用入口。

    与 Widgets 版同名函数逐行等价，差别只有对话框实现（QML 版宿主）。剪贴板为空 /
    无有效行 / 用户取消 → 静默返回；蓝图行被过滤（材料仓库只导入材料），全部被过滤时提示一次。
    """
    raw = QApplication.clipboard().text().strip()
    if not raw:
        FMessageDialog.warning(parent, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
        return
    parsed, filtered = parse_clipboard(raw)
    if not parsed:
        if filtered:
            FMessageDialog.information(
                parent,
                "提示",
                f"剪贴板中的 {filtered} 行都是蓝图，材料仓库只导入材料，已全部过滤",
            )
        return

    # 导入前后快照（数量+成本），供差异对比 —— 只取基础字段，见 `_fetch_existing_inventory`
    before_items = get_items(target_hangar_id, include_derived=False)
    before = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in before_items}
    names_before = {it["type_id"]: _item_display_name(it) for it in before_items}

    dlg = ImportReviewQmlDialog(
        parsed, hangar_name, target_hangar_id, parent, default_mode=mode, filtered_note=filtered
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    data = dlg.get_import_data()
    if not data:
        return
    actual_mode = dlg.mode()
    targets = dlg.get_sync_targets() if actual_mode == "full" else None
    added, moved = apply_inventory_import(target_hangar_id, data, actual_mode, targets)

    after_items = get_items(target_hangar_id, include_derived=False)
    after = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in after_items}
    names_after = {it["type_id"]: _item_display_name(it) for it in after_items}
    type_ids = list(dict.fromkeys(list(before) + list(after)))
    names = {**names_before, **names_after}
    changes = compute_import_diff(before, after, names, type_ids)
    ImportChangeQmlDialog(changes, added, moved, hangar_name, parent).exec()


# ══════════════════════════════════════════════════════════════
#  钱包交易记录导入（仓库 / 采购共用）
# ══════════════════════════════════════════════════════════════


def _hangar_choices(default_hangar_id: int | None) -> tuple[list[str], list[int], int]:
    """机库下拉的 (标签, id, 默认下标)。标签口径与 `inventory_bridge._reload_hangars` 一致。"""
    from services.name_resolver import resolve_system_display_names_batch

    hangars = get_hangars()
    systems = resolve_system_display_names_batch([h["solar_system_id"] for h in hangars if h.get("solar_system_id")])
    labels: list[str] = []
    for hangar in hangars:
        sid = hangar.get("solar_system_id")
        labels.append(f"{hangar['name']} ({systems[sid]})" if sid in systems else str(hangar["name"]))
    ids = [int(h["id"]) for h in hangars]
    index = ids.index(int(default_hangar_id)) if default_hangar_id in ids else 0
    return labels, ids, index


def _purchase_summary(imported: int, unmatched: int, stats: dict) -> str:
    """导入结果一行汇总 —— **跳过项都要报数**，不然用户以为全进去了。"""
    parts = [f"已入库 {imported} 项"]
    if unmatched:
        parts.append(f"{unmatched} 条物品名未匹配已跳过")
    if stats.get("sales"):
        parts.append(f"{stats['sales']} 条卖出行已跳过")
    if stats.get("unparsed"):
        parts.append(f"{stats['unparsed']} 行认不出已跳过")
    return "，".join(parts)


def run_purchase_import(default_hangar_id: int | None, parent: Any) -> str | None:
    """读剪贴板里的「钱包 → 交易记录」→ 选机库 → 按粘贴的单价入库。仓库/采购共用入口。

    只吃**金额为负**的行（你付出 ISK = 买入）；卖出（正）与认不出的行统计后跳过。
    成本按记录里的**单价**写入，同物品多行进 `add_item` 加权平均（`apply_inventory_import`
    整批一个事务，失败整体回滚）。

    Returns:
        一行汇总文案；剪贴板为空 / 一条买入行都没有 / 用户取消机库选择 → None
        （前两种已弹提示）。
    """
    raw = QApplication.clipboard().text().strip()
    if not raw:
        FMessageDialog.warning(parent, "提示", "剪贴板为空，请先在游戏「钱包 → 交易记录」里 Ctrl+A/C 复制购买记录")
        return None
    rows, stats = parse_purchase_clipboard(raw)
    if not rows:
        FMessageDialog.information(parent, "提示", _purchase_summary(0, 0, stats))
        return None

    labels, ids, index = _hangar_choices(default_hangar_id)
    if not ids:
        FMessageDialog.warning(parent, "提示", "还没有机库，请先建一个再导入")
        return None
    from ui_qml.bridge.input_dialog import InputQmlDialog

    name, ok = InputQmlDialog.get_item(parent, "入库机库", "目标机库:", labels, index)
    if not ok or name not in labels:
        return None

    matched = [r for r in rows if r.get("type_id")]
    data: list[tuple[int, int, float, int | None]] = [
        (int(r["type_id"]), int(r["qty"]), float(r["unit_price"]), None) for r in matched
    ]
    if data:
        apply_inventory_import(ids[labels.index(name)], data, "incremental")
    return _purchase_summary(len(matched), len(rows) - len(matched), stats)

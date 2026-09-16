"""采购小助手（非模态工具窗）的 QML 桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/procurement_tab.py`，**只做转发与整形**：
业务（聚合采购需求、删除/手改的回放、轮询同步、置顶、完成所有）留在
`ProcurementDialog` 里 —— 它是纯控制器（批次 7.4 起基类是 `QObject`，窗口在
`qml/pages/ProcurementWindow.qml` 里），与 `production_launcher` 同款。

模块顶部那几个纯函数原本挂在旧文件的模块级/表模型上，**逻辑一字未改**地搬过来，
桥与旧类共用同一份，不出现两套口径。

**分区的口径**：`section` 参数一律是 `"buy"`（需采购）或 `"stock"`（库存已备足），
由 `split_sections` 按 `to_buy > 0` 切分。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS
from ui_qml.bridge.summary_dialog import cell

__all__ = [
    "ProcurementBridge",
    "copy_cell_text",
    "display_name",
    "procure_rows",
    "procure_table_headers",
    "resolve_item_name",
    "spread_text",
    "split_sections",
]

#: 表头（与 Widgets 版 `ProcureTableModel._HEADERS` 同源）
#: ⚠️ 这张表的四处**按索引对齐**：`_HEADERS` / `_SORT_FIELDS` / `_COPY_FIELDS` /
#: `procure_rows` 的 cells。加列必须四处一起插，插错位会让「排序按这列、复制按那列」静默错位。
#: 「库存」「单价」「体积」三列已下线（列表太宽、装不下）：数据仍在行里（`owned`/`price`/`volume`），
#: 只是不上表 —— 汇总行、复制整单、增量添加都还在用它们。
_HEADERS = ["物品名称", "总需求", "需采购", "买卖差价", "总价"]
_SORT_FIELDS = ["name", "need", "to_buy", "spread", "total"]

#: 双击复制的列 → 剪贴板文本：数量列取整、价格/价差保留两位，一律不带千分位
#: （游戏输入框不认逗号，复制出来必须能直接粘贴）
_COPY_FIELDS = ["name", "need", "to_buy", "spread", "total"]
_INT_COPY_COLS = (1, 2)

#: 列宽（名称列吃满剩余空间）。
#: ⚠️ 固定列宽之和必须**留得下名称列**：`FSummaryTable.colWidth` 给弹性列的下限是 80px
#: 且不会挤掉固定列 —— 固定列一多（曾经 6 列 ×104）总宽就超出窗口，右侧列被裁掉，
#: 表现为「首次打开所有列显示不全」。加列时按 `Σ(w+cellPadding(12)) + 12` 估一遍。
_COLUMNS = [
    {"title": _HEADERS[0], "width": 0},
    {"title": _HEADERS[1], "width": 84},
    {"title": _HEADERS[2], "width": 84},
    {"title": _HEADERS[3], "width": 92},
    {"title": _HEADERS[4], "width": 132},
]


def resolve_item_name(mid: int | None, zh_name: str | None, en_name: str | None) -> str:
    """统一物品名解析：item 表 → terminology.json → str(id)"""
    if zh_name:
        return zh_name
    if en_name:
        return en_name
    if mid is None:
        return ""
    from services.terminology import term

    override = term.item_override(mid)
    if override:
        return override
    return str(mid)


def display_name(row: dict) -> str:
    """行的显示名：与表格第 0 列同口径（zh → en → 术语覆盖 → id）。

    双击复制 / 整单复制 / 复制此行共用，避免覆盖物 id 行输出与界面不一致的裸 name。
    """
    mid: int | None = row.get("type_id")
    return resolve_item_name(mid, row.get("zh_name"), row.get("en_name"))


def split_sections(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 to_buy 拆分为 (需采购, 库存已备足) 分区。纯函数，便于单测。"""
    to_buy = [r for r in rows if r.get("to_buy", 0) > 0]
    done = [r for r in rows if r.get("to_buy", 0) <= 0]
    return to_buy, done


def spread_text(row: dict) -> str:
    """「卖价-买价」列的显示文本。单边无挂单 → `-`（`None` 是「算不出」，不是 0）。"""
    spread = row.get("spread")
    return "-" if spread is None else f"{spread:,.2f}"


def copy_cell_text(row: dict, column: int) -> str:
    """单元格的剪贴板文本（与显示同口径，去掉千分位）。纯函数，便于单测。"""
    if column == 0:
        return display_name(row)
    if not 0 <= column < len(_COPY_FIELDS):
        return ""
    val = row.get(_COPY_FIELDS[column])
    if val is None:
        # 无数据（如单边挂单时的价差）→ 空串 = 不复制。落进数字分支会复制出 "0.00"，
        # 那是「算不出」伪装成「就是 0」，比复制不出来更坏。
        return ""
    val = val or 0
    return f"{val:.0f}" if column in _INT_COPY_COLS else f"{val:.2f}"


def procure_table_headers() -> list[str]:
    return list(_HEADERS)


def _display_cells(r: dict) -> list[dict]:
    """一行 → 单元格列表（列顺序与 `_HEADERS` 严格一致）。"""
    to_buy = r.get("to_buy", 0)
    total = r.get("total", 0)
    return [
        cell(display_name(r)),
        cell(f"{r.get('need', 0):,.0f}"),
        cell(f"{to_buy:,.0f}", "ACCENT_RED" if to_buy > 0 else "GREEN"),
        cell(spread_text(r)),
        cell(f"{total:,.2f}", "ACCENT_RED" if total > 0 else ""),
    ]


def procure_rows(rows: list[dict]) -> list[dict]:
    """分区行 → 单元格行。纯函数，便于单测。

    取值与配色对齐原 `ProcureTableModel.data`：需采购 >0 染红、=0 染绿；
    总价 >0 染红、否则用默认前景色；数量列千分位取整，金额两位小数。
    """
    return [{"cells": _display_cells(r)} for r in rows]


class ProcurementBridge(QObject):
    """采购小助手的 QML 后端。`_page` 是 `ProcurementDialog` 实例（避免循环导入用 Any）。"""

    stateChanged = Signal()
    #: 入库 / 下线后转发页面的同名信号，供主界面重载计划
    plansChanged = Signal()

    def __init__(self, page: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page = page

    # ── 工具栏 ────────────────────────────────────────────────

    @Property(str, notify=stateChanged)
    def titleText(self) -> str:
        """窗口标题 —— 由 `_reload_plans` 按材料机库改写（批次 7.4 前是 `setWindowTitle`）。"""
        return str(self._page.window_title())

    @Property(list, constant=True)
    def priceTypeOptions(self) -> list[dict]:
        return [{"label": "卖价"}, {"label": "买价"}]

    @Property(int, notify=stateChanged)
    def priceTypeIndex(self) -> int:
        return 1 if self._page.price_type() == "buy" else 0

    @Slot(int)
    def setPriceTypeIndex(self, index: int) -> None:
        self._page.set_price_type("buy" if index == 1 else "sell")

    @Property(list, constant=True)
    def hubOptions(self) -> list[dict]:
        return [{"label": name} for name in TRADE_HUB_IDS]

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        names = list(TRADE_HUB_IDS)
        current = self._page.hub_text()
        return names.index(current) if current in names else names.index("Jita")

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        names = list(TRADE_HUB_IDS)
        if 0 <= index < len(names):
            self._page.set_hub(names[index])

    @Property(bool, notify=stateChanged)
    def pinned(self) -> bool:
        return bool(self._page.pinned())

    @Slot(bool)
    def setPinned(self, checked: bool) -> None:
        self._page.set_pinned(bool(checked))

    @Property(str, notify=stateChanged)
    def completeAllText(self) -> str:
        return str(self._page.complete_all_text())

    @Property(bool, notify=stateChanged)
    def completeAllVisible(self) -> bool:
        return bool(self._page.complete_all_text())

    # ── 两个分区 ──────────────────────────────────────────────

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        return [dict(c) for c in _COLUMNS]

    @Property(list, constant=True)
    def sortFields(self) -> list[str]:
        return list(_SORT_FIELDS)

    @Property(str, notify=stateChanged)
    def buyLabel(self) -> str:
        return str(self._page.section_label("buy"))

    @Property(str, notify=stateChanged)
    def stockLabel(self) -> str:
        return str(self._page.section_label("stock"))

    @Property(list, notify=stateChanged)
    def buyRows(self) -> list[dict]:
        return procure_rows(self._page.section_rows("buy"))

    @Property(list, notify=stateChanged)
    def stockRows(self) -> list[dict]:
        return procure_rows(self._page.section_rows("stock"))

    @Property(bool, notify=stateChanged)
    def buyVisible(self) -> bool:
        return bool(self._page.section_rows("buy"))

    @Property(bool, notify=stateChanged)
    def stockVisible(self) -> bool:
        return bool(self._page.section_rows("stock"))

    @Property(int, notify=stateChanged)
    def buySortColumn(self) -> int:
        return int(self._page.sort_column("buy"))

    @Property(bool, notify=stateChanged)
    def buySortAscending(self) -> bool:
        return bool(self._page.sort_ascending("buy"))

    @Property(int, notify=stateChanged)
    def stockSortColumn(self) -> int:
        return int(self._page.sort_column("stock"))

    @Property(bool, notify=stateChanged)
    def stockSortAscending(self) -> bool:
        return bool(self._page.sort_ascending("stock"))

    @Slot(str, int)
    def sortSection(self, section: str, column: int) -> None:
        """点表头排序（再点同列反向）—— 与原 `SortPreservingTableView` 的表头行为一致。"""
        self._page.sort_section(section, column)
        self.stateChanged.emit()

    # ── 底部 ──────────────────────────────────────────────────

    @Property(str, notify=stateChanged)
    def summaryText(self) -> str:
        return str(self._page.summary_text())

    @Property(str, notify=stateChanged)
    def copyHint(self) -> str:
        return str(self._page.copy_hint_text())

    @Property(str, notify=stateChanged)
    def emptyText(self) -> str:
        """两分区都空时的提示（原版放在底部汇总行）。"""
        return "无活跃计划材料需求"

    # ── 顶部动作 ──────────────────────────────────────────────

    @Slot()
    def refresh(self) -> None:
        self._page.recalculate()

    @Slot()
    def copyAll(self) -> None:
        self._page.copy_all_to_clipboard()

    @Slot()
    def addToHangar(self) -> None:
        self._page.add_to_hangar()

    @Slot()
    def completeAll(self) -> None:
        self._page.complete_all()

    # ── 行交互（section 由 QML 传 "buy"/"stock"）──────────────

    @Slot(str, int, int)
    def copyCell(self, section: str, row: int, column: int) -> None:
        """双击单元格 → 复制该列内容（名称列给物品名，数字列给纯数字），便于游戏内下单。"""
        self._page.copy_cell(section, row, column)

    @Slot(str, int)
    def deleteRow(self, section: str, row: int) -> None:
        self._page.delete_row(section, row)

    @Slot(str, int)
    def editQty(self, section: str, row: int) -> None:
        self._page.edit_qty(section, row)

    @Slot(str, int)
    def copyQty(self, section: str, row: int) -> None:
        self._page.copy_qty(section, row)

    @Slot(str, int)
    def copyLine(self, section: str, row: int) -> None:
        self._page.copy_line(section, row)

    # ── 窗口生命周期（批次 7.4）───────────────────────────────
    #
    # QML 根从 `Item` 换成 `Window` 之后，控制器的基类变成 `QObject` —— 原来由
    # `showEvent` / `hideEvent` / `closeEvent` / `done()` 承接的四件事改由 QML 侧的
    # `onVisibleChanged` / `onClosing` / `Esc` 快捷键调这几个槽转进来。**时机逐项对齐**：
    # `showEvent`（含一次 `_reload_plans`）↔ 可见变真；`hideEvent` ↔ 可见变假；
    # `closeEvent` ↔ 窗口即将关闭；`done()`/Esc ↔ `escapePressed`。

    @Slot(bool)
    def windowVisibilityChanged(self, visible: bool) -> None:
        self._page.window_visibility_changed(bool(visible))

    @Slot()
    def windowClosing(self) -> None:
        self._page.window_closing()

    @Slot()
    def escapePressed(self) -> None:
        """Esc：与原 `QDialog` 一样走 `reject()`（不经 `closeEvent`），同样清掉删除记录。"""
        self._page.reject()

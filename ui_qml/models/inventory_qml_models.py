"""仓库页两张表的 QML 适配。

- `InvQmlModel`：机库物品（8 列）。数量类列右对齐、图标列取物品 PNG、
  「规划占用」带 tooltip。展示规则照搬 `InvTableModel.data()`。
- `BlueprintQmlModel`：蓝图（11 列）。「类型」列在被活跃计划占用时标橙、
  「利润率」列按正负染绿红。展示规则照搬 `BlueprintTableModel.data()`。

两个模型都补了 `set_rows`：原版每次刷新都**新建**模型实例
（`self._model = InvTableModel(items)`），QML 侧需要一个稳定实例 + 整体换数据。
换完必须 `reapply_sort()` —— 排序状态归模型所有（桥只读它画表头箭头），
刷新后不重排就会「表头还亮着 ▲、内容已经变回原始顺序」。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl

from ui_qml.icon_cache import item_icon_path
from ui_qml.models.inventory_helpers import BlueprintTableModel, InvTableModel
from ui_qml.theme import registry as theme

__all__ = ["InvQmlModel", "BlueprintQmlModel"]

_BASE = Qt.ItemDataRole.UserRole

INV_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"iconUrl",
    _BASE + 3: b"alignRight",
    _BASE + 4: b"tooltip",
    _BASE + 5: b"rowIndex",
    _BASE + 6: b"itemId",
    _BASE + 7: b"selected",
}
_I_TEXT = _BASE + 1
_I_ICON = _BASE + 2
_I_ALIGN = _BASE + 3
_I_TIP = _BASE + 4
_I_ROW = _BASE + 5
_I_ID = _BASE + 6
_I_SELECTED = _BASE + 7

BP_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"rowIndex",
    _BASE + 6: b"bpId",
    _BASE + 7: b"itemName",
    _BASE + 8: b"selected",
}
_B_TEXT = _BASE + 1
_B_FG = _BASE + 2
_B_ICON = _BASE + 3
_B_ALIGN = _BASE + 4
_B_ROW = _BASE + 5
_B_ID = _BASE + 6
_B_NAME = _BASE + 7
_B_SELECTED = _BASE + 8


def _token(name: str) -> str:
    return str(getattr(theme, name, "") or "")


def _png_url(type_id: Any) -> str:
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class InvQmlModel(InvTableModel):
    """机库物品表：命名角色 + 可整体换行。"""

    #: 可排序列（与父类 `sort()` 的键一致）—— QML 用它决定表头是否可点，
    #: 判据只此一份，别在 QML 里再写一遍
    SORTABLE = frozenset({1, 2, 3, 4, 5, 6, 7})

    def __init__(self, items: list[dict] | None = None) -> None:
        super().__init__(list(items or []))
        self._selection: set[int] = set()

    def set_rows(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = list(items or [])
        self._selection = set()
        self.reapply_sort()  # 整份换数据后照当前排序重排（见模块 docstring）
        self.endResetModel()

    #: 选中行集合（由桥灌入）。**高亮走模型角色而不是 QML 侧派生集合**：
    #: 绑定一个「Python 侧算出来的列表」实测不会随选中变化重算（QML 侧的依赖没建立
    #: 起来），表现为点了行、画面上高亮不动 —— 看起来就像「选了另一行」。
    #: 走 `dataChanged` 是 TableView 的原生机制，确定会刷新。
    def rows(self) -> list[dict]:
        """底层行数据（只读用途：桥排序后要按 id 找回选中行）。"""
        return list(self._items)

    def set_selection(self, rows: set[int]) -> None:
        """把选中行灌进模型，只通知受影响的那段行。"""
        new = set(rows)
        changed = self._selection ^ new
        if not changed:
            return
        self._selection = new
        n = self.rowCount()
        touched = sorted(r for r in changed if 0 <= r < n)
        if not touched:
            return
        cols = self.columnCount()
        self.dataChanged.emit(self.index(touched[0], 0), self.index(touched[-1], cols - 1), [])

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return INV_ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._items[index.row()]
        col = index.column()

        if role == _I_TEXT:
            return "" if col == 0 else self._display(row, col)
        if role == _I_ICON:
            return _png_url(row.get("type_id")) if col == 0 else ""
        if role == _I_ALIGN:
            return col >= 2
        if role == _I_TIP:
            return "待启动计划预留" if col == 4 else ""
        if role == _I_ROW:
            return index.row()
        if role == _I_ID:
            return row.get("id")
        if role == _I_SELECTED:
            return index.row() in self._selection
        return super().data(index, role)

    @staticmethod
    def _display(row: dict, col: int) -> str:
        if col == 1:
            return str(row.get("display_name") or row.get("zh_name") or row.get("en_name") or f"ID:{row['type_id']}")
        if col == 2:
            return f"{row['quantity']:,}"
        if col == 3:
            return f"{row['cost_price']:,.2f}" if row["cost_price"] else "-"
        if col == 4:
            return f"{row['plan_usage']:,}" if row.get("plan_usage") else "0"
        if col == 5:
            remain = row.get("plan_remain")
            return f"{remain:,}" if remain is not None else f"{row['quantity']:,}"
        if col == 6:
            sell_price = row.get("sell_price")
            return f"{row['quantity'] * sell_price:,.0f}" if sell_price else "-"
        if col == 7:
            research_cost = row.get("research_cost")
            return f"{research_cost:,.0f}" if research_cost else ""
        return ""


class BlueprintQmlModel(BlueprintTableModel):
    """蓝图表：命名角色 + 可整体换行。"""

    #: 可排序列（父类 `sort()` 覆盖 0..10 全部列）
    SORTABLE = frozenset(range(11))

    def __init__(self, rows: list[dict] | None = None) -> None:
        super().__init__(list(rows or []))
        self._selection: set[int] = set()

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self._selection = set()
        self.reapply_sort()  # 整份换数据后照当前排序重排（见模块 docstring）
        self.endResetModel()

    #: 选中行集合（由桥灌入）。**高亮走模型角色而不是 QML 侧派生集合**：
    #: 绑定一个「Python 侧算出来的列表」实测不会随选中变化重算（QML 侧的依赖没建立
    #: 起来），表现为点了行、画面上高亮不动 —— 看起来就像「选了另一行」。
    #: 走 `dataChanged` 是 TableView 的原生机制，确定会刷新。
    def rows(self) -> list[dict]:
        """底层行数据（只读用途：桥排序后要按 id 找回选中行）。"""
        return list(self._rows)

    def set_selection(self, rows: set[int]) -> None:
        """把选中行灌进模型，只通知受影响的那段行。"""
        new = set(rows)
        changed = self._selection ^ new
        if not changed:
            return
        self._selection = new
        n = self.rowCount()
        touched = sorted(r for r in changed if 0 <= r < n)
        if not touched:
            return
        cols = self.columnCount()
        self.dataChanged.emit(self.index(touched[0], 0), self.index(touched[-1], cols - 1), [])

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return BP_ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _B_TEXT:
            return "" if col == 0 else self._display(row, col)
        if role == _B_ICON:
            return _png_url(row.get("product_type_id")) if col == 0 else ""
        if role == _B_ALIGN:
            return col >= 2
        if role == _B_FG:
            if col == 2 and row.get("occupied"):
                return _token("ACCENT_ORANGE")
            if col == 10:
                margin = row.get("margin")
                if margin is not None:
                    return _token("ACCENT_GREEN") if margin >= 0 else _token("ACCENT_RED")
            return ""
        if role == _B_ROW:
            return index.row()
        if role == _B_ID:
            return row.get("id")
        if role == _B_NAME:
            return self._name(row)
        if role == _B_SELECTED:
            return index.row() in self._selection
        return super().data(index, role)

    def _display(self, row: dict, col: int) -> str:
        if col == 1:
            return self._name(row)
        if col == 2:
            text = "蓝图原图" if row.get("is_bpo") else "蓝图拷贝"
            if row.get("occupied"):
                text += "（占用中）"
            return text
        if col == 3:
            return str(row.get("me_level", 0))
        if col == 4:
            return str(row.get("te_level", 0))
        if col == 5:
            return str(row.get("product_name") or "-")
        if col == 6:
            secs = row.get("base_time", 0)
            if secs <= 0:
                return "-"
            h, m = divmod(secs // 60, 60)
            d, h = divmod(h, 24)
            return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
        if col == 7:
            return "无限" if row.get("is_bpo") else str(row.get("runs", 0))
        if col == 8:
            cost = row.get("material_cost")
            return f"{cost:,.0f} ISK" if cost is not None else "-"
        if col == 9:
            revenue = row.get("revenue")
            return f"{revenue:,.0f} ISK" if revenue is not None else "-"
        if col == 10:
            margin = row.get("margin")
            return "-" if margin is None else f"{margin:+.1f}%"
        return ""

    @staticmethod
    def _name(row: dict) -> str:
        """与父类同一套取名口径（terminology 覆盖优先）。"""
        from services.terminology import term

        return str(
            row.get("zh_name")
            or row.get("display_name")
            or term.item_override(row.get("blueprint_type_id", 0))
            or f"ID:{row.get('blueprint_type_id')}"
        )

    def refresh_colors(self) -> None:
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, self.columnCount() - 1),
            list(BP_ROLE_NAMES),
        )

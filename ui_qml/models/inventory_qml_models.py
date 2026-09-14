"""仓库页两张表的 QML 适配。

- `InvQmlModel`：机库物品（8 列）。数量类列右对齐、图标列取物品 PNG、
  「规划占用」带 tooltip。展示规则照搬 `InvTableModel.data()`。
- `BlueprintQmlModel`：蓝图（11 列）。「类型」列在被活跃计划占用时标橙、
  「利润率」列按正负染绿红。展示规则照搬 `BlueprintTableModel.data()`。

两个模型都补了 `set_rows`：原版每次刷新都**新建**模型实例
（`self._model = InvTableModel(items)`），QML 侧需要一个稳定实例 + 整体换数据。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import item_icon_path
from ui_pyside6.views.inventory.inventory_helpers import BlueprintTableModel, InvTableModel

__all__ = ["InvQmlModel", "BlueprintQmlModel"]

_BASE = Qt.ItemDataRole.UserRole

INV_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"iconUrl",
    _BASE + 3: b"alignRight",
    _BASE + 4: b"tooltip",
    _BASE + 5: b"rowIndex",
    _BASE + 6: b"itemId",
}
_I_TEXT = _BASE + 1
_I_ICON = _BASE + 2
_I_ALIGN = _BASE + 3
_I_TIP = _BASE + 4
_I_ROW = _BASE + 5
_I_ID = _BASE + 6

BP_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"rowIndex",
    _BASE + 6: b"bpId",
    _BASE + 7: b"itemName",
}
_B_TEXT = _BASE + 1
_B_FG = _BASE + 2
_B_ICON = _BASE + 3
_B_ALIGN = _BASE + 4
_B_ROW = _BASE + 5
_B_ID = _BASE + 6
_B_NAME = _BASE + 7


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

    def __init__(self, items: list[dict] | None = None) -> None:
        super().__init__(list(items or []))

    def set_rows(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = list(items or [])
        self.endResetModel()

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

    def __init__(self, rows: list[dict] | None = None) -> None:
        super().__init__(list(rows or []))

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

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

"""合同页两张表的 QML 适配。

- `ContractQmlModel` / `ContractItemQmlModel`：给既有模型补**命名角色**，
  展示规则（价格绿、抵押橙、状态按语义染色、金额列右对齐 + 等宽）保持不动；
- 过滤仍走既有的 `ContractFilterProxy` —— `QSortFilterProxyModel` 会把源模型的
  `roleNames()` 转发下去，所以 QML 直接把**代理**当 model 用即可，
  过滤逻辑一份都不用重写。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Qt

from ui_qml.models.contract_models import ContractItemTableModel, ContractTableModel
from ui_qml.theme import registry as theme

__all__ = ["ContractQmlModel", "ContractItemQmlModel"]

_BASE = Qt.ItemDataRole.UserRole

CONTRACT_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"bg",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"mono",
    _BASE + 6: b"rowIndex",
    _BASE + 7: b"contractId",
}
_C_TEXT = _BASE + 1
_C_FG = _BASE + 2
_C_BG = _BASE + 3
_C_ALIGN = _BASE + 4
_C_MONO = _BASE + 5
_C_ROW = _BASE + 6
_C_ID = _BASE + 7

ITEM_ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"alignRight",
    _BASE + 3: b"rowIndex",
}
_I_TEXT = _BASE + 1
_I_ALIGN = _BASE + 2
_I_ROW = _BASE + 3


def _token(name: str) -> str:
    return str(getattr(theme, name, "") or "")


class ContractQmlModel(ContractTableModel):
    """合同列表：命名角色。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return CONTRACT_ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _C_TEXT:
            return self._get_display(row, col)
        if role == _C_FG:
            return self._fg(row, col)
        if role == _C_BG:
            return _token("BG_SURFACE") if index.row() % 2 == 0 else _token("BG_DARK")
        if role == _C_ALIGN:
            return col in (0, 3, 4, 5, 6)
        if role == _C_MONO:
            return col in (0, 3, 4, 5, 6)
        if role == _C_ROW:
            return index.row()
        if role == _C_ID:
            return row.get("contract_id")
        return super().data(index, role)

    @staticmethod
    def _fg(row: dict, col: int) -> str:
        if col == 3:  # 价格
            return _token("ACCENT_GREEN") if row.get("price", 0) else _token("TEXT_SECONDARY")
        if col == 4:  # 抵押
            return _token("ACCENT_ORANGE") if row.get("collateral", 0) else _token("TEXT_SECONDARY")
        if col == 7:  # 状态
            status = row.get("status", "")
            if status in ("outstanding", "in_progress"):
                return _token("ACCENT_GREEN")
            if status in ("cancelled", "expired", "deleted"):
                return _token("ACCENT_RED")
            return _token("TEXT_SECONDARY")
        return _token("TEXT_PRIMARY")


class ContractItemQmlModel(ContractItemTableModel):
    """合同内物品：命名角色（数量列右对齐）。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ITEM_ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        col = index.column()

        if role == _I_TEXT:
            return self._get_display(self._rows[index.row()], col)
        if role == _I_ALIGN:
            return col in (0, 3, 6, 7)
        if role == _I_ROW:
            return index.row()
        return super().data(index, role)

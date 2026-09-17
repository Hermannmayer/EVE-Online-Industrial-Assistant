"""跨区域价格对比表的 QML 适配。

与 `QueryQmlModel` / `PlanQmlModel` 同一套路：`TradeHubTableModel` 的展示规则
（价差% 染色、图标列、右对齐）保持不变，这里只补**命名角色**并让行数据可整体替换
（原版模型是构造时传 `rows` 的不可变形态，QML 侧需要一个稳定实例）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Qt

from ui_qml.icon_cache import icon_url as _icon_url
from ui_qml.models.trade_models import TradeHubTableModel
from ui_qml.theme import registry as theme

__all__ = ["TradeHubQmlModel", "ROLE_NAMES"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"rowIndex",
    _BASE + 6: b"hub",
}
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4
_ROW_INDEX = _BASE + 5
_HUB = _BASE + 6

#: 价差% 列（对齐 `TradeHubTableModel.data()` 的 ForegroundRole 分支）
_SPREAD_PCT_COL = 4


class TradeHubQmlModel(TradeHubTableModel):
    """跨区域价格表：命名角色 + 可整体替换行。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        super().__init__(list(rows or []))

    def set_rows(self, rows: list[dict]) -> None:
        """整体替换行（原版每次分析都新建模型，QML 侧复用同一实例）。"""
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _TEXT:
            return self._display(row, col)
        if role == _ICON_URL:
            return _icon_url(row.get("type_id")) if col == 0 else ""
        if role == _ALIGN_RIGHT:
            return col > 0  # 只有「贸易中心」列左对齐
        if role == _FG:
            if col == _SPREAD_PCT_COL:
                spread = row.get("spread_pct", 0) or 0
                if spread > 0:
                    return str(theme.ACCENT_GREEN)
                if spread < 0:
                    return str(theme.ACCENT_RED)
            return ""
        if role == _ROW_INDEX:
            return index.row()
        if role == _HUB:
            return row.get("hub", "")
        return super().data(index, role)

    @staticmethod
    def _display(row: dict, col: int) -> str:
        return str(
            [
                row.get("hub", ""),
                f"{row.get('buy_price', 0):,.2f}",
                f"{row.get('sell_price', 0):,.2f}",
                f"{row.get('spread', 0):,.2f}",
                f"{row.get('spread_pct', 0):.1f}%",
                f"{row.get('volume', 0):,}",
            ][col]
        )

    def refresh_colors(self) -> None:
        """主题切换后补发 dataChanged（价差% 的颜色是算出来的字符串）。"""
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, self.columnCount() - 1),
            list(ROLE_NAMES),
        )

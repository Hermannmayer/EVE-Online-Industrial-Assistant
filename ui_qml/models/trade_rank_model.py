"""跨区域价差排行表的 QML 模型。

与 `AllItemsQmlModel` 同一套路：命名角色（`text` / `fg` / `iconUrl` / `alignRight`）
交给 QML，展示规则留在 Python 侧。**不继承 `all_items_models.AModel`** ——
它的 `data()` 绑死了 `BCOLS` 的字段键与千分位格式，且被全物品页共用，改它会连带改那边。

排序**不走 `all_items_models.Proxy`**：那个把每格转成字符串再 `float(replace(...))`
解析回来，本表稳定在 1.2 万行量级，会白格式化两万多次。这里直接按原始数值排。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ui_qml.icon_cache import icon_url as _icon_url
from ui_qml.theme import registry as theme

__all__ = ["COLUMNS", "TradeRankQmlModel", "ROLE_NAMES", "format_order_change"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"typeId",
    _BASE + 6: b"isAction",
}
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4
_TYPE_ID = _BASE + 5
_IS_ACTION = _BASE + 6

DASH = chr(8212)

#: (表头, 宽度, 行字段键 / 排序键)。操作列没有数据键 —— 由 QML 渲染按钮。
COLUMNS: list[tuple[str, int, str | None]] = [
    ("", 34, None),  # 图标
    ("中文名称", 170, "z"),
    ("英文名称", 190, "e"),
    ("起点价格", 110, "pa"),
    ("终点价格", 110, "pb"),
    ("价差", 100, "spread"),
    ("每单位体积", 90, "v"),
    ("每方利润", 100, "pm3"),
    ("B侧挂单变化", 120, "chg"),
    ("", 88, None),  # 加入购物车
]

_ICON_COL = 0
_ACTION_COL = len(COLUMNS) - 1
_PM3_COL = 7
_CHG_COL = 8
#: 左对齐的列（其余右对齐）
_LEFT_COLS = {0, 1, 2}

#: 排序时把 None 当作「最小」——`-inf` 而非 0，否则「无数据」会挤在正值中间。
_SORT_NONE = float("-inf")


def format_order_change(per_day: float | None) -> str:
    """挂单变化的显示文案。正数 = 挂单在减少（有人在吃单）。"""
    if per_day is None:
        return DASH
    if per_day == 0:
        return "0/天"
    arrow = "↓" if per_day > 0 else "↑"
    return f"{arrow}{abs(per_day):,.0f}/天"


def _cell_text(row: dict, col: int) -> str:
    key = COLUMNS[col][2]
    if key == "chg":
        return format_order_change(row.get("chg"))
    if key == "pm3":
        v = row.get("pm3")
        return f"{v:,.2f}" if isinstance(v, int | float) else DASH
    if key == "v":
        v = row.get("v") or 0
        return f"{v:,.2f}" if v else DASH
    if key in ("pa", "pb", "spread"):
        v = row.get(key) or 0
        return f"{v:,.2f}"
    return str(row.get(key) or "")


class TradeRankQmlModel(QAbstractTableModel):
    """A → B 全品类价差排行：一个物品一行。"""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col = _PM3_COL
        self._sort_desc = True

    # ── 数据 ────────────────────────────────────────────────

    def set_rows(self, rows: list[dict]) -> None:
        """整体替换并套用当前排序（结果集变了要重排）。"""
        self.beginResetModel()
        self._rows = sorted(rows or [], key=self._sort_key, reverse=self._sort_desc)
        self.endResetModel()

    def row_at(self, r: int) -> dict:
        """第 r 行的原始数据（桥据此取 type_id 加购物车）。"""
        return self._rows[r]

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(COLUMNS)

    def headerData(  # type: ignore[override]
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(COLUMNS)
        ):
            return COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _TEXT:
            return "" if col == _ACTION_COL else _cell_text(row, col)
        if role == _ICON_URL:
            return _icon_url(row.get("id")) if col == _ICON_COL else ""
        if role == _ALIGN_RIGHT:
            return col not in _LEFT_COLS
        if role == _IS_ACTION:
            return col == _ACTION_COL
        if role == _TYPE_ID:
            return int(row.get("id") or 0)
        if role == _FG:
            return self._fg(row, col)
        if role == Qt.ItemDataRole.DisplayRole:
            return self.data(index, _TEXT)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            a = Qt.AlignmentFlag.AlignRight if col not in _LEFT_COLS else Qt.AlignmentFlag.AlignLeft
            return a | Qt.AlignmentFlag.AlignVCenter
        return None

    @staticmethod
    def _fg(row: dict, col: int) -> str:
        """只在「每方利润」「B侧挂单变化」两列给色，其余交给 QML 默认前景色。"""
        if col == _PM3_COL:
            v = row.get("pm3")
        elif col == _CHG_COL:
            v = row.get("chg")
        else:
            return ""
        if not isinstance(v, int | float):
            return ""
        if v > 0:
            return str(theme.ACCENT_GREEN)
        if v < 0:
            return str(theme.ACCENT_RED)
        return ""

    # ── 排序 ────────────────────────────────────────────────

    def sortColumn(self) -> int:
        return self._sort_col

    def sortDescending(self) -> bool:
        return self._sort_desc

    def _sort_key(self, row: dict):
        key = COLUMNS[self._sort_col][2]
        if key is None:
            return 0
        v = row.get("chg") if key == "chg" else row.get(key)
        if isinstance(v, int | float):
            return v
        if isinstance(v, str):
            return v
        return _SORT_NONE

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # type: ignore[override]
        if not 0 <= column < len(COLUMNS) or COLUMNS[column][2] is None:
            return  # 图标列与操作列不参与排序
        self._sort_col = column
        self._sort_desc = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=self._sort_key, reverse=self._sort_desc)
        self.layoutChanged.emit()

    def refresh_colors(self) -> None:
        """主题切换后补发 dataChanged（两列的颜色是算出来的字符串）。"""
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, len(COLUMNS) - 1),
            list(ROLE_NAMES),
        )

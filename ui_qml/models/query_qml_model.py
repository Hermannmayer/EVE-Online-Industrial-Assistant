"""物品查询结果表的 QML 适配。

QML 的 `TableView` 只认**命名角色**（没有 DisplayRole/ForegroundRole 那套约定），
而这张表的展示规则已经写在 `QueryTableModel.data()` 里 —— 本类只做
「角色名 → 那一次 data() 取值的等价计算」的映射，不复制任何业务逻辑，
`set_rows` / `sort` / `get_row` 全部沿用父类实现。

与 `PlanQmlModel` 同一套路（见该文件头部说明）。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import item_icon_path
from ui_pyside6.views.query.query_search import QueryTableModel

__all__ = ["QueryQmlModel", "ROLE_NAMES"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"bg",
    _BASE + 4: b"iconUrl",
    _BASE + 5: b"alignRight",
    _BASE + 6: b"mono",
    _BASE + 7: b"tooltip",
    _BASE + 8: b"rowIndex",
    _BASE + 9: b"typeId",
}

_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ICON_URL = _BASE + 4
_ALIGN_RIGHT = _BASE + 5
_MONO = _BASE + 6
_TOOLTIP = _BASE + 7
_ROW_INDEX = _BASE + 8
_TYPE_ID = _BASE + 9

#: 右对齐 + 等宽字体的列（对齐 `QueryTableModel.data()` 的 TextAlignment/FontRole）
_RIGHT_ALIGNED = frozenset({1, 4, 5, 6, 7})
#: 有价格时染色的列 → 颜色 token
_PRICE_TOKENS: dict[int, tuple[str, str]] = {
    4: ("buy_str", "ACCENT_GREEN"),
    5: ("sell_str", "ACCENT_RED"),
    6: ("avg_price_str", "ACCENT_GREEN"),
}


def _token(name: str) -> str:
    """按 token 名取当前主题色值。"""
    return str(getattr(theme, name, "") or "")


def icon_url(type_id: Any) -> str:
    """物品图标（磁盘上的 PNG）URL；没有缓存文件时返回空串。"""
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class QueryQmlModel(QueryTableModel):
    """给 `QueryTableModel` 补命名角色，供 QML `TableView` + delegate 使用。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        col = index.column()

        if role == _TEXT:
            # 列 0 只有图标没有文字（与原 `data()` 的 DisplayRole 分支一致）
            return "" if col == 0 else self._get_display(self._rows[index.row()], col)
        if role == _ICON_URL:
            return icon_url(self._rows[index.row()].get("type_id")) if col == 0 else ""
        if role == _ALIGN_RIGHT:
            return col in _RIGHT_ALIGNED
        if role == _MONO:
            return col in _RIGHT_ALIGNED
        if role == _FG:
            return self._fg(self._rows[index.row()], col)
        if role == _BG:
            return self._bg(self._rows[index.row()], index.row())
        if role == _TOOLTIP:
            row = self._rows[index.row()]
            return f"{row.get('zh', '')}\nType ID: {row.get('type_id', '')}".strip()
        if role == _ROW_INDEX:
            return index.row()
        if role == _TYPE_ID:
            return self._rows[index.row()].get("type_id")
        # 其余角色（含 DisplayRole）交回父类，保持 Widgets 侧行为不变
        return super().data(index, role)

    # ── 展示规则（逐条对齐 `QueryTableModel.data()`） ─────────────

    @staticmethod
    def _fg(row: dict, col: int) -> str:
        spec = _PRICE_TOKENS.get(col)
        if spec is None:
            return ""
        key, token = spec
        return _token(token) if row.get(key) != "—" else _token("TEXT_SECONDARY")

    @staticmethod
    def _bg(row: dict, row_index: int) -> str:
        if row.get("is_inverted"):
            return _token("BG_HOVER")
        return _token("BG_SURFACE") if row_index % 2 == 0 else _token("BG_DARK")

    # ── 排序状态（供桥读，不直接摸私有字段） ─────────────────

    @property
    def sort_column(self) -> int:
        return int(self._sort_col)

    @property
    def sort_ascending(self) -> bool:
        return bool(self._sort_order == Qt.SortOrder.AscendingOrder)

    def refresh_colors(self) -> None:
        """主题切换后补发 dataChanged —— 颜色是算出来的字符串，QML 绑定不会自己重算。"""
        if not self._rows:
            return
        top = self.index(0, 0)
        bottom = self.index(len(self._rows) - 1, self.columnCount() - 1)
        # 角色列表要显式给全：只发前两个参数时部分 QML 绑定不会重读（与 PlanQmlModel 同款）
        self.dataChanged.emit(top, bottom, list(ROLE_NAMES))

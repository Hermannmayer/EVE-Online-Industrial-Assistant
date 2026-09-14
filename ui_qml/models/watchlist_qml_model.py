"""关注列表（价格监控）表的 QML 适配。

`WatchlistTableModel` 的展示规则（买卖价染色、价差% 橙、价格变化/阈值触发的行底色、
金额列右对齐 + 等宽）保持不变，这里只补**命名角色**。

底色带 alpha（价格变化用 50/255 的绿/红叠加），所以必须是 `#aarrggbb` 形式 ——
QML 的 `color` 能解析它，而 `#rrggbb` 会丢掉透明度、把整行糊成实心色。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QColor

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import item_icon_path
from ui_pyside6.views.watchlist_view import WatchlistTableModel

__all__ = ["WatchlistQmlModel", "ROLE_NAMES"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"bg",
    _BASE + 4: b"iconUrl",
    _BASE + 5: b"alignRight",
    _BASE + 6: b"mono",
    _BASE + 7: b"rowIndex",
    _BASE + 8: b"watchId",
    _BASE + 9: b"itemName",
}
_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ICON_URL = _BASE + 4
_ALIGN_RIGHT = _BASE + 5
_MONO = _BASE + 6
_ROW_INDEX = _BASE + 7
_WATCH_ID = _BASE + 8
_ITEM_NAME = _BASE + 9

#: 右对齐 + 等宽字体的列（对齐 `WatchlistTableModel.data()`）
_ALIGNED_COLS = frozenset({4, 5, 6, 7, 8})

#: 价格变化高亮的叠加不透明度（对齐原版 `setAlpha(50)`）
_CHANGE_ALPHA = 50


def _token(name: str) -> str:
    return str(getattr(theme, name, "") or "")


def _tint(name: str) -> str:
    """带透明度的主题色的 `#aarrggbb` 形式。"""
    color = QColor(_token(name))
    if not color.isValid():
        return ""
    color.setAlpha(_CHANGE_ALPHA)
    return color.name(QColor.NameFormat.HexArgb)


def _icon_url(type_id: Any) -> str:
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class WatchlistQmlModel(WatchlistTableModel):
    """关注列表：命名角色（行数据与刷新仍走父类）。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _TEXT:
            return "" if col == 0 else self._get_display(row, col)
        if role == _ICON_URL:
            return _icon_url(row.get("type_id")) if col == 0 else ""
        if role == _ALIGN_RIGHT:
            return col in _ALIGNED_COLS
        if role == _MONO:
            return col in _ALIGNED_COLS
        if role == _FG:
            return self._fg(row, col)
        if role == _BG:
            return self._bg(row, index.row())
        if role == _ROW_INDEX:
            return index.row()
        if role == _WATCH_ID:
            return row.get("id")
        if role == _ITEM_NAME:
            return row.get("zh_name") or row.get("en_name") or ""
        return super().data(index, role)

    # ── 展示规则（逐条对齐 `WatchlistTableModel.data()`） ─────────

    @staticmethod
    def _fg(row: dict, col: int) -> str:
        if col == 4:
            return _token("ACCENT_GREEN") if row.get("buy_price") else _token("TEXT_SECONDARY")
        if col == 5:
            return _token("ACCENT_RED") if row.get("sell_price") else _token("TEXT_SECONDARY")
        if col == 6:
            buy_price = row.get("buy_price")
            if buy_price and row.get("sell_price") and buy_price > 0:
                return _token("ACCENT_ORANGE")
            return _token("TEXT_SECONDARY")
        return ""

    def _bg(self, row: dict, row_index: int) -> str:
        # 1) 价格变化高亮（优先于阈值触发）
        type_id = row.get("type_id")
        change = self._price_changes.get(int(type_id)) if type_id else None
        if change:
            new_buy = change.get("new_buy", 0) or 0
            old_buy = change.get("old_buy", 0) or 0
            new_sell = change.get("new_sell", 0) or 0
            old_sell = change.get("old_sell", 0) or 0
            if new_buy > old_buy or new_sell > old_sell:
                return _tint("ACCENT_GREEN")
            if new_buy < old_buy or new_sell < old_sell:
                return _tint("ACCENT_RED")

        # 2) 阈值触发
        buy_thresh = row.get("buy_threshold")
        sell_thresh = row.get("sell_threshold")
        buy_price = row.get("buy_price")
        sell_price = row.get("sell_price")
        if (buy_thresh is not None and buy_price and buy_price <= buy_thresh) or (
            sell_thresh is not None and sell_price and sell_price >= sell_thresh
        ):
            return _token("BG_SURFACE_LIGHT")

        # 3) 隔行
        return _token("BG_SURFACE") if row_index % 2 == 0 else _token("BG_DARK")

    def refresh_colors(self) -> None:
        """主题切换 / 价格变化后补发 dataChanged（颜色都是算出来的字符串）。"""
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, self.columnCount() - 1),
            list(ROLE_NAMES),
        )

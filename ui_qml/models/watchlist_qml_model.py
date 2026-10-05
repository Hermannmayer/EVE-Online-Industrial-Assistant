"""关注列表（价格监控）表的 QML 适配。

`WatchlistTableModel` 的展示规则（买卖价染色、价差% 橙、价格变化/阈值触发的行底色、
金额列右对齐 + 等宽）保持不变，这里只补**命名角色**。

底色带 alpha（价格变化用 50/255 的绿/红叠加），所以必须是 `#aarrggbb` 形式 ——
QML 的 `color` 能解析它，而 `#rrggbb` 会丢掉透明度、把整行糊成实心色。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor

from ui_qml.icon_cache import icon_url as _icon_url
from ui_qml.models.watchlist_models import WatchlistTableModel
from ui_qml.theme.registry import token as _token

__all__ = ["DASH", "ROLE_NAMES", "WatchlistQmlModel"]

#: 缺数据的统一占位 —— **不用 0 冒充**（价格 0 表示没有挂单，不是「卖 0 ISK」）。
#: 定义在这里：表格模型与桥（对比表、材料表）共用一份，避免两处各写一个字面量。
DASH = "—"

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
    # 左侧窄列表（`ListView`）用的**行级**角色：与列无关，列 0 上取也一样。
    # 窄列表每行只有 4 段文字（名称 / 买价 / 卖价 / 涨幅），列级角色取不到。
    _BASE + 10: b"rowName",
    _BASE + 11: b"buyText",
    _BASE + 12: b"sellText",
    _BASE + 13: b"riseText",
    _BASE + 14: b"note",
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
_ROW_NAME = _BASE + 10
_BUY_TEXT = _BASE + 11
_SELL_TEXT = _BASE + 12
_RISE_TEXT = _BASE + 13
_NOTE = _BASE + 14

#: 右对齐 + 等宽字体的列（对齐 `WatchlistTableModel.data()`）
_ALIGNED_COLS = frozenset({4, 5, 6, 7, 8})

#: 价格变化高亮的叠加不透明度（对齐原版 `setAlpha(50)`）
_CHANGE_ALPHA = 50


def _tint(name: str) -> str:
    """带透明度的主题色的 `#aarrggbb` 形式。"""
    color = QColor(_token(name))
    if not color.isValid():
        return ""
    color.setAlpha(_CHANGE_ALPHA)
    return color.name(QColor.NameFormat.HexArgb)


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
        # ── 左侧窄列表的行级角色（与列无关） ──
        if role == _ROW_NAME:
            return row.get("zh_name") or row.get("en_name") or ""
        if role == _BUY_TEXT:
            return self._get_display(row, 4)
        if role == _SELL_TEXT:
            return self._get_display(row, 5)
        if role == _RISE_TEXT:
            # 由桥在 refresh() 里按 `added_price` 算好塞进行里；缺失时桥给的就是 DASH
            return str(row.get("rise_text") or DASH)
        if role == _NOTE:
            return str(row.get("note") or "")
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

    def list_rows(self) -> list[dict[str, Any]]:
        """左侧窄列表（`ListView`）的行卡片载荷。

        `ListView` 用 JS 数组模型（本仓所有 `ListView` 的既有做法），所以这里把**行级角色**
        挨个取一遍 —— 走的是同一个 `data()`，展示规则仍只有一份，不会与列级角色漂移。
        `bg` 取列 1 只为拿行底色（`_bg` 与列无关）。
        """
        out: list[dict[str, Any]] = []
        for row_index in range(len(self._rows)):
            cell = self.index(row_index, 0)
            out.append(
                {
                    "row": row_index,
                    "name": self.data(cell, _ROW_NAME),
                    "buyText": self.data(cell, _BUY_TEXT),
                    "sellText": self.data(cell, _SELL_TEXT),
                    "riseText": self.data(cell, _RISE_TEXT),
                    "iconUrl": self.data(cell, _ICON_URL),
                    "bg": self.data(self.index(row_index, 1), _BG),
                }
            )
        return out

    def refresh_colors(self) -> None:
        """主题切换 / 价格变化后补发 dataChanged（颜色都是算出来的字符串）。"""
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, self.columnCount() - 1),
            list(ROLE_NAMES),
        )

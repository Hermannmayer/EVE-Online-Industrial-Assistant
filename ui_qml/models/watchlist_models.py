"""关注列表的列定义与表格模型（零 QtWidgets）。

原先在 `ui_pyside6/views/watchlist_view.py`，QML 侧复用同一份展示规则。
"""

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor

from core.constants import TRADE_HUB_IDS
from ui_qml.icon_cache import load_item_icon
from ui_qml.theme import registry as theme

#: 区域 id → 交易中心名（原在 `watchlist_view`）
_REGION_LABELS = {v: k for k, v in TRADE_HUB_IDS.items()}


COLUMNS = [
    ("图标", 50),
    ("中文名", 140),
    ("英文名", 160),
    ("区域", 80),
    ("买价 ↓", 110),
    ("卖价 ↑", 110),
    ("差价%", 80),
    ("买价阈值", 100),
    ("卖价阈值", 100),
    ("备注", 140),
]


class WatchlistTableModel(QAbstractTableModel):
    """关注列表表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._price_changes: dict[int, dict] = {}

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_price_changes(self, changes: dict[int, dict]):
        """设置价格变化数据用于行高亮"""
        self._price_changes = changes

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return ""
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                pix = load_item_icon(row.get("type_id"), size=32)
                if pix is not None:
                    return pix
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (4, 5, 6, 7, 8):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:
                return QColor(theme.GREEN) if row.get("buy_price") else QColor(theme.TEXT_SECONDARY)
            elif col == 5:
                return QColor(theme.RED) if row.get("sell_price") else QColor(theme.TEXT_SECONDARY)
            elif col == 6:
                bp = row.get("buy_price")
                sp = row.get("sell_price")
                if bp and sp and bp > 0:
                    return QColor(theme.ACCENT_ORANGE)
                return QColor(theme.TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            # 价格变化高亮（优先于阈值触发）
            type_id = row.get("type_id")
            if type_id and type_id in self._price_changes:
                ch = self._price_changes[type_id]
                buy_up = ch.get("new_buy", 0) > ch.get("old_buy", 0)
                buy_down = ch.get("new_buy", 0) < ch.get("old_buy", 0)
                sell_up = ch.get("new_sell", 0) > ch.get("old_sell", 0)
                sell_down = ch.get("new_sell", 0) < ch.get("old_sell", 0)
                if buy_up or sell_up:
                    c = QColor(theme.ACCENT_GREEN)
                    c.setAlpha(50)
                    return c
                if buy_down or sell_down:
                    c = QColor(theme.ACCENT_RED)
                    c.setAlpha(50)
                    return c
            buy_thresh = row.get("buy_threshold")
            sell_thresh = row.get("sell_threshold")
            buy_price = row.get("buy_price")
            sell_price = row.get("sell_price")
            triggered = False
            if buy_thresh is not None and buy_price and buy_price <= buy_thresh:
                triggered = True
            if sell_thresh is not None and sell_price and sell_price >= sell_thresh:
                triggered = True
            if triggered:
                return QColor(theme.BG_SURFACE_LIGHT)
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)

        elif role == Qt.ItemDataRole.FontRole:
            from PySide6.QtGui import QFont

            if col in (4, 5, 6, 7, 8):
                return QFont("Consolas", 10)

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 1:
            return row.get("zh_name", "")  # type: ignore[no-any-return]
        elif col == 2:
            return row.get("en_name", "")  # type: ignore[no-any-return]
        elif col == 3:
            return _REGION_LABELS.get(row.get("region_id", 0), str(row.get("region_id", "")))
        elif col == 4:
            bp = row.get("buy_price")
            return f"{bp:,.2f}" if bp else "—"
        elif col == 5:
            sp = row.get("sell_price")
            return f"{sp:,.2f}" if sp else "—"
        elif col == 6:
            bp = row.get("buy_price")
            sp = row.get("sell_price")
            if bp and sp and bp > 0:
                spread = (sp - bp) / bp * 100
                return f"{spread:+.1f}%"
            return "—"
        elif col == 7:
            bt = row.get("buy_threshold")
            return f"{bt:,.2f}" if bt is not None else "—"
        elif col == 8:
            st = row.get("sell_threshold")
            return f"{st:,.2f}" if st is not None else "—"
        elif col == 9:
            return row.get("note", "")  # type: ignore[no-any-return]
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        return None


# ═══════════════════════════════════════
#  自动补全搜索线程
# ═══════════════════════════════════════

"""查询页的表格模型与展示规则（零 QtWidgets）。

原先都在 `ui_pyside6/views/query/query_search.py` —— 那个文件里还混着
SuggestionPopup（Widgets 悬浮候选）与页面级动作；随批次 6.0 把 QML 侧也要用的
部分拆到这里：列定义、表格模型、行格式化。
"""

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor, QFont

from ui_qml.icon_cache import load_item_icon
from ui_qml.theme import registry as theme

#: 表格里的图标列渲染尺寸
ICON_SIZE = 32
#: 默认区域（Jita 所在星系/The Forge）
DEFAULT_REGION_ID = 10000002

COLUMNS = [
    ("图标", 50),
    ("中文名", 140),
    ("英文名", 170),
    ("类别", 100),
    ("买单 ↓", 120),
    ("卖单 ↑", 120),
    ("均价", 90),
    ("体积 m³", 80),
]

SORT_KEYS = [None, "zh", "en", "group", "buy_val", "sell_val", "avg_price_val", "vol_val"]


class QueryTableModel(QAbstractTableModel):
    """查询结果表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self._sort_col = -1
        self.endResetModel()

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
                pix = load_item_icon(row.get("type_id"), size=ICON_SIZE)
                if pix is not None:
                    return pix
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 4, 5, 6, 7):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:
                return QColor(theme.GREEN) if row.get("buy_str") != "—" else QColor(theme.TEXT_SECONDARY)
            elif col == 5:
                return QColor(theme.RED) if row.get("sell_str") != "—" else QColor(theme.TEXT_SECONDARY)
            elif col == 6:
                return QColor(theme.GREEN) if row.get("avg_price_str") != "—" else QColor(theme.TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            if row.get("is_inverted"):
                return QColor(theme.BG_HOVER)
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)

        elif role == Qt.ItemDataRole.FontRole:
            if col in (1, 4, 5, 6, 7):
                font = QFont("Consolas", 10)
                return font

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 1:
            return row.get("zh", "")  # type: ignore[no-any-return]
        elif col == 2:
            return row.get("en", "")  # type: ignore[no-any-return]
        elif col == 3:
            return row.get("group", "")  # type: ignore[no-any-return]
        elif col == 4:
            return row.get("buy_str", "—")  # type: ignore[no-any-return]
        elif col == 5:
            return row.get("sell_str", "—")  # type: ignore[no-any-return]
        elif col == 6:
            return row.get("avg_price_str", "—")  # type: ignore[no-any-return]
        elif col == 7:
            return row.get("vol_str", "—")  # type: ignore[no-any-return]
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = COLUMNS[section][0]
            if section == self._sort_col:
                arrow = " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
                label = label.rstrip(" ↓↑") + arrow
            return label
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        sk = SORT_KEYS[column] if column < len(SORT_KEYS) else None
        if sk is None:
            return

        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        if sk in ("buy_val", "sell_val", "avg_price_val", "vol_val", "type_id"):
            self._rows.sort(key=lambda r: r.get(sk, 0) or 0, reverse=reverse)
        else:
            self._rows.sort(key=lambda r: (r.get(sk, "") or "").lower(), reverse=reverse)

        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    def get_row(self, row_idx: int) -> dict | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None


# ═══════════════════════════════════════
#  Workers
# ═══════════════════════════════════════


def format_search_rows(rows: list, is_fallback: bool) -> list[dict]:
    """将数据库返回的行格式化为表格模型所需的字典列表"""
    parsed = []
    for row in rows:
        if is_fallback:
            tid, zh, en, zhg, eng, vol = row[:6]
            buy_p = sell_p = None
            buy_v = sell_v = 0
        else:
            tid, zh, en, en_group, zh_group, volume, buy_p, sell_p, buy_v, sell_v = row
            buy_v = buy_v or 0
            sell_v = sell_v or 0
            vol = volume or 0.0

        group = (zh_group or en_group or "—") if not is_fallback else (zhg or eng or "—")

        buy_str = "—"
        if buy_p is not None and buy_v > 0:
            buy_str = f"{buy_p:,.2f} ({buy_v:,})"
        elif buy_p is not None:
            buy_str = f"{buy_p:,.2f}"

        sell_str = "—"
        if sell_p is not None and sell_v > 0:
            sell_str = f"{sell_p:,.2f} ({sell_v:,})"
        elif sell_p is not None:
            sell_str = f"{sell_p:,.2f}"

        avg_price_str = "—"
        avg_price_val = 0.0
        if buy_p is not None and sell_p is not None:
            avg_price_val = (buy_p + sell_p) / 2
            avg_price_str = f"{avg_price_val:,.2f}"
        elif buy_p is not None:
            avg_price_val = buy_p
            avg_price_str = f"{buy_p:,.2f}"
        elif sell_p is not None:
            avg_price_val = sell_p
            avg_price_str = f"{sell_p:,.2f}"

        buy_val = buy_p if buy_p is not None else 0.0
        sell_val = sell_p if sell_p is not None else 0.0
        is_inverted = buy_p is not None and sell_p is not None and buy_p > sell_p

        parsed.append(
            {
                "type_id": tid,
                "zh": zh or "",
                "en": en or "",
                "group": group,
                "buy_str": buy_str,
                "sell_str": sell_str,
                "buy_val": buy_val,
                "sell_val": sell_val,
                "avg_price_str": avg_price_str,
                "avg_price_val": avg_price_val,
                "vol_str": f"{vol:,.2f}" if vol > 0 else "—",
                "vol_val": vol,
                "is_inverted": is_inverted,
            }
        )
    return parsed


# ═══════════════════════════════════════
#  上下文菜单辅助
# ═══════════════════════════════════════

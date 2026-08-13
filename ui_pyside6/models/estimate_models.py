"""估价页面 — 表格模型"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import load_item_icon

ICON_SIZE = 32

# ── 表格列定义 ──
_COLUMNS = [
    ("图标", 50),
    ("名字", 160),
    ("数量", 70),
    ("单价", 110),
    ("卖价合计", 120),
    ("买价合计", 120),
    ("体积 m³", 80),
]

_SORT_KEYS = [None, "name", "qty", "unit_price", "sell_total", "buy_total", "volume"]


class EstimateTableModel(QAbstractTableModel):
    """估价表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._discount: float = 1.0

    def set_discount(self, discount: float):
        self._discount = discount
        if self._rows:
            self._recalc_totals()
            top_left = self.index(0, 3)
            bottom_right = self.index(len(self._rows) - 1, 6)
            self.dataChanged.emit(top_left, bottom_right)

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self._sort_col = -1
        self._recalc_totals()
        self.endResetModel()

    def _recalc_totals(self):
        for row in self._rows:
            sell_unit = row.get("sell_price", 0) or 0
            buy_unit = row.get("buy_price", 0) or 0
            qty = row.get("qty", 0)
            row["unit_price"] = sell_unit * self._discount  # 默认显示卖价
            row["sell_total"] = sell_unit * qty * self._discount
            row["buy_total"] = buy_unit * qty * self._discount
            row["volume"] = (row.get("_volume", 0) or 0) * qty

    def add_row(self, row_data: dict):
        idx = len(self._rows)
        self.beginInsertRows(QModelIndex(), idx, idx)
        self._rows.append(row_data)
        self._sort_col = -1
        self.endInsertRows()
        self._recalc_totals()
        top_left = self.index(idx, 0)
        bottom_right = self.index(idx, 6)
        self.dataChanged.emit(top_left, bottom_right)

    def remove_row(self, row_idx: int):
        if 0 <= row_idx < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row_idx, row_idx)
            self._rows.pop(row_idx)
            self.endRemoveRows()

    def clear_all(self):
        self.beginResetModel()
        self._rows.clear()
        self._sort_col = -1
        self.endResetModel()

    def get_rows(self) -> list[dict]:
        return list(self._rows)

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(_COLUMNS)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 2:  # 数量列可编辑
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 2:
            return False
        if role == Qt.ItemDataRole.EditRole:
            try:
                qty = int(value)
                if qty <= 0:
                    return False
                self._rows[index.row()]["qty"] = qty
                self._recalc_totals()
                self.dataChanged.emit(index, self.index(index.row(), 6))
                return True
            except (ValueError, TypeError):
                return False
        return False

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                pix = load_item_icon(row.get("type_id"), size=ICON_SIZE)
                if pix is not None:
                    return pix
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (2, 3, 4, 5, 6):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:  # 卖价合计 → green
                return QColor(theme.GREEN)
            elif col == 5:  # 买价合计 → red
                return QColor(theme.RED)
            elif col == 3:  # 单价
                return QColor(theme.GREEN)

        elif role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 0:
            return ""
        elif col == 1:
            return row.get("name", "?")  # type: ignore[no-any-return]
        elif col == 2:
            return f"{row.get('qty', 0):,}"
        elif col == 3:
            up = row.get("unit_price", 0) or 0
            return f"{up:,.2f}" if up else "---"
        elif col == 4:
            st = row.get("sell_total", 0) or 0
            return f"{st:,.2f}" if st else "---"
        elif col == 5:
            bt = row.get("buy_total", 0) or 0
            return f"{bt:,.2f}" if bt else "---"
        elif col == 6:
            vol = row.get("volume", 0) or 0
            return f"{vol:,.2f}" if vol else "---"
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section < len(_COLUMNS):
                label = _COLUMNS[section][0]
                if section == self._sort_col:
                    arrow = " ↓" if self._sort_order == Qt.SortOrder.DescendingOrder else " ↑"
                    return label + arrow
                return label
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if column < 0 or column >= len(_SORT_KEYS):
            return
        key = _SORT_KEYS[column]
        if key is None:
            return
        self._sort_col = column
        self._sort_order = order
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=lambda r: r.get(key, 0) or 0, reverse=reverse)
        self.layoutChanged.emit()

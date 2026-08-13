"""合同市场 — 表格模型 + 客户端过滤器（列表 / 物品）"""

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import load_item_icon

# ── 合同类型 / 状态中文映射 ──
CONTRACT_TYPE_CN = {
    "item_exchange": "物品交换",
    "auction": "拍卖",
    "courier": "运输",
}

CONTRACT_STATUS_CN = {
    "outstanding": "进行中",
    "in_progress": "已接受",
    "finished_issuer": "已完成",
    "finished_contractor": "已完成",
    "cancelled": "已取消",
    "expired": "已过期",
    "deleted": "已删除",
    "reversed": "已逆转",
}

# ── 合同列表列定义（列名, 默认宽） ──
_CONTRACT_COLUMNS = [
    ("合同ID", 90),
    ("类型", 80),
    ("标题", 200),
    ("价格 (ISK)", 120),
    ("抵押 (ISK)", 120),
    ("体积 (m³)", 90),
    ("运输天数", 70),
    ("状态", 80),
    ("签发日期", 140),
    ("过期日期", 140),
]

_CONTRACT_SORT_KEYS = [
    "contract_id",
    "type",
    "title",
    "price",
    "collateral",
    "volume",
    "days_completed",
    "status",
    "date_issued",
    "date_expired",
]


class ContractTableModel(QAbstractTableModel):
    """合同列表表格模型"""

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
        return len(_CONTRACT_COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 3, 4, 5, 6):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 3:  # 价格
                price = row.get("price", 0)
                return QColor(theme.GREEN) if price > 0 else QColor(theme.TEXT_SECONDARY)
            elif col == 4:  # 抵押
                coll = row.get("collateral", 0)
                return QColor(theme.ACCENT_ORANGE) if coll > 0 else QColor(theme.TEXT_SECONDARY)
            elif col == 7:  # 状态
                status = row.get("status", "")
                if status in ("outstanding", "in_progress"):
                    return QColor(theme.GREEN)
                elif status in ("cancelled", "expired", "deleted"):
                    return QColor(theme.RED)
                return QColor(theme.TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)

        elif role == Qt.ItemDataRole.FontRole:
            if col in (0, 3, 4, 5, 6):
                return QFont("Consolas", 10)

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 0:
            return str(row.get("contract_id", ""))
        elif col == 1:
            raw = row.get("type", "")
            return CONTRACT_TYPE_CN.get(raw, raw)  # type: ignore[no-any-return]
        elif col == 2:
            return row.get("title", "") or "—"
        elif col == 3:
            v = row.get("price", 0)
            return f"{v:,.2f}" if v else "—"
        elif col == 4:
            v = row.get("collateral", 0)
            return f"{v:,.2f}" if v else "—"
        elif col == 5:
            v = row.get("volume", 0)
            return f"{v:,.1f}" if v else "—"
        elif col == 6:
            v = row.get("days_completed", 0)
            return str(v) if v else "—"
        elif col == 7:
            raw = row.get("status", "")
            return CONTRACT_STATUS_CN.get(raw, raw)  # type: ignore[no-any-return]
        elif col == 8:
            return row.get("date_issued", "") or "—"
        elif col == 9:
            return row.get("date_expired", "") or "—"
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = _CONTRACT_COLUMNS[section][0]
            if section == self._sort_col:
                arrow = " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
                label = label.rstrip(" ↓↑") + arrow
            return label
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        if column < 0 or column >= len(_CONTRACT_SORT_KEYS):
            return
        sk = _CONTRACT_SORT_KEYS[column]
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder
        if sk in ("contract_id", "price", "collateral", "volume", "days_completed"):
            self._rows.sort(key=lambda r: r.get(sk, 0) or 0, reverse=reverse)
        else:
            self._rows.sort(key=lambda r: (r.get(sk, "") or "").lower(), reverse=reverse)
        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    def get_row(self, idx: int) -> dict | None:
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None


# ── 合同内物品列表列定义 ──
_ITEM_COLUMNS = [
    ("物品 ID", 80),
    ("中文名", 160),
    ("英文名", 160),
    ("数量", 80),
    ("蓝图复制品", 80),
    ("包含", 60),
    ("ME", 50),
    ("PE", 50),
]


class ContractItemTableModel(QAbstractTableModel):
    """合同内物品表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(_ITEM_COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display(row, col)
        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:  # 物品 ID 列 — 显示图标
                pix = load_item_icon(row.get("type_id"), size=32)
                if pix is not None:
                    return pix
                return None
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 3, 4, 6, 7):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 3:
                return QColor(theme.PRIMARY)
        elif role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)
        elif role == Qt.ItemDataRole.FontRole:
            if col in (0, 3):
                return QFont("Consolas", 10)
        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 0:
            return str(row.get("type_id", ""))
        elif col == 1:
            return row.get("zh_name", "") or "—"
        elif col == 2:
            return row.get("en_name", "") or "—"
        elif col == 3:
            return str(row.get("quantity", 0))
        elif col == 4:
            return "是" if row.get("is_blueprint_copy") else "否"
        elif col == 5:
            return "是" if row.get("is_included", True) else "否"
        elif col == 6:
            v = row.get("material_efficiency", 0)
            return str(v) if v else "—"
        elif col == 7:
            v = row.get("time_efficiency", 0)
            return str(v) if v else "—"
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _ITEM_COLUMNS[section][0]
        return None


class ContractFilterProxy(QSortFilterProxyModel):
    """合同列表实时过滤器 — 按名称/价格/买卖类型"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._min_price = 0.0
        self._max_price = 0.0  # 0 = unlimited
        self._buy_sell = "全部"
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_search_text(self, text: str) -> None:
        self._search_text = text
        self.invalidateFilter()

    def set_price_range(self, min_p: float, max_p: float) -> None:
        self._min_price = min_p
        self._max_price = max_p
        self.invalidateFilter()

    def set_buy_sell(self, mode: str) -> None:
        self._buy_sell = mode
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        model = self.sourceModel()
        if not model:
            return True
        idx = model.index(source_row, 0, source_parent)
        row = idx.data(Qt.ItemDataRole.UserRole)
        if not row:
            return True

        # 1. 标题搜索
        if self._search_text:
            title = (row.get("title", "") or "").lower()
            if self._search_text.lower() not in title:
                return False

        # 2. 价格区间
        price = row.get("price", 0) or 0
        if self._min_price > 0 and price < self._min_price:
            return False
        if self._max_price > 0 and price > self._max_price:
            return False

        # 3. 买卖类型
        if self._buy_sell != "全部":
            ctype = row.get("type", "")
            if self._buy_sell == "我要买":
                if ctype not in ("item_exchange", "auction"):
                    return False
            elif self._buy_sell == "我要卖":
                if ctype != "item_exchange":
                    return False

        return True

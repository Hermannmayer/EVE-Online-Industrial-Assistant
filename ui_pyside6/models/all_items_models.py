"""全物品市场 — 表格模型 + 排序代理"""

from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

import ui_pyside6.theme as theme
from ui_pyside6.icon_cache import load_item_icon

DASH = chr(8212)

BCOLS = [
    ("图标", 36, "i"),
    ("中文名", 160, "z"),
    ("English", 180, "e"),
    ("买价", 100, "bp"),
    ("卖价", 100, "sp"),
    ("均价", 85, "ap"),
    ("体积", 70, "v"),
]
MCOLS = [
    ("成本", 105, "mc"),
    ("收入", 105, "mr"),
    ("产能/天", 65, "mh"),
    ("日利润", 100, "mdp"),
    ("状态", 110, "ms"),
    ("收益", 75, "_tag"),
    ("利润率%", 70, "mm"),
]
TCOLS = [("花费", 105, "tc"), ("收入", 105, "tr"), ("收益", 75, "_tag"), ("利润率%", 70, "tm"), ("每方利率", 90, "tpm")]


class AModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._cols = BCOLS[:]

    def set_rows(self, r):
        self.beginResetModel()
        self._rows = r
        self.endResetModel()

    def set_cols(self, c):
        self.beginResetModel()
        self._cols = c
        self.endResetModel()

    def rowCount(self, p=None):
        return len(self._rows)

    def columnCount(self, p=None):
        return len(self._cols)

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid():
            return None
        r = self._rows[idx.row()]
        _, _, k = self._cols[idx.column()]
        v = r.get(k)
        if role == Qt.ItemDataRole.DisplayRole:
            if k in ("bp", "sp", "ap", "mc", "mr", "tc", "tr"):
                return f"{v:,.2f}" if isinstance(v, int | float) and v is not None else DASH
            if k in ("_tag",):
                return v or DASH
            if k in ("mm", "tm", "tpm", "mdp", "_tag_sort"):
                return f"{float(v):,.1f}" if v is not None else DASH
            if k == "mh":
                return f"{v:.2f}" if isinstance(v, int | float) and v else DASH
            if k == "ms":
                s = {"no_blueprint": "无蓝图", "no_price": "无价格", "no_materials": "无材料", "no_depth": "市场无买单"}
                return s.get(v, v) or DASH
            if k in ("z", "e"):
                return v or ""
            if k == "v":
                return f"{v:,.2f}" if v else DASH
            return str(v) if v is not None else ""
        if role == Qt.ItemDataRole.DecorationRole and k == "i":
            pix = load_item_icon(r.get("id"), size=30)
            if pix is not None:
                return pix
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if k not in ("i", "z", "e", "ms"):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole:
            if k == "_tag":
                tag = str(v or "")
                if tag.endswith("S"):
                    return QColor(theme.ACCENT_GREEN)
                if tag.endswith("A"):
                    return QColor(theme.PRIMARY)
                if tag.endswith("B"):
                    return QColor(theme.ACCENT_YELLOW)
                if tag.endswith("C"):
                    return QColor(theme.ACCENT_ORANGE)
                if tag.endswith("D") and not tag.startswith("✗"):
                    return QColor(theme.ACCENT_RED)
            if k in ("mm", "tm"):
                vf = float(r.get(k, 0) or 0)
                if vf > 0:
                    return QColor(theme.ACCENT_GREEN)
                elif vf < 0:
                    return QColor(theme.ACCENT_RED)
        if role == Qt.ItemDataRole.UserRole:
            return r
        return None

    def headerData(self, s, o, r=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and r == Qt.ItemDataRole.DisplayRole and s < len(self._cols):
            return self._cols[s][0]
        return None


class Proxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        lv = str(left.data() or "")
        rv = str(right.data() or "")
        # 收益列按等级排序: S > A > B > C > D > ✗
        _rank = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "✗": 0}
        lr = next((_rank[k] for k in _rank if k in lv), -1)
        rr = next((_rank[k] for k in _rank if k in rv), -1)
        if lr >= 0 and rr >= 0:
            return lr < rr
        try:
            ln = float(lv.replace(",", "").replace(DASH, "0"))
            rn = float(rv.replace(",", "").replace(DASH, "0"))
            return ln < rn
        except Exception:
            return lv < rv

"""对比结果的数据模型与格式化（零 QtWidgets）。

`CompareTableModel` 原先在 `ui_pyside6/views/compare/compare_models.py`，
同一文件里还混着对话框的 QSS 构建；随批次 6.0 把「模型 + 纯格式化」拆出来，
因为 QML 侧（`ui_qml/models/compare_qml_model.py`）也要用这一份展示规则。
QSS 那一半留在原处（它只服务 Widgets 对话框）。
"""

import os

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor, QIcon

from core.paths import ICON_DIR
from ui_qml.theme import registry as theme

COMPARE_COLS_MFG = [
    ("物品", 160, "name"),
    ("成本", 100, "cost"),
    ("收入", 100, "revenue"),
    ("利润", 100, "profit"),
    ("利润率%", 70, "margin"),
    ("评分", 60, "score"),
    ("时均ISK/h", 100, "isk_per_hour"),
    ("产能/天", 70, "runs_per_day"),
    ("状态", 90, "status"),
]

COMPARE_COLS_TRADE = [
    ("物品", 160, "name"),
    ("买入", 100, "buy_cost"),
    ("卖出", 100, "sell_revenue"),
    ("毛利", 100, "gross_profit"),
    ("利润率%", 70, "margin"),
    ("评分", 60, "score"),
    ("每方利率", 90, "profit_per_m3"),
    ("状态", 90, "status"),
]

COMPARE_COLS_REACTION = COMPARE_COLS_MFG  # 反应与制造结构一致


class CompareTableModel(QAbstractTableModel):
    """对比结果表格模型"""

    def __init__(self, mode: str = "mfg"):
        super().__init__()
        self._rows: list[dict] = []
        self._mode = mode
        self._cols = self._get_cols()

    def _get_cols(self) -> list[tuple]:
        if self._mode == "trade":
            return COMPARE_COLS_TRADE
        if self._mode == "reaction":
            return COMPARE_COLS_REACTION
        return COMPARE_COLS_MFG

    def set_mode(self, mode: str):
        self.beginResetModel()
        self._mode = mode
        self._cols = self._get_cols()
        self.endResetModel()

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(self._cols)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        _, _, key = self._cols[index.column()]
        value = row.get(key)

        if role == Qt.ItemDataRole.DecorationRole:
            if key == "name":
                type_id = row.get("type_id")
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        return QIcon(icon_path)
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if key == "name":
                return value or ""
            if key in ("cost", "revenue", "profit", "buy_cost", "sell_revenue", "gross_profit"):
                return _format_isk(value) if isinstance(value, int | float) and value is not None else "—"
            if key == "margin":
                return f"{value:.1f}%" if value is not None else "—"
            if key == "score":
                return f"{value:.1f}" if isinstance(value, int | float) and value else "—"
            if key == "isk_per_hour":
                return _format_isk(value) if isinstance(value, int | float) and value else "—"
            if key == "profit_per_m3":
                return _format_isk(value) if isinstance(value, int | float) and value else "—"
            if key == "runs_per_day":
                return f"{value:.1f}" if isinstance(value, int | float) and value else "—"
            if key == "status":
                tips = {
                    "no_blueprint": "无蓝图",
                    "no_price": "无价格",
                    "no_materials": "无材料",
                    "no_depth": "市场无买单",
                }
                return tips.get(value, value) if value else "—"
            return str(value) if value is not None else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key not in ("name",):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "profit":
                v = value or 0
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "margin":
                v = float(value or 0)
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "gross_profit":
                v = value or 0
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "status":
                if value and value != "":
                    return QColor(theme.ACCENT_RED)

        if role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section < len(self._cols):
                return self._cols[section][0]
        return None

    def get_export_data(self) -> list[list]:
        """导出 CSV 数据"""
        header = [col[0] for col in self._cols]
        rows = []
        for row in self._rows:
            row_data = []
            for _, _, key in self._cols:
                val = row.get(key)
                if val is None:
                    row_data.append("")
                elif isinstance(val, float):
                    row_data.append(f"{val:.2f}")
                else:
                    row_data.append(str(val))
            rows.append(row_data)
        return [header] + rows


def _format_isk(value: float) -> str:
    """格式化 ISK 金额"""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"

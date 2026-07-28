"""
对比数据模型 — CompareTableModel + 格式化辅助函数 + 样式表构建
"""

import os

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor, QIcon

import ui_pyside6.theme as theme
from core.paths import ICON_DIR

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
                return _format_isk(value) if isinstance(value, (int, float)) and value is not None else "—"
            if key == "margin":
                return f"{value:.1f}%" if value is not None else "—"
            if key == "score":
                return f"{value:.1f}" if isinstance(value, (int, float)) and value else "—"
            if key == "isk_per_hour":
                return _format_isk(value) if isinstance(value, (int, float)) and value else "—"
            if key == "profit_per_m3":
                return _format_isk(value) if isinstance(value, (int, float)) and value else "—"
            if key == "runs_per_day":
                return f"{value:.1f}" if isinstance(value, (int, float)) and value else "—"
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


def _fmt_tag(daily_profit: float, veto: str = "") -> str:
    """将日均利润格式化为等级标签"""
    if veto:
        return "✗"
    if daily_profit >= 50_000_000:
        return f"{daily_profit / 100_000_000:.1f}亿 S"
    if daily_profit >= 10_000_000:
        return f"{daily_profit / 10_000:.0f}万 A"
    if daily_profit >= 1_000_000:
        return f"{daily_profit / 10_000:.0f}万 B"
    if daily_profit >= 100_000:
        return f"{daily_profit / 10_000:.0f}万 C"
    return f"{daily_profit / 10_000:.0f}万 D"


# ═══════════════════════════════════════════
#  主题相关样式表构建
# ═══════════════════════════════════════════


def build_dialog_stylesheet():
    """构建对话框主样式表"""
    return f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"


def build_search_input_stylesheet():
    """构建搜索框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 8px;"
    )


def build_primary_btn_stylesheet():
    """构建主按钮样式表"""
    return (
        f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
        f"border:none;border-radius:4px;padding:4px 12px;font-size:11px;}}"
        f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
    )


def build_item_list_stylesheet():
    """构建物品列表样式表"""
    return (
        f"QListWidget{{background:{theme.BG_SURFACE};border:1px solid {theme.BORDER};"
        f"border-radius:4px;font-size:11px;}}"
        f"QListWidget::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
        f"QListWidget::item:hover{{background:{theme.BG_HOVER};}}"
    )


def build_combo_stylesheet():
    """构建下拉框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 6px;font-size:11px;"
    )


def build_spin_stylesheet():
    """构建数字输入框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px;"
    )


def build_compare_btn_stylesheet():
    """构建对比按钮样式表"""
    return (
        f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
        f"border:none;border-radius:4px;padding:5px 16px;font-size:12px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
        f"QPushButton:disabled{{background:{theme.TEXT_SECONDARY};color:{theme.BG_SURFACE};}}"
    )


def build_export_btn_stylesheet():
    """构建导出按钮样式表"""
    return (
        f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 12px;font-size:11px;}}"
        f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.PRIMARY};}}"
    )


def build_status_stylesheet():
    """构建状态栏样式表"""
    return f"color:{theme.TEXT_SECONDARY};font-size:11px;"


def build_progress_stylesheet():
    """构建进度条样式表"""
    return (
        f"QProgressBar{{background:{theme.BG_SURFACE};border:none;border-radius:1px;height:3px;}}"
        f"QProgressBar::chunk{{background:{theme.PRIMARY};border-radius:1px;}}"
    )


def build_label_stylesheet():
    """构建标签样式表"""
    return f"color:{theme.TEXT_SECONDARY};font-size:11px;"


def build_clear_btn_stylesheet():
    """构建清空按钮样式表"""
    return (
        f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 8px;font-size:10px;}}"
        f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.ACCENT_RED};}}"
    )


def build_table_stylesheet():
    """构建表格样式表"""
    return (
        f"QTableView{{background:{theme.BG_DARK};alternate-background-color:{theme.BG_SURFACE};"
        f"border:1px solid {theme.BORDER};border-radius:4px;gridline-color:{theme.BORDER};"
        f"selection-background-color:{theme.PRIMARY};selection-color:{theme.TEXT_BRIGHT};outline:none;}}"
        f"QTableView::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
        f"QTableView::item:selected{{background:{theme.PRIMARY};color:{theme.TEXT_BRIGHT};}}"
        f"QHeaderView::section{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"padding:4px 6px;border:none;border-right:1px solid {theme.BORDER};"
        f"border-bottom:1px solid {theme.BORDER};font-weight:bold;font-size:11px;}}"
        f"QHeaderView::section:hover{{background:{theme.BG_HOVER};}}"
    )

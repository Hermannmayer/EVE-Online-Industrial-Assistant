"""
产出总表 — 查看所有生产计划的成本/利润概况
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container

_STATUS_MAP = {
    "pending": "待开始",
    "in_progress": "进行中",
    "running": "运行中",
    "completed": "已完成",
    "cancelled": "已取消",
}


class OutputSummaryDialog(QWidget):
    """产出总表对话框"""

    _COLUMNS = ["产品名称", "数量", "成本", "售价", "利润", "利润率%", "状态"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("产出总表")
        self.setMinimumSize(700, 500)
        self.setMaximumSize(1100, 800)
        self._setup_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self._status_label = QLabel("正在加载...")
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        layout.addWidget(self._table)
        layout.addWidget(self._status_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.load_data()

    def load_data(self):
        """查询所有生产计划，计算成本/利润"""
        self._table.setRowCount(0)

        conn_ctx = get_container().db.connect("user")
        conn = conn_ctx.__enter__()
        try:
            plans = conn.execute(
                "SELECT product_name, product_type_id, runs, parallels, "
                "material_cost, profit, margin, status "
                "FROM production_plans ORDER BY created_at DESC"
            ).fetchall()
        finally:
            conn_ctx.__exit__(None, None, None)

        if not plans:
            self._status_label.setText("没有生产计划")
            return

        self._table.setRowCount(len(plans))
        total_profit = 0.0

        for row_idx, plan in enumerate(plans):
            name = plan[0] or str(plan[1])
            runs = plan[2] or 1
            parallels = plan[3] or 1
            material_cost = plan[4] or 0.0
            profit = plan[5] or 0.0
            margin = plan[6] or 0.0
            status_raw = plan[7] or "pending"

            quantity = runs * parallels
            cost = material_cost * runs * parallels
            sell_price = cost + profit
            margin_pct = margin * 100 if margin else (profit / cost * 100 if cost > 0 else 0.0)
            status_text = _STATUS_MAP.get(status_raw, status_raw)

            items = [
                name,
                str(quantity),
                _fmt_isk(cost),
                _fmt_isk(sell_price),
                _fmt_isk(profit),
                f"{margin_pct:.1f}%",
                status_text,
            ]
            total_profit += profit

            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # 利润着色
                if col_idx == 4:
                    if profit > 0:
                        item.setForeground(theme.ACCENT_GREEN)
                    elif profit < 0:
                        item.setForeground(theme.ACCENT_RED)
                # 状态着色
                if col_idx == 6:
                    if status_raw in ("completed",):
                        item.setForeground(theme.ACCENT_GREEN)
                    elif status_raw in ("cancelled",):
                        item.setForeground(theme.ACCENT_RED)
                    elif status_raw in ("in_progress", "running"):
                        item.setForeground(theme.PRIMARY)
                self._table.setItem(row_idx, col_idx, item)

        total = len(plans)
        self._status_label.setText(f"共 {total} 个计划，总利润 {_fmt_isk(total_profit)}")

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


def _fmt_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"

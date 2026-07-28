"""
产出总表 — 查看所有生产计划的产出数量、价值、利润，含材料溢出信息

每个计划展开 BOM 树，计算中间产品制造成批时的批量溢出（surplus）。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.plan_aggregator import calculate_output_with_overflow

_STATUS_MAP = {
    "pending": "待开始",
    "in_progress": "进行中",
    "running": "运行中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
    "cancelled": "已取消",
    "paused": "已暂停",
}


class OutputSummaryDialog(QDialog):
    """产出总表对话框"""

    _COLUMNS = ["计划名称", "产出物品", "计划数量", "产出价值", "成本", "利润", "利润率", "材料溢出", "状态"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("产出总表")
        self.setMinimumSize(900, 550)
        self.setMaximumSize(1400, 900)
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
        """查询所有生产计划，计算产出价值 + 溢出"""
        self._table.setRowCount(0)

        with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
            # 1) 所有计划
            plan_rows = conn.execute(
                "SELECT id, product_type_id, product_name, runs, parallels, "
                "material_cost, profit, margin, market_margin, status, me_level "
                "FROM production_plans ORDER BY created_at DESC"
            ).fetchall()

            if not plan_rows:
                self._status_label.setText("没有生产计划")
                return

            plans = [
                {
                    "id": r[0],
                    "product_type_id": r[1],
                    "product_name": r[2],
                    "runs": r[3] or 1,
                    "parallels": r[4] or 1,
                    "material_cost": r[5] or 0.0,
                    "profit": r[6] or 0.0,
                    "margin": r[7] or 0.0,
                    "market_margin": r[8] or r[7] or 0.0,
                    "status": r[9] or "pending",
                    "me_level": r[10] or 0,
                }
                for r in plan_rows
            ]

            # 2) 计算产出 + 溢出
            output_results = calculate_output_with_overflow(conn, plans)

        # 3) 填充表格
        self._table.setRowCount(len(output_results))
        total_value = 0.0
        total_profit = 0.0
        overflow_plan_count = 0

        for row_idx, result in enumerate(output_results):
            name = result["plan_name"]
            pid = result["product_type_id"]
            qty = result["total_qty"]
            plan_value = result["plan_value"]
            cost = result["material_cost"]
            profit = result["profit"]
            margin = result["margin_pct"]
            overflow_text = result["overflow_text"]
            status_raw = result["status"]
            status_text = _STATUS_MAP.get(status_raw, status_raw)

            if result["has_overflow"]:
                overflow_plan_count += 1

            total_value += plan_value
            total_profit += profit

            items = [
                name,
                str(pid),  # 产出物品名称在 name 列已经显示了
                f"{qty:,}",
                _fmt_isk(plan_value),
                _fmt_isk(cost),
                _fmt_isk(profit),
                f"{margin:.1f}%" if margin else "—",
                overflow_text,
                status_text,
            ]

            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # 利润着色
                if col_idx == 5:
                    if profit > 0:
                        item.setForeground(QColor(theme.ACCENT_GREEN))
                    elif profit < 0:
                        item.setForeground(QColor(theme.ACCENT_RED))

                # 状态着色
                if col_idx == 8:
                    if status_raw in ("completed", "done"):
                        item.setForeground(QColor(theme.ACCENT_GREEN))
                    elif status_raw in ("cancelled",):
                        item.setForeground(QColor(theme.ACCENT_RED))
                    elif status_raw in ("in_progress", "running"):
                        item.setForeground(QColor(theme.PRIMARY))
                    elif status_raw == "ready":
                        item.setForeground(QColor(theme.ACCENT_ORANGE))

                # 溢出信息着色（有溢出时用橙色高亮）
                if col_idx == 7 and result["has_overflow"]:
                    item.setForeground(QColor(theme.ACCENT_ORANGE))

                self._table.setItem(row_idx, col_idx, item)

        total = len(output_results)
        self._status_label.setText(
            f"共 {total} 个计划，总产出价值 {_fmt_isk(total_value)}，"
            f"总利润 {_fmt_isk(total_profit)}，"
            f"{overflow_plan_count} 个计划存在材料溢出"
        )

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

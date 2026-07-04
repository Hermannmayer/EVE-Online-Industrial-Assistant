
"""成本明细 — 从 PlanTable 右键打开查看核算"""

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
from services.scoring_service import calc_manufacturing_score

_COLUMNS = ["材料", "基础量", "ME效率", "实际量", "单价", "小计"]


class CostBreakdownDialog(QWidget):
    """成本明细对话框"""

    def __init__(self, plan_data: dict, parent: QWidget | None = None, char_config: dict | None = None):
        super().__init__(parent)
        self._plan = plan_data
        self._char_config = char_config or {}
        product_name = plan_data.get("product_name", "未知产品")
        self.setWindowTitle(f"核算 - {product_name}")
        self.setMinimumSize(750, 500)
        self.setMaximumSize(1100, 800)
        self._setup_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._status_label = QLabel("正在加载...")
        layout.addWidget(self._status_label)
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._summary_label)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_data()

    def _load_data(self):
        self._table.setRowCount(0)
        type_id = self._plan.get("product_type_id")
        if not type_id:
            self._status_label.setText("缺少 type_id")
            return
        me = self._plan.get("me_level", 0) or 0
        te = self._plan.get("te_level", 0) or 0
        mat_hub = self._plan.get("mat_hub", "Jita")
        sell_hub = self._plan.get("sell_hub", "Jita")
        char_config = self._char_config or {}
        result = calc_manufacturing_score(
            type_id=type_id, char_config=char_config, bp_me=me, bp_te=te,
            mat_source_hub=mat_hub, sell_hub=sell_hub, facility_tax_pct=0.0,
            price_type_mat="sell", price_type_prod="sell",
        )
        status = result.get("status", "")
        if status:
            tips = {"no_blueprint": "未找到蓝图", "no_price": "无价格数据", "no_materials": "无需材料"}
            self._status_label.setText(tips.get(status, f"状态: {status}"))
            self._summary_label.setText("")
            return
        materials = result.get("materials", [])
        self._table.setRowCount(len(materials))
        for row_idx, mat in enumerate(materials):
            items = [
                mat.get("name", ""), str(mat.get("base_qty", 0)),
                f"{mat.get('waste_factor', 1):.2f}", f"{mat.get('qty', 0):,.2f}",
                _fmt_isk(mat.get("unit_price", 0)), _fmt_isk(mat.get("subtotal", 0)),
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row_idx, col_idx, item)
        bd = result.get("breakdown", {})
        mat_cost = sum(m.get("subtotal", 0) for m in materials)
        profit = result.get("profit_per_run", 0) or 0
        margin = result.get("margin_pct", 0) or 0
        score = result.get("score", 0) or 0
        isk_per_hour = result.get("isk_per_hour", 0) or 0
        result.get("cost_per_unit", 0) or 0
        hours = result.get("hours_per_run", 0) or 1
        facility_fee = bd.get("facility_fee", 0) or 0
        broker_init = bd.get("broker_init", 0) or 0
        broker_relist = bd.get("broker_relist", 0) or 0
        sales_tax = bd.get("sales_tax", 0) or 0
        revenue = bd.get("revenue", 0) or 0
        material_cost_val = bd.get("material_cost", 0) or 0
        sep40 = "=" * 40
        sep36 = "=" * 36
        lines = [
            f"  {sep40}", f"  材料费: {_fmt_isk(mat_cost)} ({material_cost_val:,.0f} ISK)",
            f"  安装费: {_fmt_isk(facility_fee)}", f"  经纪人(挂单): {_fmt_isk(broker_init)}",
            f"  经纪人(改单): {_fmt_isk(broker_relist)}", f"  销售税: {_fmt_isk(sales_tax)}",
            f"  {sep36}",
        ]
        cost_data = mat_cost + facility_fee + broker_init + broker_relist + sales_tax
        lines += [
            f"  总成本: {_fmt_isk(cost_data)}", f"  收入: {_fmt_isk(revenue)}",
            f"  利润: {_fmt_isk(profit)}", f"  利润率: {margin:.2f}%",
            f"  耗时: {hours:.2f}h/run", f"  日产能: {24/hours:.2f}run/天",
            f"  日利润: {_fmt_isk(profit * 24 / hours)}/天", f"  {sep40}",
            f"  评分: {score:.1f}", f"  ISK/h: {_fmt_isk(isk_per_hour)}",
        ]
        self._summary_label.setText("\n".join(lines))
        self._status_label.setText(
            f"共 {len(materials)} 种材料 | 评分 {score:.1f} | 利润 {_fmt_isk(profit)} | 利润率 {margin:.1f}%"
        )

    def _on_theme_changed(self):
        self.setStyleSheet(f"QWidget {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}")
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {theme.BG_DARK}; alternate-background-color: {theme.BG_SURFACE};"
            f"  border: 1px solid {theme.BORDER}; border-radius: 4px; gridline-color: {theme.BORDER};"
            f"  selection-background-color: {theme.BG_SURFACE_LIGHT};}}"
            f"QHeaderView::section {{"
            f"  background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER}; padding: 4px 8px; font-weight: bold;}}"
            f"QTableWidget::item {{ padding: 2px 6px;}}"
        )
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._summary_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px;"
            f"background-color: {theme.BG_SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 8px;"
        )


def _fmt_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"

"""成本明细 — 从 PlanTable 右键打开查看核算"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container

_COLUMNS = ["材料", "基础量", "损耗率", "实际量", "单价", "小计"]


class CostBreakdownDialog(QWidget):
    """成本明细对话框"""

    def __init__(
        self,
        plan_data: dict,
        parent: QWidget | None = None,
        char_config: dict | None = None,
        *,
        price_type_mat: str | None = None,
        price_type_prod: str | None = None,
    ):
        super().__init__(parent)
        self._plan = plan_data
        self._price_type_mat = price_type_mat
        self._price_type_prod = price_type_prod
        # 优先使用传入的角色配置；否则按计划角色的 char_name 解析
        if char_config is not None:
            self._char_config = char_config
        else:
            plan_char = (plan_data.get("char_name") or "").strip()
            if plan_char:
                from services.char_config_resolver import resolve_char_config

                self._char_config = resolve_char_config(char_name=plan_char) or {}
            else:
                self._char_config = {}
        product_name = plan_data.get("product_name", "未知产品")
        self.setWindowTitle(f"核算 — {product_name}")
        self.setMinimumSize(800, 600)
        self.resize(960, 720)
        self._setup_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _setup_ui(self):
        # ── root scroll ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)

        root = QVBoxLayout(inner)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ── 状态栏 ──────────────────────────────────────────
        self._status_label = QLabel("正在加载…")
        root.addWidget(self._status_label)

        # ── 双列: 左侧材料 | 右侧核算 ──────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # ── 左侧: 材料清单 ──────────────────────────────────
        mat_box = QGroupBox("材料清单")
        mat_layout = QVBoxLayout(mat_box)
        mat_layout.setContentsMargins(6, 6, 6, 6)
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        mat_layout.addWidget(self._table)
        splitter.addWidget(mat_box)

        # ── 右侧: 核算明细 ─────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # ── 2. 制造作业费 ───────────────────────────────────
        job_box = QGroupBox("制造作业费")
        self._job_form = QFormLayout(job_box)
        self._job_form.setContentsMargins(8, 6, 8, 6)
        self._job_form.setSpacing(2)
        self._job_eiv = QLabel("—")
        self._job_form.addRow("预估物品价值 (EIV):", self._job_eiv)
        self._job_sci = QLabel("—")
        self._job_form.addRow("系统成本 (SCI × EIV):", self._job_sci)
        self._job_fac_tax = QLabel("—")
        self._job_form.addRow("设施税:", self._job_fac_tax)
        self._job_scc = QLabel("—")
        self._job_form.addRow("SCC 附加费:", self._job_scc)
        self._job_total = QLabel("—")
        self._job_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")
        self._job_form.addRow("制造作业费:", self._job_total)
        right_layout.addWidget(job_box)

        # ── 3. 市场费用 ─────────────────────────────────────
        mkt_box = QGroupBox("市场费用")
        self._mkt_form = QFormLayout(mkt_box)
        self._mkt_form.setContentsMargins(8, 6, 8, 6)
        self._mkt_form.setSpacing(2)
        self._mkt_broker = QLabel("—")
        self._mkt_form.addRow("经纪人费:", self._mkt_broker)
        self._mkt_relist = QLabel("—")
        self._mkt_form.addRow("改单费:", self._mkt_relist)
        self._mkt_sales_tax = QLabel("—")
        self._mkt_form.addRow("销售税:", self._mkt_sales_tax)
        self._mkt_fee_total = QLabel("—")
        self._mkt_fee_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")
        self._mkt_form.addRow("市场费用合计:", self._mkt_fee_total)
        right_layout.addWidget(mkt_box)

        # ── 4. 汇总 ─────────────────────────────────────────
        summary_box = QGroupBox("汇总")
        self._summary_form = QFormLayout(summary_box)
        self._summary_form.setContentsMargins(8, 6, 8, 6)
        self._summary_form.setSpacing(2)
        self._summary_labels: dict[str, QLabel] = {}
        for key, label in [
            ("total_cost", "总成本"),
            ("revenue", "收入"),
            ("profit", "利润"),
            ("margin", "利润率"),
            ("hours", "耗时"),
            ("daily_output", "日产能"),
            ("daily_profit", "日利润"),
            ("score", "评分"),
            ("iskph", "ISK/h"),
        ]:
            val = QLabel("—")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._summary_form.addRow(f"{label}:", val)
            self._summary_labels[key] = val
        right_layout.addWidget(summary_box)
        right_layout.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([580, 360])
        splitter.setStretchFactor(0, 3)  # 材料表多占
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)  # stretch=1 充满

        # ── 填充外层 ────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_data()

    def _load_data(self):
        self._table.setRowCount(0)
        type_id = self._plan.get("product_type_id")
        if not type_id:
            self._status_label.setText("缺少 type_id")
            return

        runs = max(int(self._plan.get("runs", 1)), 1)
        parallels = max(int(self._plan.get("parallels", 1)), 1)
        total_mult = runs * parallels

        # 统一调用 calculate_plan_metrics()，与主表批量重算路径一致
        metrics = (
            get_container()
            .scoring_service()
            .calculate_plan_metrics(
                self._plan,
                self._char_config or {},
                price_type_mat=self._price_type_mat,
                price_type_prod=self._price_type_prod,
            )
        )

        material_cost = metrics.get("material_cost", 0)
        profit = metrics.get("profit", 0)
        margin = metrics.get("margin", 0)
        score = metrics.get("score", 0) or 0
        isk_per_hour = metrics.get("iskph", 0)
        hours = metrics.get("calculated_time", 0) / 3600 if metrics.get("calculated_time") else 0
        daily_output = metrics.get("daily_output", 0)

        # 从 calc_manufacturing_score 的 breakdown 获取费用明细
        per_run = (
            get_container()
            .scoring_service()
            .calc_manufacturing_score(
                type_id=type_id,
                char_config=self._char_config or {},
                bp_me=self._plan.get("me_level", 0) or 0,
                bp_te=self._plan.get("te_level", 0) or 0,
                mat_source_hub=self._plan.get("mat_hub", "Jita"),
                sell_hub=self._plan.get("sell_hub", "Jita"),
                facility_tax_pct=(
                    (self._char_config or {})
                    .get("market", {})
                    .get((self._plan.get("sell_hub", "Jita")).lower(), {})
                    .get("facility_tax", 0.0)
                ),
                price_type_mat=self._price_type_mat or "sell",
                price_type_prod=self._price_type_prod or "sell",
            )
        )
        status = per_run.get("status", "")
        if status:
            tips = {"no_blueprint": "未找到蓝图", "no_price": "无价格数据", "no_materials": "无需材料"}
            self._status_label.setText(tips.get(status, f"状态: {status}"))
            return

        materials = per_run.get("materials", [])
        self._table.setRowCount(len(materials))
        for row_idx, mat in enumerate(materials):
            items = [
                mat.get("name", ""),
                str(mat.get("base_qty", 0)),
                _fmt_waste_pct(mat.get("waste_factor", 1)),
                f"{mat.get('qty', 0) * total_mult:,.2f}",
                _fmt_isk(mat.get("unit_price", 0)),
                _fmt_isk(mat.get("subtotal", 0) * total_mult),
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row_idx, col_idx, item)

        bd = per_run.get("breakdown", {})
        eiv = bd.get("eiv", 0) or 0
        system_cost = bd.get("system_cost", 0) or 0
        installation_fee = bd.get("installation_fee", 0) or 0
        facility_tax_v = bd.get("facility_tax", 0) or 0
        scc = bd.get("scc_surcharge", 0) or 0
        broker_init = bd.get("broker_init", 0) or 0
        broker_relist = bd.get("broker_relist", 0) or 0
        sales_tax = bd.get("sales_tax", 0) or 0
        revenue = bd.get("revenue", 0) or 0
        sci = bd.get("sci", 0) or 0

        # ── 顶部信息 ──
        self._status_label.setText(
            f"计划设定: {runs} 流程 × {parallels} 并行 = {total_mult} 总流程 "
            f"| 共 {len(materials)} 种材料 | 评分 {score:.1f} | 利润 {_fmt_isk(profit)} | 利润率 {margin:.1f}%"
        )

        # ── 制造作业费 ──
        self._job_eiv.setText(_fmt_isk(eiv))
        self._job_sci.setText(f"{_fmt_isk(system_cost * total_mult)}  (SCI={sci*100:.4f}%)")
        self._job_fac_tax.setText(_fmt_isk(facility_tax_v * total_mult))
        self._job_scc.setText(_fmt_isk(scc * total_mult))
        self._job_total.setText(_fmt_isk(installation_fee * total_mult))

        # ── 市场费用 ──
        self._mkt_broker.setText(_fmt_isk(broker_init * total_mult))
        self._mkt_relist.setText(_fmt_isk(broker_relist * total_mult))
        self._mkt_sales_tax.setText(_fmt_isk(sales_tax * total_mult))
        self._mkt_fee_total.setText(_fmt_isk((broker_init + broker_relist + sales_tax) * total_mult))

        # ── 汇总 ──
        self._summary_labels["total_cost"].setText(_fmt_isk(round(material_cost, 2)))
        self._summary_labels["revenue"].setText(_fmt_isk(revenue * total_mult))
        p_label = self._summary_labels["profit"]
        p_label.setText(_fmt_isk(profit))
        p_label.setStyleSheet(f"color: {theme.GREEN if profit >= 0 else theme.RED}; font-weight: bold;")
        self._summary_labels["margin"].setText(f"{margin:.2f}%")
        self._summary_labels["hours"].setText(f"{hours:.2f}h")
        self._summary_labels["daily_output"].setText(f"{daily_output:.1f} 件/天")
        daily_profit = profit / hours * 24 if hours > 0 else 0
        self._summary_labels["daily_profit"].setText(_fmt_isk(daily_profit))
        self._summary_labels["score"].setText(f"{score:.1f}")
        self._summary_labels["iskph"].setText(_fmt_isk(isk_per_hour))

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px; font-weight: bold;")
        self._job_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")
        self._mkt_fee_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")


def _fmt_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def _fmt_waste_pct(waste_factor: float) -> str:
    """Convert waste multiplier to waste percentage display, e.g. 1.10 -> 10%, 1.00 -> 0%."""
    pct = (waste_factor - 1) * 100
    return f"{pct:.0f}%"

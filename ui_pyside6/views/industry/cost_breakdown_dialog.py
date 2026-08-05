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

_COLUMNS = ["材料", "基础量", "材料减成%", "实际量", "单价", "小计"]


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
        self._job_research = QLabel("—")
        self._job_research.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._job_form.addRow("拷贝/发明研究成本:", self._job_research)
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

        try:
            self._load_data_inner(type_id)
        except Exception as e:
            # showEvent 中未捕获异常会导致 Qt 事件循环崩溃（闪退）。
            # 兜底：显示错误信息而非崩溃。
            from core.logger import log

            log.exception("成本明细加载失败: %s", self._plan.get("product_name"))
            self._status_label.setText(f"⚠ 加载失败: {e}")

    def _load_data_inner(self, type_id: int):
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

        # 拆解母项：自制子项按其制造价（材料+作业费）计入成本，而非市场买入价
        sub_cost_map: dict[int, float] = {}
        try:
            gid = self._plan.get("group_id") or self._plan.get("group_number")
            my_lvl = int(self._plan.get("sub_level") or self._plan.get("child_level") or 0)
            if gid:
                sub_cost_map = self._compute_subitem_costs(gid, my_lvl)
        except Exception:
            from core.logger import log

            log.exception("计算拆解子项成本失败: %s", self._plan.get("product_name"))
            sub_cost_map = {}
        if sub_cost_map:
            from services.scoring_service import ScoringService

            adj_mat, adj_profit, adj_margin, _ = ScoringService.adjust_mother_metrics(
                metrics, sub_cost_map, total_mult
            )
            material_cost = adj_mat
            profit = adj_profit
            margin = adj_margin
        else:
            material_cost = metrics.get("material_cost", 0)
            profit = metrics.get("profit", 0)
            margin = metrics.get("margin", 0)
        score = metrics.get("score", 0) or 0
        isk_per_hour = metrics.get("iskph", 0)
        hours = metrics.get("calculated_time", 0) / 3600 if metrics.get("calculated_time") else 0
        daily_output = metrics.get("daily_output", 0)

        # 统一从 calculate_plan_metrics 的结果取 breakdown/材料/状态（避免双重解析不一致，
        # 也确保明细与主表利润使用相同的机库结构加成/设施税）
        status = metrics.get("status", "")
        if status:
            tips = {"no_blueprint": "未找到蓝图", "no_price": "无价格数据", "no_materials": "无需材料"}
            self._status_label.setText(tips.get(status, f"状态: {status}"))
            return

        from services.manufacturing_calculator import calc_material_for_runs

        materials = metrics.get("materials", [])
        structure_mat_saving = metrics.get("structure_mat_saving", 1.0)
        self._table.setRowCount(len(materials))
        for row_idx, mat in enumerate(materials):
            base = mat.get("base_qty", 0)
            # 单件材料(基础量≤1)不受ME影响
            if base <= 1:
                total_qty = base * total_mult
            else:
                wf = mat.get("wastefactor", 10) or 10
                me = self._plan.get("me_level", 0) or 0
                total_qty = calc_material_for_runs(base, wf, me, total_mult, structure_mat_saving=structure_mat_saving)
            mid = mat.get("type_id")
            if mid in sub_cost_map:
                # 自制子项：单价 = 子项制造价 / 本计划总需求，小计 = 子项制造价
                sub_total = sub_cost_map[mid]
                unit_price = sub_total / total_qty if total_qty > 0 else 0.0
                name_display = f"{mat.get('name', '')}（自制）"
            else:
                unit_price = mat.get("unit_price", 0) or 0
                sub_total = unit_price * total_qty
                name_display = mat.get("name", "")
            items = [
                name_display,
                str(base),
                _fmt_material_saving(total_qty, base, total_mult),
                f"{total_qty:,.0f}",
                _fmt_isk(unit_price),
                _fmt_isk(sub_total),
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row_idx, col_idx, item)

        bd = metrics.get("breakdown", {})
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
            f"计划设定: {parallels} 并行 × {runs} 流程 = {total_mult} 总流程 "
            f"| 共 {len(materials)} 种材料 | 评分 {score:.1f} | 利润 {_fmt_isk(profit)} | 利润率 {margin:.1f}%"
        )

        # ── 制造作业费 ──
        self._job_eiv.setText(_fmt_isk(eiv))
        # 展示实际使用的星系（快照/材料机库推导），帮助确认 SCI 按哪个星系计算
        sys_id = metrics.get("solar_system_id")
        sys_name = ""
        if sys_id:
            from services.name_resolver import resolve_system_name

            with get_container().db.connect("ref") as conn:
                sys_name = resolve_system_name(conn, sys_id)
        sci_label = f"SCI={sci * 100:.4f}%"
        if sys_name:
            sci_label += f"（{sys_name}）"
        self._job_sci.setText(f"{_fmt_isk(system_cost * total_mult)}  ({sci_label})")
        self._job_fac_tax.setText(_fmt_isk(facility_tax_v * total_mult))
        self._job_scc.setText(_fmt_isk(scc * total_mult))
        self._job_total.setText(_fmt_isk(installation_fee * total_mult))
        research_cost = bd.get("research_cost", 0) or 0
        self._job_research.setText(
            _fmt_isk(research_cost * total_mult) if research_cost else "—（无，原图或 T1 无需研究）"
        )

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

    def _compute_subitem_costs(self, group_number: int, deeper_than: int) -> dict[int, float]:
        """读同组更深子项产线，返回 {子项 product_type_id: 制造价合计（材料+作业费）}。

        自底向上按 sub_level 降序计算：最深子项先算，父层用子层调整后的成本，
        支持嵌套拆解。制造价经 ScoringService.child_manufacturing_cost 含子项制造作业费。
        """
        from services.scoring_service import ScoringService

        with get_container().db.connect("user") as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM production_plans WHERE group_number=? AND sub_level>? "
                    "ORDER BY sub_level DESC, id DESC",
                    (group_number, deeper_than),
                ).fetchall()
            ]
        if not rows:
            return {}
        for p in rows:
            p["group_id"] = p.get("group_number", 0)
            p["child_level"] = p.get("sub_level", 0)

        svc = get_container().scoring_service()
        cost_by_id: dict[int, float] = {}
        for p in rows:
            metrics = svc.calculate_plan_metrics(
                p,
                self._char_config or {},
                price_type_mat=self._price_type_mat,
                price_type_prod=self._price_type_prod,
            )
            lvl = int(p.get("sub_level") or 0)
            kids = [c for c in rows if int(c.get("sub_level") or 0) > lvl]
            if kids:
                child_map = {
                    int(k.get("product_type_id") or 0): cost_by_id.get(int(k.get("id") or 0), 0.0)
                    for k in kids
                }
                total_mult = max(int(p.get("runs", 1)), 1) * max(int(p.get("parallels", 1)), 1)
                adj_mat, _, _, _ = ScoringService.adjust_mother_metrics(metrics, child_map, total_mult)
                metrics = dict(metrics)
                metrics["material_cost"] = adj_mat
            cost_by_id[int(p.get("id") or 0)] = ScoringService.child_manufacturing_cost(p, metrics)
        return {int(p.get("product_type_id") or 0): cost_by_id.get(int(p.get("id") or 0), 0.0) for p in rows}

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px; font-weight: bold;")
        self._job_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")
        self._mkt_fee_total.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY};")


def _fmt_isk(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _fmt_material_saving(total_qty: int, base_qty: int, total_mult: int) -> str:
    """材料减成百分比：按总量计算 (1 - total_with_ME / total_without_ME)"""
    total_base = base_qty * total_mult
    if total_base <= 0:
        return "0%"
    pct = (1 - total_qty / total_base) * 100
    return f"{pct:.1f}%"

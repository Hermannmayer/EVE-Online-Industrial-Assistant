"""
生产计划管理 — 统一页面
"""

from datetime import datetime, timezone

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog
from ui_pyside6.models.industry_models import MaterialTableModel, PlanTableModel, RankTableModel
from ui_pyside6.views.compare_dialog import CompareDialog
from ui_pyside6.views.procurement_tab import ProcurementTab
from ui_pyside6.workers.industry_workers import RankWorker, ScoreWorker, SearchWorker

# ════════════════════════════════════════════════════
#  DB
# ════════════════════════════════════════════════════

PLAN_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_type_id INTEGER NOT NULL,
    product_name TEXT,
    blueprint_type_id INTEGER,
    runs INTEGER DEFAULT 1,
    parallels INTEGER DEFAULT 1,
    me_level INTEGER DEFAULT 0,
    te_level INTEGER DEFAULT 0,
    mat_hub TEXT DEFAULT 'Jita',
    sell_hub TEXT DEFAULT 'Jita',
    facility TEXT DEFAULT '',
    char_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    profit REAL DEFAULT 0,
    margin REAL DEFAULT 0,
    score REAL DEFAULT 0,
    material_cost REAL DEFAULT 0,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT
);
"""


def init_plan_db():
    try:
        with get_container().db.connect("user") as conn:
            conn.executescript(PLAN_DB_SCHEMA)
            for col, col_type in [("iskph", "REAL DEFAULT 0"), ("material_cost", "REAL DEFAULT 0")]:
                try:
                    conn.execute(f"ALTER TABLE production_plans ADD COLUMN {col} {col_type}")
                except Exception:
                    pass
    except Exception:
        pass


PROCUREMENT_DB_SCHEMA = """CREATE TABLE IF NOT EXISTS procurement_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    item_name TEXT,
    quantity INTEGER DEFAULT 1,
    hub TEXT DEFAULT 'Jita',
    priority TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def init_procurement_db():
    try:
        with get_container().db.connect("user") as conn:
            conn.executescript(PROCUREMENT_DB_SCHEMA)
            # 兼容旧表：添加可能缺失的列
            for col in [("status", "TEXT DEFAULT 'pending'"),
                       ("ordered_at", "TEXT"),
                       ("received_at", "TEXT")]:
                try:
                    conn.execute(f"ALTER TABLE procurement_items ADD COLUMN {col[0]} {col[1]}")
                except Exception:
                    pass
    except Exception:
        pass


# ════════════════════════════════════════════════════
#  Main Page
# ════════════════════════════════════════════════════


class IndustryPage(QWidget):
    """生产计划管理统一页面 — 3 Tab"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        init_procurement_db()
        self.setObjectName("industry_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── QTabWidget ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        self._tabs.addTab(self._build_tab_calc(), "制造计算")
        self._tabs.addTab(self._build_tab_rank(), "利润排行")
        self._tabs.addTab(self._build_tab_plan(), "生产计划")
        self._procurement_tab = ProcurementTab(self)
        self._tabs.addTab(self._procurement_tab, "代采购")

        layout.addWidget(self._tabs)

        # ── 状态 ──
        self._ps_selected: dict | None = None
        self._rank_results: list[dict] = []
        self.load_plans()

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")
        self._preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._score_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        for lbl in self._profit_labels.values():
            lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        self._rank_status.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._plan_count.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._mat_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._mat_summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

    # ═══════════════════════════════════
    #  Tab 0: 制造计算
    # ═══════════════════════════════════

    def _build_tab_calc(self) -> QWidget:
        """搜索 + 评分 + 利润卡片"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶栏
        bar = QWidget()
        bar.setObjectName("industry_toolbar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        # 第1行：搜索 + 蓝图参数 + 区域 + 操作
        r1 = QHBoxLayout()

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索成品名（如 渡鸦级） → 计算利润 → 加入计划")
        self._search.textChanged.connect(self._on_search)
        r1.addWidget(self._search, 1)

        self._search_list = QListWidget()
        self._search_list.setMaximumHeight(160)
        self._search_list.setVisible(False)
        self._search_list.itemClicked.connect(self._on_search_click)

        r1.addWidget(QLabel("蓝图ME:"))
        self._me = QSpinBox()
        self._me.setRange(0, 10)
        self._me.setValue(0)
        r1.addWidget(self._me)

        r1.addWidget(QLabel("蓝图TE:"))
        self._te = QSpinBox()
        self._te.setRange(0, 20)
        self._te.setValue(0)
        r1.addWidget(self._te)

        r1.addWidget(QLabel("原料区域:"))
        self._mat_hub = QComboBox()
        self._mat_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._mat_hub.setCurrentText("Jita")
        r1.addWidget(self._mat_hub)

        r1.addWidget(QLabel("出售区域:"))
        self._sell_hub = QComboBox()
        self._sell_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._sell_hub.setCurrentText("Jita")
        r1.addWidget(self._sell_hub)

        r1.addWidget(QLabel("原料价:"))
        self._mat_price_type = QComboBox()
        self._mat_price_type.addItems(["卖价", "买价"])
        r1.addWidget(self._mat_price_type)

        r1.addWidget(QLabel("税%:"))
        self._tax = QLineEdit("0")
        self._tax.setFixedWidth(40)
        r1.addWidget(self._tax)

        self._calc_btn = QPushButton("计算")
        self._calc_btn.clicked.connect(self._on_calc)
        r1.addWidget(self._calc_btn)

        self._add_btn = QPushButton("加入计划")
        self._add_btn.setObjectName("ps_add_btn")
        self._add_btn.clicked.connect(self._on_add_plan)
        self._add_btn.setEnabled(False)
        r1.addWidget(self._add_btn)

        v.addLayout(r1)

        # 第2行：Runs + 预览
        r2 = QHBoxLayout()

        r2.addWidget(QLabel("Runs:"))
        self._runs = QSpinBox()
        self._runs.setRange(1, 1000)
        self._runs.setValue(1)
        r2.addWidget(self._runs)

        self._preview = QLabel("搜索物品 → 计算 → 加入生产计划")
        self._preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        r2.addWidget(self._preview, 1)

        v.addLayout(r2)
        layout.addWidget(bar)
        layout.addWidget(self._search_list)

        # 利润分析面板
        self._build_score_group(layout)

        layout.addStretch()
        return w

    def _build_score_group(self, layout):
        """评分结果面板：利润卡片 + 材料清单"""
        self._score_group = QGroupBox("利润分析")
        self._score_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._score_group.setVisible(False)

        gv = QVBoxLayout(self._score_group)
        gv.setSpacing(6)

        self._profit_grid = QFrame()
        grid = QGridLayout(self._profit_grid)
        grid.setSpacing(4)

        label_specs = [
            ("成品收入:", "revenue"),
            ("材料成本:", "material_cost"),
            ("安装费:", "facility_fee"),
            ("经纪人费:", "broker_fee"),
            ("销售税:", "sales_tax"),
            ("单次利润:", "profit"),
            ("利润率:", "margin_pct"),
            ("ISK/小时:", "isk_per_hour"),
        ]
        self._profit_labels = {}
        for i, (label, key) in enumerate(label_specs):
            row, col_pair = i % 4, i // 4
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            val = QLabel("—")
            val.setObjectName(f"profit_{key}")
            val.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
            grid.addWidget(lbl, row, col_pair * 2)
            grid.addWidget(val, row, col_pair * 2 + 1)
            self._profit_labels[key] = val

        gv.addWidget(self._profit_grid)

        self._scored_mat_table = QTableView()
        self._scored_mat_table.setAlternatingRowColors(True)
        self._scored_mat_table.setMaximumHeight(160)
        self._scored_mat_table.horizontalHeader().setStretchLastSection(True)
        self._scored_mat_table.verticalHeader().setDefaultSectionSize(22)
        gv.addWidget(self._scored_mat_table)

        layout.addWidget(self._score_group)

    # ═══════════════════════════════════
    #  Tab 1: 利润排行
    # ═══════════════════════════════════

    def _build_tab_rank(self) -> QWidget:
        """批量评分所有可制造物品，按利润排序"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 工具栏
        bar = QHBoxLayout()

        bar.addWidget(QLabel("原料区域:"))
        self._rank_mat_hub = QComboBox()
        self._rank_mat_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._rank_mat_hub.setCurrentText("Jita")
        bar.addWidget(self._rank_mat_hub)

        bar.addWidget(QLabel("出售区域:"))
        self._rank_sell_hub = QComboBox()
        self._rank_sell_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._rank_sell_hub.setCurrentText("Jita")
        bar.addWidget(self._rank_sell_hub)

        bar.addWidget(QLabel("原料价:"))
        self._rank_price_type = QComboBox()
        self._rank_price_type.addItems(["卖价", "买价"])
        bar.addWidget(self._rank_price_type)

        bar.addWidget(QLabel("ME:"))
        self._rank_me = QSpinBox()
        self._rank_me.setRange(0, 10)
        self._rank_me.setValue(0)
        bar.addWidget(self._rank_me)

        bar.addWidget(QLabel("TE:"))
        self._rank_te = QSpinBox()
        self._rank_te.setRange(0, 20)
        self._rank_te.setValue(0)
        bar.addWidget(self._rank_te)

        bar.addWidget(QLabel("税%:"))
        self._rank_tax = QLineEdit("0")
        self._rank_tax.setFixedWidth(40)
        bar.addWidget(self._rank_tax)

        bar.addWidget(QLabel("Top N:"))
        self._rank_top_n = QComboBox()
        self._rank_top_n.addItems(["20", "50", "100", "200", "全部"])
        self._rank_top_n.setCurrentText("100")
        bar.addWidget(self._rank_top_n)

        bar.addWidget(QLabel("排序:"))
        self._rank_sort = QComboBox()
        self._rank_sort.addItems(["时均 ISK/h", "利润/run", "利润率%", "评分"])
        bar.addWidget(self._rank_sort)

        self._rank_btn = QPushButton("开始排行")
        self._rank_btn.clicked.connect(self._on_rank_start)
        bar.addWidget(self._rank_btn)
        self._rank_compare_btn = QPushButton("批量对比选中")
        self._rank_compare_btn.clicked.connect(self._on_rank_compare)
        bar.addWidget(self._rank_compare_btn)

        bar.addStretch()
        layout.addLayout(bar)

        # 进度条 + 状态
        status_bar = QHBoxLayout()
        self._rank_progress = QProgressBar()
        self._rank_progress.setVisible(False)
        status_bar.addWidget(self._rank_progress)
        self._rank_status = QLabel("")
        self._rank_status.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        status_bar.addWidget(self._rank_status)
        status_bar.addStretch()
        layout.addLayout(status_bar)

        # 过滤栏
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("过滤:"))
        self._rank_filter = QComboBox()
        self._rank_filter.addItems(["全部", "T1 (利润率≥5%)", "T2 (利润率≥10%)", "利润率≥20%", "时均≥10M ISK/h"])
        self._rank_filter.currentTextChanged.connect(self._apply_rank_filter)
        filter_bar.addWidget(self._rank_filter)

        self._rank_sort.currentTextChanged.connect(self._apply_rank_filter)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        # 排列表
        self._rank_table = QTableView()
        self._rank_table.setAlternatingRowColors(True)
        self._rank_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._rank_table.setSortingEnabled(True)
        self._rank_table.horizontalHeader().setStretchLastSection(True)
        self._rank_table.verticalHeader().setDefaultSectionSize(22)
        self._rank_table.doubleClicked.connect(self._on_rank_double_click)
        layout.addWidget(self._rank_table, 1)

        return w

    # ═══════════════════════════════════
    #  Tab 2: 生产计划
    # ═══════════════════════════════════

    def _build_tab_plan(self) -> QWidget:
        """计划列表 + 材料汇总"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._del_btn = QPushButton("删除选中计划")
        self._del_btn.setObjectName("del_btn")
        self._del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._del_btn)

        self._refresh_btn = QPushButton("刷新材料汇总")
        self._refresh_btn.clicked.connect(self._refresh_material)
        btn_row.addWidget(self._refresh_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 计划表
        self._plan_table = QTableView()
        self._plan_table.setAlternatingRowColors(True)
        self._plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._plan_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._plan_table.horizontalHeader().setStretchLastSection(True)
        self._plan_table.setSortingEnabled(True)
        self._plan_table.verticalHeader().setDefaultSectionSize(26)
        layout.addWidget(self._plan_table, 1)

        # 统计 + 过滤
        stats = QHBoxLayout()
        self._plan_count = QLabel("")
        self._plan_count.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        stats.addWidget(self._plan_count)

        stats.addWidget(QLabel("  过滤:"))
        self._filter = QComboBox()
        self._filter.addItems(["全部", "待排产", "运行中", "已完成"])
        self._filter.currentTextChanged.connect(lambda: self.load_plans())
        stats.addWidget(self._filter)
        stats.addStretch()
        layout.addLayout(stats)

        # 材料汇总
        self._mat_group = QGroupBox("材料需求汇总（所有活跃计划）")
        self._mat_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        mv = QVBoxLayout(self._mat_group)
        mv.setContentsMargins(4, 4, 4, 4)
        mv.setSpacing(2)

        self._mat_table = QTableView()
        self._mat_table.setAlternatingRowColors(True)
        self._mat_table.horizontalHeader().setStretchLastSection(True)
        self._mat_table.setMaximumHeight(160)
        self._mat_table.verticalHeader().setDefaultSectionSize(22)
        mv.addWidget(self._mat_table)

        self._mat_summary = QLabel("")
        self._mat_summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        mv.addWidget(self._mat_summary)

        layout.addWidget(self._mat_group)
        return w

    # ═══════════════════════════════════
    #  搜索
    # ═══════════════════════════════════

    def _on_search(self, text: str):
        if not text.strip():
            self._search_list.setVisible(False)
            return
        w = SearchWorker(text.strip(), get_container().db, self)
        w.finished.connect(self._on_search_result)
        w.start()

    def _on_search_result(self, results: list):
        self._search_list.clear()
        if not results:
            self._search_list.addItem("无匹配")
            self._search_list.setVisible(True)
            return
        for r in results:
            name = r.get("zh_name") or r.get("en_name") or f"ID:{r['type_id']}"
            item = QListWidgetItem(f"[{r['type_id']}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._search_list.addItem(item)
        self._search_list.setVisible(True)

    def _on_search_click(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._search_list.setVisible(False)
        self._search.setText(data.get("zh_name") or data.get("en_name") or str(data["type_id"]))
        self._selected_tid = data["type_id"]
        self._selected_name = data.get("zh_name") or data.get("en_name") or f"ID:{data['type_id']}"
        self._preview.setText(f"已选: {self._selected_name} — 点「计算」查看利润")
        self._add_btn.setEnabled(False)
        # 自动触发计算
        self._on_calc()

    # ═══════════════════════════════════
    #  计算
    # ═══════════════════════════════════

    def _on_calc(self):
        if not hasattr(self, "_selected_tid"):
            self._preview.setText("请先选一个物品")
            return
        try:
            tax = float(self._tax.text() or "0")
        except ValueError:
            tax = 0.0
        self._preview.setText(f"正在计算 {self._selected_name}...")
        self._score_group.setVisible(False)

        mat_price_type = "sell" if self._mat_price_type.currentText() == "卖价" else "buy"
        w = ScoreWorker(
            self._selected_tid,
            self._me.value(),
            self._te.value(),
            self._mat_hub.currentText(),
            self._sell_hub.currentText(),
            tax,
            mat_price_type,
            self._runs.value(),
            self,
        )
        w.finished.connect(self._on_score)
        w.start()

    def _on_score(self, result: dict):
        self._ps_selected = result
        status = result.get("status", "")

        if status:
            self._preview.setText(f"{self._selected_name}: {status}")
            self._add_btn.setEnabled(False)
            self._score_group.setVisible(False)
            return

        bd = result.get("breakdown", {})
        profit = result.get("profit_per_run", 0)
        margin = result.get("margin_pct", 0)
        iskph = result.get("isk_per_hour", 0) or bd.get("isk_per_hour", 0)
        score = result.get("score", 0)
        runs = self._runs.value()
        profit_color = theme.GREEN if profit > 0 else theme.RED

        # 填充利润卡片
        revenue = bd.get("revenue", 0)
        mat_cost = bd.get("material_cost", 0)
        facility_fee = bd.get("facility_fee", 0)
        broker_fee = bd.get("broker_init", 0) + bd.get("broker_relist", 0)
        sales_tax = bd.get("sales_tax", 0)

        self._profit_labels["revenue"].setText(f"{revenue:,.0f} ISK")
        self._profit_labels["material_cost"].setText(f"{mat_cost:,.0f} ISK")
        self._profit_labels["facility_fee"].setText(f"{facility_fee:,.0f} ISK")
        self._profit_labels["broker_fee"].setText(f"{broker_fee:,.0f} ISK")
        self._profit_labels["sales_tax"].setText(f"{sales_tax:,.0f} ISK")
        self._profit_labels["profit"].setText(f"{profit:,.0f} ISK")
        self._profit_labels["profit"].setStyleSheet(f"color: {profit_color}; font-size: 12px; font-weight: bold;")
        self._profit_labels["margin_pct"].setText(f"{margin:.1f}%")
        self._profit_labels["margin_pct"].setStyleSheet(f"color: {profit_color}; font-size: 12px;")
        self._profit_labels["isk_per_hour"].setText(f"{iskph:,.0f} ISK/h")

        # 填充评分材料表（按 runs 倍数）
        materials = result.get("materials", [])
        mat_rows = []
        for m in materials:
            mat_rows.append(
                {
                    "name": m["name"],
                    "need": round(m["qty"] * runs, 2),
                    "price": m.get("unit_price", 0),
                    "total": round(m.get("subtotal", 0) * runs, 2),
                }
            )
        self._scored_mat_table.setModel(MaterialTableModel(mat_rows))

        self._score_group.setVisible(True)

        # 预览摘要
        self._preview.setText(
            f"{self._selected_name} | 评分: {score:.1f} | "
            f"利润: {profit:,.0f} ISK | 利润率: {margin:.1f}% | "
            f"时均: {iskph:,.0f} ISK/h"
        )
        self._preview.setStyleSheet(f"color: {profit_color}; font-size: 12px;")
        self._add_btn.setEnabled(True)

    # ═══════════════════════════════════
    #  加入计划
    # ═══════════════════════════════════

    def _on_add_plan(self):
        if not hasattr(self, "_selected_tid") or not self._ps_selected:
            return

        dlg = AddPlanDialog(self._selected_name, self._ps_selected, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return

        conn = get_container().db.direct_connect("user")
        try:
            iskph = self._ps_selected.get("isk_per_hour", 0) or self._ps_selected.get("breakdown", {}).get(
                "isk_per_hour", 0
            )
            mat_cost = self._ps_selected.get("breakdown", {}).get("material_cost", 0)

            conn.execute(
                """
                INSERT INTO production_plans
                (product_type_id, product_name, runs, parallels, me_level, te_level,
                 mat_hub, sell_hub, facility, char_name, status,
                 profit, margin, score, iskph, material_cost, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
                (
                    self._selected_tid,
                    self._selected_name,
                    data["runs"],
                    data["parallels"],
                    data["me"],
                    data["te"],
                    self._mat_hub.currentText(),
                    self._sell_hub.currentText(),
                    data["fac"],
                    data["char"],
                    self._ps_selected.get("profit_per_run", 0),
                    self._ps_selected.get("margin_pct", 0),
                    self._ps_selected.get("score", 0),
                    iskph,
                    mat_cost,
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._preview.setText(f"✅ {self._selected_name} 已加入生产计划")
        self._add_btn.setEnabled(False)
        self.load_plans()
        self._refresh_material()

    # ═══════════════════════════════════
    #  计划管理
    # ═══════════════════════════════════

    def load_plans(self):
        with get_container().db.connect("user") as conn:
            f = self._filter.currentText()
            sql = "SELECT * FROM production_plans"
            if f == "待排产":
                sql += " WHERE status = 'pending'"
            elif f == "运行中":
                sql += " WHERE status = 'running'"
            elif f == "已完成":
                sql += " WHERE status = 'done'"
            sql += " ORDER BY created_at DESC"
            c = conn.cursor()
            c.execute(sql)
            cols = [d[0] for d in c.description]
            rows = [dict(zip(cols, r)) for r in c.fetchall()]
            self._plan_model = PlanTableModel(rows)
            self._plan_table.setModel(self._plan_model)
            self._plan_count.setText(f"共 {len(rows)} 条计划")

    def _on_delete(self):
        sel = self._plan_table.selectionModel().selectedRows()
        if not sel:
            return
        ids = [self._plan_model._plans[r.row()]["id"] for r in sel]
        if (
            QMessageBox.question(
                self,
                "确认",
                f"删除 {len(ids)} 条计划？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        with get_container().db.connect("user") as conn:
            conn.executemany("DELETE FROM production_plans WHERE id = ?", [(i,) for i in ids])
        self.load_plans()
        self._refresh_material()

    # ═══════════════════════════════════
    #  材料汇总
    # ═══════════════════════════════════

    def _refresh_material(self):
        with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT product_type_id, runs, parallels FROM production_plans WHERE status IN ('pending', 'running')"
            )
            plans = c.fetchall()

            if not plans:
                self._mat_table.setModel(None)
                self._mat_summary.setText("无活跃计划")
                return

            material_map: dict[int, int] = {}
            for pid, runs, parallels in plans:
                c.execute(
                    """
                    SELECT bm.material_type_id, bm.quantity
                    FROM bp.blueprint_products bp
                    JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                        AND bm.activity = bp.activity
                    WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
                """,
                    (pid,),
                )
                for mid, qty in c.fetchall():
                    material_map[mid] = material_map.get(mid, 0) + qty * runs * parallels

            rows = []
            total = 0
            for mid, need in material_map.items():
                c.execute("SELECT zh_name, en_name FROM ref.item WHERE type_id = ?", (mid,))
                r = c.fetchone()
                name = (r[0] or r[1] or str(mid)) if r else str(mid)
                c.execute(
                    "SELECT sell_price FROM mkt.market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1",
                    (mid,),
                )
                pr = c.fetchone()
                price = pr[0] or 0 if pr else 0
                subtotal = need * price
                total += subtotal
                rows.append({"name": name, "need": need, "price": price, "total": subtotal})

            rows.sort(key=lambda x: x["total"], reverse=True)
            self._mat_table.setModel(MaterialTableModel(rows))
            self._mat_summary.setText(f"共 {len(rows)} 种材料 | 总成本: {total:,.0f} ISK")

    # ═══════════════════════════════════
    #  利润排行
    # ═══════════════════════════════════

    def _on_rank_start(self):
        """启动批量排行"""
        self._rank_btn.setEnabled(False)
        self._rank_progress.setVisible(True)
        self._rank_status.setText("正在评分所有可制造物品...")

        try:
            tax = float(self._rank_tax.text() or "0")
        except ValueError:
            tax = 0.0

        mat_price_type = "sell" if self._rank_price_type.currentText() == "卖价" else "buy"
        top_n_text = self._rank_top_n.currentText()
        top_n = None if top_n_text == "全部" else int(top_n_text)
        self._rank_worker = RankWorker(
            self._rank_mat_hub.currentText(),
            self._rank_sell_hub.currentText(),
            mat_price_type,
            self._rank_me.value(),
            self._rank_te.value(),
            tax,
            get_container().db,
            self,
            top_n=top_n,
        )
        self._rank_worker.progress.connect(self._on_rank_progress)
        self._rank_worker.result.connect(self._on_rank_result)
        self._rank_worker.done.connect(self._on_rank_done)
        self._rank_worker.start()

    def _on_rank_progress(self, current: int, total: int):
        self._rank_progress.setRange(0, total)
        self._rank_progress.setValue(current)
        self._rank_status.setText(f"已评分 {current}/{total}...")

    def _on_rank_result(self, results: list):
        """接收排行结果，补充名称后展示"""
        # 批量查名称
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            for r in results:
                tid = r.get("_type_id")
                if tid:
                    c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (tid,))
                    row = c.fetchone()
                    r["_name"] = (row[0] or row[1] or str(tid)) if row else str(tid)

        self._rank_results = results
        self._rank_btn.setEnabled(True)
        self._apply_rank_filter()

    def _on_rank_done(self, elapsed: float):
        self._rank_progress.setVisible(False)
        self._rank_status.setText(f"完成 {len(self._rank_results)} 项 | 耗时 {elapsed:.1f}s")
        self.update_status_bar()

    def _apply_rank_filter(self):
        """根据过滤条件筛选排行结果，并按选择排序"""
        if not self._rank_results:
            return
        ft = self._rank_filter.currentText()
        filtered = self._rank_results
        if "利润率≥5%" in ft:
            filtered = [r for r in filtered if r.get("margin_pct", 0) >= 5]
        elif "利润率≥10%" in ft:
            filtered = [r for r in filtered if r.get("margin_pct", 0) >= 10]
        elif "利润率≥20%" in ft:
            filtered = [r for r in filtered if r.get("margin_pct", 0) >= 20]
        elif "10M ISK/h" in ft:
            filtered = [r for r in filtered if r.get("isk_per_hour", 0) >= 10_000_000]

        # 按排序下拉框排序
        sort_key = self._rank_sort.currentText()
        sort_map = {
            "时均 ISK/h": lambda x: x.get("isk_per_hour", 0),
            "利润/run": lambda x: x.get("profit_per_run", 0),
            "利润率%": lambda x: x.get("margin_pct", 0),
            "评分": lambda x: x.get("score", 0),
        }
        key_fn = sort_map.get(sort_key, sort_map["时均 ISK/h"])
        filtered.sort(key=key_fn, reverse=True)
        self._rank_table.setModel(RankTableModel(filtered))

    def _on_rank_compare(self):
        """选中排行结果行，打开批量对比"""
        sel = self._rank_table.selectionModel().selectedRows()
        if not sel:
            return
        model = self._rank_table.model()
        if not isinstance(model, RankTableModel):
            return
        items = []
        for s in sel:
            row_data = model.get_row(s.row())
            tid = row_data.get("_type_id")
            name = row_data.get("_name", "")
            if tid:
                items.append({"type_id": tid, "name": name})
        dlg = CompareDialog(initial_items=items)
        dlg.show()

    def _on_rank_double_click(self, index: QModelIndex):
        """双击排行行 → 跳到制造计算 Tab 并自动计算"""
        model = self._rank_table.model()
        if not isinstance(model, RankTableModel):
            return
        row_data = model.get_row(index.row())
        tid = row_data.get("_type_id")
        name = row_data.get("_name", "")
        if not tid:
            return

        # 同步参数
        self._me.setValue(self._rank_me.value())
        self._te.setValue(self._rank_te.value())
        self._mat_hub.setCurrentText(self._rank_mat_hub.currentText())
        self._sell_hub.setCurrentText(self._rank_sell_hub.currentText())
        self._mat_price_type.setCurrentText(self._rank_price_type.currentText())
        self._tax.setText(self._rank_tax.text())

        # 填入搜索 → 跳转 → 计算
        self._search.setText(name)
        self._selected_tid = tid
        self._selected_name = name
        self._tabs.setCurrentIndex(0)
        self._on_calc()

    # ═══════════════════════════════════
    #  刷新
    # ═══════════════════════════════════

    def refresh_display(self):
        self.load_plans()
        self._refresh_material()
        if hasattr(self, "_procurement_tab"):
            self._procurement_tab.refresh()

    def update_status_bar(self):
        """更新主窗口状态栏显示利润排行统计"""
        count = len(self._rank_results) if hasattr(self, "_rank_results") else 0
        hub = self._rank_mat_hub.currentText() if hasattr(self, "_rank_mat_hub") else ""
        if self._main and hasattr(self._main, "statusBar"):
            self._main.statusBar().showMessage(f"利润排行: {count} 项, 区域: {hub}")

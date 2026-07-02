"""生产计划管理 — 统一页面（5 区布局）"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.container import get_container
from ui_pyside6.theme import (
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    add_theme_listener,
)
from ui_pyside6.views.industry import (
    ActionButtons,
    BlueprintRequirementsDialog,
    CharacterUsageDialog,
    GanttView,
    MaterialsSummaryDialog,
    OutputSummaryDialog,
    PlanTable,
    StatusBar,
    TopToolbar,
)
from ui_pyside6.views.manufacturable_items_dialog import ManufacturableItemsDialog

PLAN_DB_SCHEMA = """CREATE TABLE IF NOT EXISTS production_plans (
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
            # --- migration: production_plans 新字段 ---
            new_cols = [
                ("notes", "TEXT DEFAULT ''"),
                ("group_number", "INTEGER DEFAULT 0"),
                ("sub_level", "INTEGER DEFAULT 0"),
                ("facility", "TEXT DEFAULT ''"),
                ("output_location", "TEXT DEFAULT ''"),
                ("sell_hub", "TEXT DEFAULT 'Jita'"),
                ("market_margin", "REAL DEFAULT 0"),
                ("personal_margin", "REAL DEFAULT 0"),
                ("daily_output", "REAL DEFAULT 0"),
                ("materials_ready", "INTEGER DEFAULT 0"),
            ]
            # 保留已有迁移
            new_cols += [("iskph", "REAL DEFAULT 0"), ("material_cost", "REAL DEFAULT 0")]
            for col, col_type in new_cols:
                try:
                    conn.execute(f"ALTER TABLE production_plans ADD COLUMN {col} {col_type}")
                except Exception:
                    pass
            # --- price_snapshots 表 ---
            conn.executescript("""CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                region_id INTEGER NOT NULL,
                sell_price REAL,
                buy_price REAL,
                snapshot_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(type_id, region_id, snapshot_time)
            );""")
    except Exception:
        pass


class IndustryPage(QWidget):
    """生产计划管理统一页面 — 5 区布局"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        self.setObjectName("industry_page")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. 页面标题栏 ──────────────────────────────────────
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 12, 4)
        title_bar.setSpacing(12)
        self._title_label = QLabel("生产规划")
        title_bar.addWidget(self._title_label)
        self._plan_count = QLabel("")
        title_bar.addWidget(self._plan_count)
        title_bar.addStretch(1)
        root.addLayout(title_bar)

        # ── 2. 顶部工具栏 ──────────────────────────────────────
        self._toolbar = TopToolbar()
        root.addWidget(self._toolbar)

        # ── 3. 视图切换区域（数据表格 / 甘特图）──────────────────
        self._view_stack = QStackedWidget()

        # 页0: 数据视图（表格 + 添加按钮）
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(0)
        self._plan_table_widget = PlanTable()
        data_layout.addWidget(self._plan_table_widget, 1)
        bp_row = QHBoxLayout()
        bp_row.setContentsMargins(12, 4, 12, 4)
        self._btn_add_from_list = QPushButton("+ 从蓝图列表添加")
        bp_row.addWidget(self._btn_add_from_list)
        bp_row.addStretch(1)
        data_layout.addLayout(bp_row)
        self._view_stack.addWidget(data_page)

        # 页1: 甘特图
        self._gantt_view = GanttView()
        gantt_scroll = QScrollArea()
        gantt_scroll.setWidget(self._gantt_view)
        gantt_scroll.setWidgetResizable(True)
        gantt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view_stack.addWidget(gantt_scroll)

        root.addWidget(self._view_stack, 1)  # stretch=1 填充剩余空间

        # ── 4. 底部状态栏 ──────────────────────────────────────
        self._status_bar = StatusBar()
        root.addWidget(self._status_bar)

        # ── 5. 底部功能按钮 ────────────────────────────────────
        self._action_buttons = ActionButtons()
        root.addWidget(self._action_buttons)

        # ── 信号连接 ───────────────────────────────────────────
        self._connect_signals()

        # ── 初始加载 ───────────────────────────────────────────
        self.load_plans()

        # ── 主题 ───────────────────────────────────────────────
        add_theme_listener(self._on_theme_changed)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        # TopToolbar
        self._toolbar.refresh_requested.connect(self.load_plans)
        self._toolbar.filter_changed.connect(self.load_plans)
        self._toolbar.hub_changed.connect(self.load_plans)
        self._toolbar.plan_add_requested.connect(self._on_plan_add)
        self._toolbar.manufacturable_browser_requested.connect(self._on_manufacturable_browser)
        self._toolbar.batch_add_requested.connect(self._on_batch_add)
        self._toolbar.char_changed.connect(self.load_plans)

        self._toolbar.view_changed.connect(self._on_view_changed)

        # PlanTable
        self._plan_table_widget.plan_updated.connect(self.load_plans)
        self._plan_table_widget.refresh_requested.connect(self.load_plans)
        self._plan_table_widget.plan_detail_requested.connect(self._on_plan_detail)

        # StatusBar
        self._status_bar.save_price_requested.connect(self._on_save_prices)

        # ActionButtons
        self._action_buttons.refresh_procurement_requested.connect(self._on_procurement)
        self._action_buttons.blueprint_list_requested.connect(self._on_blueprint_list)
        self._action_buttons.materials_summary_requested.connect(self._on_materials_summary)
        self._action_buttons.output_summary_requested.connect(self._on_output_summary)
        self._action_buttons.char_usage_requested.connect(self._on_char_usage)

        # 蓝图列表快捷按钮
        self._btn_add_from_list.clicked.connect(self._on_batch_add)

    # ── load_plans ────────────────────────────────────────────

    def load_plans(self):
        with get_container().db.connect("user") as conn:
            f = self._toolbar.get_filter()
            sql = "SELECT * FROM production_plans"
            if f == "待排":
                sql += " WHERE status = 'pending'"
            elif f == "运行中":
                sql += " WHERE status IN ('in_progress','running')"
            elif f == "已完成":
                sql += " WHERE status IN ('completed','done')"
            sql += " ORDER BY created_at DESC"
            c = conn.cursor()
            c.execute(sql)
            cols = [d[0] for d in c.description]
            rows = [dict(zip(cols, r)) for r in c.fetchall()]
        from ui_pyside6.models.industry_models import PlanTableModel

        model = PlanTableModel(rows)
        self._plan_table_widget.set_model(model)
        self._status_bar.update_stats(rows)
        self._plan_count.setText(f"共 {len(rows)} 条计划")

        # 如果当前是甘特图模式，同步刷新甘特图
        if self._view_stack.currentIndex() == 1:
            self._refresh_gantt()
        self._auto_calculate_plans(rows)

    def _on_view_changed(self, view_mode: str):
        if view_mode == "gantt":
            self._view_stack.setCurrentIndex(1)
            self._refresh_gantt()
            self._status_bar.setVisible(False)
            self._action_buttons.setVisible(False)
        else:
            self._view_stack.setCurrentIndex(0)
            self._status_bar.setVisible(True)
            self._action_buttons.setVisible(True)

    def _refresh_gantt(self):
        model = self._plan_table_widget.get_model()
        plans = []
        if model:
            for row in range(model.rowCount()):
                p = model.get_plan(row)
                if p:
                    plans.append(p)
        self._gantt_view.load_from_plans(plans)

    # ── 对话框打开方法 ────────────────────────────────────────

    def _on_plan_add(self, text: str):
        """???????????? -> ?? -> AddPlanDialog -> INSERT"""
        text = text.strip()
        if not text:
            return
        from datetime import datetime, timezone

        from PySide6.QtWidgets import QDialog

        from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog

        # 1) ????
        conn = get_container().db.direct_connect("ref")
        try:
            like = f"%{text}%"
            cur = conn.cursor()
            cur.execute(
                "SELECT type_id, zh_name, en_name FROM item "
                "WHERE (zh_name LIKE ? OR en_name LIKE ?) "
                "ORDER BY CASE WHEN en_name=? OR zh_name=? THEN 0 ELSE 1 END, "
                "LENGTH(en_name), type_id LIMIT 10",
                (like, like, text, text),
            )
            items = cur.fetchall()
        finally:
            conn.close()

        if not items:
            QMessageBox.information(self, "???", f"????????: {text}")
            return

        type_id = items[0][0]
        product_name = items[0][1] or items[0][2] or str(type_id)

        # ?????????
        conn2 = get_container().db.direct_connect("bp")
        try:
            cur = conn2.cursor()
            cur.execute(
                "SELECT 1 FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                (type_id,),
            )
            has_bp = cur.fetchone() is not None
        finally:
            conn2.close()

        if not has_bp:
            QMessageBox.information(self, "????", f"\u300c{product_name}\u300d??????")
            return

        # 3) ????
        from ui_pyside6.workers.industry_workers import ScoreWorker

        self._score_worker = ScoreWorker(
            type_id=type_id,
            bp_me=0,
            bp_te=0,
            mat_hub="Jita",
            sell_hub="Jita",
            tax=0.0,
        )

        def _on_score(result: dict):
            dlg = AddPlanDialog(product_name, result, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            conn3 = get_container().db.direct_connect("user")
            try:
                iskph = result.get("isk_per_hour", 0) or result.get("breakdown", {}).get("isk_per_hour", 0)
                mat_cost = result.get("breakdown", {}).get("material_cost", 0)
                conn3.execute(
                    "INSERT INTO production_plans "
                    "(product_type_id, product_name, runs, parallels, me_level, te_level, "
                    "mat_hub, sell_hub, facility, char_name, status, "
                    "profit, margin, score, iskph, material_cost, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?)",
                    (
                        type_id,
                        product_name,
                        data["runs"],
                        data["parallels"],
                        data["me"],
                        data["te"],
                        "Jita",
                        "Jita",
                        data["fac"],
                        data["char"],
                        result.get("profit_per_run", 0),
                        result.get("margin_pct", 0),
                        result.get("score", 0),
                        iskph,
                        mat_cost,
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn3.commit()
            finally:
                conn3.close()
            self.load_plans()
            QMessageBox.information(self, "??", f"???????: {product_name}")

        self._score_worker.finished.connect(_on_score)
        self._score_worker.start()

    def _on_manufacturable_browser(self):
        """??????????"""
        dlg = ManufacturableItemsDialog()
        dlg.show()

    def _on_batch_add(self):
        """???????????????"""
        self._on_manufacturable_browser()

    def _on_plan_detail(self, plan_id: int):
        """双击计划行 → 打开 PlanEditDialog"""
        from ui_pyside6.views.industry import PlanEditDialog

        model = self._plan_table_widget.get_model()
        plan_data = {}
        if model:
            for row in range(model.rowCount()):
                p = model.get_plan(row)
                if p and p.get("id") == plan_id:
                    plan_data = p
                    break
        if not plan_data:
            return
        dlg = PlanEditDialog(self, plan_data)
        if dlg.exec():
            updated = dlg.get_updated_data()
            with get_container().db.connect("user") as conn:
                conn.execute(
                    "UPDATE production_plans SET runs=?, parallels=?, me_level=?, te_level=?, "
                    "char_name=?, facility=?, output_location=?, mat_hub=?, notes=? WHERE id=?",
                    (
                        updated.get("runs", 1),
                        updated.get("parallels", 1),
                        updated.get("me", 0),
                        updated.get("te", 0),
                        updated.get("char_name", ""),
                        updated.get("facility", ""),
                        updated.get("output", ""),
                        updated.get("material_hub", "Jita"),
                        updated.get("notes", ""),
                        plan_id,
                    ),
                )
            self.load_plans()

    def _on_blueprint_list(self):
        dlg = BlueprintRequirementsDialog(self)
        dlg.exec()

    def _on_materials_summary(self):
        dlg = MaterialsSummaryDialog(self)
        dlg.exec()

    def _on_output_summary(self):
        dlg = OutputSummaryDialog(self)
        dlg.exec()

    def _on_char_usage(self):
        dlg = CharacterUsageDialog(self)
        dlg.exec()

    def _on_procurement(self):
        """打开待采购对话框"""
        from ui_pyside6.views.procurement_tab import ProcurementDialog

        plans = []
        with get_container().db.connect("user", "ref", "mkt") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, product_type_id, product_name, runs, parallels, me_level, mat_hub, sell_hub "
                "FROM production_plans WHERE status IN ('pending', 'in_progress', 'running')"
            )
            for pr in c.fetchall():
                plans.append(
                    {
                        "id": pr[0],
                        "product_type_id": pr[1],
                        "product_name": pr[2],
                        "runs": pr[3],
                        "parallels": pr[4],
                        "me_level": pr[5],
                        "mat_hub": pr[6],
                        "sell_hub": pr[7],
                    }
                )
        if not plans:
            QMessageBox.information(self, "提示", "没有活跃计划")
            return
        dlg = ProcurementDialog(plans, "Jita", "Jita", self)
        dlg.exec()
        self.load_plans()

    # ── 保存价格快照 ──────────────────────────────────────────

    def _on_save_prices(self):
        with get_container().db.connect("user", "ref", "mkt") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT product_type_id FROM production_plans WHERE status IN ('pending','in_progress','running')"
            )
            plan_pids = [r[0] for r in c.fetchall()]
            if not plan_pids:
                QMessageBox.information(self, "提示", "没有活跃计划")
                return
            placeholders = ",".join("?" for _ in plan_pids)
            c.execute(
                "SELECT DISTINCT bm.material_type_id "
                "FROM bp.blueprint_products bp "
                "JOIN bp.blueprint_materials bm "
                "ON bm.blueprint_type_id=bp.blueprint_type_id "
                "AND bm.activity=bp.activity "
                f"WHERE bp.product_type_id IN ({placeholders}) "
                "AND bp.activity='manufacturing'",
                plan_pids,
            )
            type_ids = set(r[0] for r in c.fetchall())
            type_ids.update(plan_pids)
            count = 0
            for tid in type_ids:
                c.execute(
                    "SELECT sell_price, buy_price FROM mkt.market_prices "
                    "WHERE type_id=? AND region_id=10000002 LIMIT 1",
                    (tid,),
                )
                row = c.fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO price_snapshots(type_id,region_id,sell_price,buy_price) "
                        "VALUES (?,10000002,?,?)",
                        (tid, row[0] or 0, row[1] or 0),
                    )
                    count += 1
            QMessageBox.information(self, "完成", f"已保存 {count} 个价格快照")

    # ── 状态保存/恢复 ─────────────────────────────────────────

    def save_state(self) -> dict:
        data = {}
        table = self._plan_table_widget.get_table()
        vs = table.verticalScrollBar()
        if vs:
            data["v_scroll"] = vs.value()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        table = self._plan_table_widget.get_table()
        vs = table.verticalScrollBar()
        if vs and "v_scroll" in data:
            vs.setValue(data["v_scroll"])

    # ── 外部刷新接口 ──────────────────────────────────────────

    def refresh_display(self):
        self.load_plans()

    def update_status_bar(self):
        self.load_plans()

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self):
        self._title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: bold; background: transparent;"
        )
        self._plan_count.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;")
        self._btn_add_from_list.setStyleSheet(
            f"QPushButton {{ padding: 4px 12px; border: 1px solid {TEXT_SECONDARY}; "
            f"border-radius: 4px; background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"
        )

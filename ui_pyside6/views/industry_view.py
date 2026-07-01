# 生产计划管理 — 统一页面
from datetime import datetime, timezone

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.container import get_container
from ui_pyside6.models.industry_models import MaterialTableModel, PlanTableModel
from ui_pyside6.theme import (
    ACCENT_RED,
    BORDER,
    GREEN,
    PRIMARY,
    TEXT_SECONDARY,
    add_theme_listener,
)
from ui_pyside6.views.procurement_tab import ProcurementDialog

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
            for col, col_type in [("iskph", "REAL DEFAULT 0"), ("material_cost", "REAL DEFAULT 0")]:
                try:
                    conn.execute(f"ALTER TABLE production_plans ADD COLUMN {col} {col_type}")
                except Exception:
                    pass
    except Exception:
        pass


class IndustryPage(QWidget):
    """生产计划管理统一页面"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        self.setObjectName("industry_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")
        self._tabs.addTab(self._build_tab_plan(), "生产计划")
        layout.addWidget(self._tabs)
        self.load_plans()
        add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")
        self._plan_count.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._mat_summary.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        self._setup_plan_actions()

    def save_state(self) -> dict:
        data = {}
        vs = self._plan_table.verticalScrollBar()
        if vs:
            data["v_scroll"] = vs.value()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        sv = data.get("v_scroll", 0)
        if sv:
            QTimer.singleShot(100, lambda: self._plan_table.verticalScrollBar().setValue(sv))

    def _build_tab_plan(self) -> QWidget:
        """计划列表 + 材料汇总 + 待采购"""
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

        self._procure_btn = QPushButton("\U0001f4cb 待采购")
        self._procure_btn.clicked.connect(self._on_procurement)
        btn_row.addWidget(self._procure_btn)

        btn_row.addWidget(QLabel("  机库:"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.setMinimumWidth(120)
        btn_row.addWidget(self._hangar_combo)
        self._load_hangars()

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
        self._plan_count.setStyleSheet(f"color: {TEXT_SECONDARY};")
        stats.addWidget(self._plan_count)

        stats.addWidget(QLabel("  过滤:"))
        self._filter = QComboBox()
        self._filter.addItems(["全部", "待生产", "生产中", "已完成"])
        self._filter.currentTextChanged.connect(lambda: self.load_plans())
        stats.addWidget(self._filter)
        stats.addStretch()
        layout.addLayout(stats)

        # 材料汇总
        self._mat_group = QGroupBox("材料需求汇总（所有活跃计划）")
        self._mat_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {TEXT_SECONDARY}; }}
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
        self._mat_summary.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        mv.addWidget(self._mat_summary)

        layout.addWidget(self._mat_group)
        return w

    def load_plans(self):
        with get_container().db.connect("user") as conn:
            f = self._filter.currentText()
            sql = "SELECT * FROM production_plans"
            if f == "待生产":
                sql += " WHERE status = 'pending'"
            elif f == "生产中":
                sql += " WHERE status IN ('in_progress', 'running')"
            elif f == "已完成":
                sql += " WHERE status IN ('completed', 'done')"
            sql += " ORDER BY created_at DESC"
            c = conn.cursor()
            c.execute(sql)
            cols = [d[0] for d in c.description]
            rows = [dict(zip(cols, r)) for r in c.fetchall()]
            self._plan_model = PlanTableModel(rows)
            self._plan_table.setModel(self._plan_model)
            self._plan_count.setText(f"共 {len(rows)} 条计划")
            self._setup_plan_actions()

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

    def _setup_plan_actions(self):
        """为生产计划表格的操作列添加按钮控件"""
        model = self._plan_table.model()
        if not model or not self._plan_model:
            return

        source = self._plan_model
        n_rows = model.rowCount()
        last_col = source.columnCount() - 1

        for row in range(n_rows):
            idx = model.index(row, last_col)
            self._plan_table.removeCellWidget(idx.row(), idx.column())

        for row in range(n_rows):
            if hasattr(model, "mapToSource"):
                src_row = model.mapToSource(model.index(row, 0)).row()
            else:
                src_row = row
            plan = source.get_plan(src_row)
            if not plan:
                continue

            idx = model.index(row, last_col)
            widget = QWidget()
            layout_w = QHBoxLayout(widget)
            layout_w.setContentsMargins(2, 0, 2, 0)
            layout_w.setSpacing(4)

            plan_id = plan["id"]
            status = plan.get("status", "")

            if status == "pending":
                btn = QPushButton("启动")
                btn.setStyleSheet(f"color: {GREEN}; font-size: 11px; padding: 1px 6px;")
                btn.clicked.connect(lambda checked, pid=plan_id: self._on_plan_start(pid))
                layout_w.addWidget(btn)

            if status in ("pending", "in_progress", "running"):
                btn = QPushButton("完成")
                btn.setStyleSheet(f"color: {PRIMARY}; font-size: 11px; padding: 1px 6px;")
                btn.clicked.connect(lambda checked, pid=plan_id: self._on_plan_complete(pid))
                layout_w.addWidget(btn)

            btn = QPushButton("删除")
            btn.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px; padding: 1px 6px;")
            btn.clicked.connect(lambda checked, pid=plan_id: self._on_plan_delete(pid))
            layout_w.addWidget(btn)

            layout_w.addStretch()
            self._plan_table.setIndexWidget(idx, widget)

    def _on_plan_start(self, plan_id: int):
        """启动生产 -> status = in_progress"""
        with get_container().db.connect("user") as conn:
            conn.execute(
                "UPDATE production_plans SET status = 'in_progress', started_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), plan_id),
            )
        self.load_plans()
        self._refresh_material()

    def _on_plan_complete(self, plan_id: int):
        """完成生产 -> status = completed"""
        with get_container().db.connect("user") as conn:
            conn.execute(
                "UPDATE production_plans SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), plan_id),
            )
        self.load_plans()
        self._refresh_material()

    def _on_plan_delete(self, plan_id: int):
        """删除单条计划"""
        if (
            QMessageBox.question(
                self,
                "确认",
                f"删除生产计划 #{plan_id}？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        with get_container().db.connect("user") as conn:
            conn.execute("DELETE FROM production_plans WHERE id = ?", (plan_id,))
        self.load_plans()
        self._refresh_material()

    def _refresh_material(self):
        """刷新材料汇总 + 跟踪活跃计划"""
        with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, product_type_id, product_name, runs, parallels, me_level, mat_hub, sell_hub "
                "FROM production_plans WHERE status IN ('pending', 'in_progress', 'running')"
            )
            plan_rows = c.fetchall()
            if not plan_rows:
                self._mat_table.setModel(None)
                self._mat_summary.setText("无活跃计划")
                self._active_plans = []
                return
            self._active_plans = []
            for pr in plan_rows:
                self._active_plans.append(
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
            material_map: dict[int, int] = {}
            for pr in plan_rows:
                pid, runs, parallels = pr[1], pr[3], pr[4]
                c.execute(
                    """SELECT bm.material_type_id, bm.quantity
                    FROM bp.blueprint_products bp
                    JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                        AND bm.activity = bp.activity
                    WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'""",
                    (pid,),
                )
                for mid, qty in c.fetchall():
                    material_map[mid] = material_map.get(mid, 0) + qty * runs * parallels
            rows = []
            total = 0
            for mid, need in material_map.items():
                c.execute("SELECT zh_name, en_name, volume FROM ref.item WHERE type_id = ?", (mid,))
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

    def _on_procurement(self):
        """打开待采购对话框"""
        hangar_id = self._hangar_combo.currentData()
        if hangar_id is None:
            QMessageBox.information(self, "提示", "请先选择一个机库")
            return
        plans = getattr(self, "_active_plans", [])
        dlg = ProcurementDialog(plans, hangar_id, self._hangar_combo.currentText(), self)
        dlg.exec()
        self._refresh_material()

    def _load_hangars(self):
        """加载机库列举"""
        self._hangar_combo.clear()
        try:
            from services.inventory_manager import get_hangars

            for h in get_hangars():
                self._hangar_combo.addItem(h["name"], h["id"])
        except Exception:
            pass

    def refresh_display(self):
        self.load_plans()
        self._refresh_material()

    def update_status_bar(self):
        if self._main and hasattr(self._main, "statusBar"):
            count = self._plan_model.rowCount() if self._plan_model else 0
            self._main.statusBar().showMessage(f"生产计划: {count} 条")

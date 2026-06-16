"""
生产计划管理 — 统一页面
"""
import json
import sqlite3
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QTableView, QHeaderView,
    QSplitter, QListWidget, QListWidgetItem, QFrame,
    QSpinBox, QGroupBox, QAbstractItemView, QMessageBox, QDialog,
    QDialogButtonBox, QFormLayout, QHeaderView,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal, QTimer
from PySide6.QtGui import QColor

from core.paths import DB_PATH
from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, PRIMARY,
    TEXT_PRIMARY, TEXT_SECONDARY, GREEN, RED, BORDER,
)
from services.scoring import calc_manufacturing_score, TRADE_HUB_IDS


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
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(PLAN_DB_SCHEMA)
        conn.close()
    except Exception:
        pass


# ════════════════════════════════════════════════════
#  Workers
# ════════════════════════════════════════════════════

class SearchWorker(QThread):
    finished = Signal(list)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            like = f"%{self._query}%"
            c.execute("""
                SELECT type_id, zh_name, en_name FROM item
                WHERE en_name LIKE ? OR zh_name LIKE ?
                ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                         LENGTH(en_name), type_id
                LIMIT 30
            """, (like, like, f"{self._query}%", f"{self._query}%"))
            rows = [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]
            self.finished.emit(rows)
        finally:
            conn.close()


class ScoreWorker(QThread):
    finished = Signal(dict)

    def __init__(self, type_id: int, me: int, te: int, mat_hub: str, sell_hub: str, tax: float, parent=None):
        super().__init__(parent)
        self._tid = type_id
        self._me = me
        self._te = te
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._tax = tax

    def run(self):
        result = calc_manufacturing_score(
            type_id=self._tid,
            char_config={"skills": {"工业理论": self._me, "高级工业理论": self._te}},
            mat_source_hub=self._mat_hub,
            sell_hub=self._sell_hub,
            facility_tax_pct=self._tax,
            price_type_mat="sell",
            price_type_prod="sell",
        )
        self.finished.emit(result)


# ════════════════════════════════════════════════════
#  Table Models
# ════════════════════════════════════════════════════

class PlanTableModel(QAbstractTableModel):
    _HEADERS = ["产品", "批次", "并行", "ME", "TE", "材料区域", "角色",
                "利润", "利润率", "评分", "时均/h", "状态"]

    def __init__(self, plans: list[dict]):
        super().__init__()
        self._plans = plans

    def rowCount(self, parent=QModelIndex()): return len(self._plans)
    def columnCount(self, parent=QModelIndex()): return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._plans[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            cols = [
                p.get("product_name", f"ID:{p['product_type_id']}"),
                str(p["runs"]), str(p["parallels"]),
                str(p["me_level"]), str(p["te_level"]),
                p.get("mat_hub", "Jita"),
                p.get("char_name") or "-",
                f"{p.get('profit', 0):,.0f}" if p.get('profit') else "-",
                f"{p.get('margin', 0):.1f}%" if p.get('margin') else "-",
                f"{p.get('score', 0):.0f}" if p.get('score') else "-",
                f"{p.get('iskph', 0):,.0f}" if p.get('iskph') else "-",
                {"pending": "⏳待排", "running": "⚙运行", "done": "✅完成"}.get(p.get("status", ""), p.get("status", "")),
            ]
            return cols[c]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 7:
                return QColor(GREEN) if p.get("profit", 0) > 0 else QColor(RED)
            if c == 9:
                s = p.get("score", 0)
                return QColor(GREEN) if s >= 70 else (QColor(RED) if s < 30 else QColor(PRIMARY))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_plan(self, row: int) -> dict:
        return self._plans[row] if 0 <= row < len(self._plans) else {}


class MaterialTableModel(QAbstractTableModel):
    _HEADERS = ["材料", "总需求", "单价", "总价"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()): return len(self._rows)
    def columnCount(self, parent=QModelIndex()): return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [r.get("name", ""), str(r.get("need", 0)),
                    f"{r.get('price', 0):,.2f}", f"{r.get('total', 0):,.2f}"][c]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None


# ════════════════════════════════════════════════════
#  Dialog: 加入计划
# ════════════════════════════════════════════════════

class AddPlanDialog(QDialog):
    def __init__(self, product_name: str, score_result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"加入生产计划 — {product_name}")
        self.setMinimumWidth(420)
        self._result_data = None

        layout = QFormLayout(self)
        layout.addRow("物品:", QLabel(product_name))

        profit = score_result.get("profit_per_run", 0)
        margin = score_result.get("margin_pct", 0)
        score = score_result.get("score", 0)
        layout.addRow("评分:", QLabel(f"{score:.1f} | 利润: {profit:,.0f} ISK | 利润率: {margin:.1f}%"))

        self._runs = QSpinBox()
        self._runs.setRange(1, 10000)
        self._runs.setValue(1)
        layout.addRow("批次 (runs):", self._runs)

        self._par = QSpinBox()
        self._par.setRange(1, 100)
        self._par.setValue(1)
        layout.addRow("并行线:", self._par)

        me_te = QHBoxLayout()
        self._me = QSpinBox()
        self._me.setRange(0, 20)
        self._te = QSpinBox()
        self._te.setRange(0, 20)
        me_te.addWidget(QLabel("ME:"))
        me_te.addWidget(self._me)
        me_te.addWidget(QLabel("TE:"))
        me_te.addWidget(self._te)
        layout.addRow("参数:", me_te)

        self._char = QLineEdit()
        self._char.setPlaceholderText("角色名（可选）")
        layout.addRow("角色:", self._char)

        self._fac = QLineEdit()
        self._fac.setPlaceholderText("设施名（可选）")
        layout.addRow("设施:", self._fac)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._on_ok)
        btn.rejected.connect(self.reject)
        layout.addRow(btn)

    def _on_ok(self):
        self._result_data = {
            "runs": self._runs.value(), "parallels": self._par.value(),
            "me": self._me.value(), "te": self._te.value(),
            "char": self._char.text().strip(), "fac": self._fac.text().strip(),
        }
        self.accept()

    def result_data(self) -> dict | None:
        return self._result_data


# ════════════════════════════════════════════════════
#  Main Page
# ════════════════════════════════════════════════════

class IndustryPage(QWidget):
    """生产计划管理统一页面"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        self.setObjectName("industry_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 顶栏：搜索 + 快速参数 + 操作 ──
        self._build_top_bar(layout)

        # ── 中栏：计划列表（主区域） ──
        self._build_plan_table(layout)

        # ── 底栏：材料汇总 ──
        self._build_material_bar(layout)

        # ── 状态 ──
        self._ps_suggest_visible = False
        self._ps_results: list[dict] = []
        self._ps_selected: dict | None = None
        self.load_plans()

    # ═══════════════════════════════════
    #  UI
    # ═══════════════════════════════════

    def _build_top_bar(self, layout):
        """搜索 + 参数 + 操作按钮"""
        bar = QWidget()
        bar.setObjectName("industry_toolbar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        # 第1行：搜索
        r1 = QHBoxLayout()

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索成品名（如 渡鸦级） → 计算利润 → 加入计划")
        self._search.textChanged.connect(self._on_search)
        r1.addWidget(self._search, 1)

        self._search_list = QListWidget()
        self._search_list.setMaximumHeight(160)
        self._search_list.setVisible(False)
        self._search_list.itemClicked.connect(self._on_search_click)

        r1.addWidget(QLabel("ME:"))
        self._me = QSpinBox()
        self._me.setRange(0, 20)
        r1.addWidget(self._me)

        r1.addWidget(QLabel("TE:"))
        self._te = QSpinBox()
        self._te.setRange(0, 20)
        r1.addWidget(self._te)

        r1.addWidget(QLabel("区域:"))
        self._hub = QComboBox()
        self._hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._hub.setCurrentText("Jita")
        r1.addWidget(self._hub)

        r1.addWidget(QLabel("税%:"))
        self._tax = QLineEdit("0")
        self._tax.setFixedWidth(40)
        r1.addWidget(self._tax)

        self._calc_btn = QPushButton("🔍 计算")
        self._calc_btn.clicked.connect(self._on_calc)
        r1.addWidget(self._calc_btn)

        self._add_btn = QPushButton("➕ 加入计划")
        self._add_btn.setObjectName("ps_add_btn")
        self._add_btn.clicked.connect(self._on_add_plan)
        self._add_btn.setEnabled(False)
        r1.addWidget(self._add_btn)

        v.addLayout(r1)

        # 第2行：选中物品预览 + 操作
        r2 = QHBoxLayout()
        self._preview = QLabel("☝️ 搜索物品 → 计算 → 加入生产计划")
        self._preview.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        r2.addWidget(self._preview, 1)

        self._del_btn = QPushButton("🗑 删除选中计划")
        self._del_btn.setObjectName("del_btn")
        self._del_btn.clicked.connect(self._on_delete)
        r2.addWidget(self._del_btn)

        self._refresh_btn = QPushButton("🔄 刷新材料汇总")
        self._refresh_btn.clicked.connect(self._refresh_material)
        r2.addWidget(self._refresh_btn)

        v.addLayout(r2)

        layout.addWidget(bar)
        layout.addWidget(self._search_list)

    def _build_plan_table(self, layout):
        """主计划列表"""
        self._plan_table = QTableView()
        self._plan_table.setAlternatingRowColors(True)
        self._plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._plan_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._plan_table.horizontalHeader().setStretchLastSection(True)
        self._plan_table.setSortingEnabled(True)
        self._plan_table.verticalHeader().setDefaultSectionSize(26)
        layout.addWidget(self._plan_table, 1)

        # 底部统计
        stats = QHBoxLayout()
        self._plan_count = QLabel("")
        self._plan_count.setStyleSheet(f"color: {TEXT_SECONDARY};")
        stats.addWidget(self._plan_count)

        stats.addWidget(QLabel("  过滤:"))
        self._filter = QComboBox()
        self._filter.addItems(["全部", "待排产", "运行中", "已完成"])
        self._filter.currentTextChanged.connect(lambda: self.load_plans())
        stats.addWidget(self._filter)

        stats.addStretch()
        layout.addLayout(stats)

    def _build_material_bar(self, layout):
        """底部材料汇总"""
        self._mat_group = QGroupBox("📦 材料需求汇总（所有活跃计划）")
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

    # ═══════════════════════════════════
    #  搜索
    # ═══════════════════════════════════

    def _on_search(self, text: str):
        if not text.strip():
            self._search_list.setVisible(False)
            return
        w = SearchWorker(text.strip(), self)
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
        self._preview.setText(f"⏳ 正在计算 {self._selected_name}...")
        w = ScoreWorker(self._selected_tid, self._me.value(), self._te.value(),
                        self._hub.currentText(), self._hub.currentText(), tax, self)
        w.finished.connect(self._on_score)
        w.start()

    def _on_score(self, result: dict):
        self._ps_selected = result
        status = result.get("status", "")

        if status:
            self._preview.setText(f"⚠️ {self._selected_name}: {status}")
            self._add_btn.setEnabled(False)
            return

        score = result.get("score", 0)
        profit = result.get("profit_per_run", 0)
        margin = result.get("margin_pct", 0)
        iskph = result.get("breakdown", {}).get("isk_per_hour", 0)
        cost = result.get("cost_per_unit", 0)

        self._preview.setText(
            f"📊 {self._selected_name} | 评分: {score:.1f} | "
            f"利润: {profit:,.0f} ISK | 利润率: {margin:.1f}% | "
            f"时均: {iskph:,.0f} ISK/h | 成本: {cost:,.0f} ISK"
        )
        self._preview.setStyleSheet(
            f"color: {GREEN if profit > 0 else RED}; font-size: 12px;"
        )
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

        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                INSERT INTO production_plans
                (product_type_id, product_name, runs, parallels, me_level, te_level,
                 mat_hub, sell_hub, facility, char_name, status,
                 profit, margin, score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """, (
                self._selected_tid, self._selected_name,
                data["runs"], data["parallels"], data["me"], data["te"],
                self._hub.currentText(), self._hub.currentText(),
                data["fac"], data["char"],
                self._ps_selected.get("profit_per_run", 0),
                self._ps_selected.get("margin_pct", 0),
                self._ps_selected.get("score", 0),
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ))
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
        conn = sqlite3.connect(DB_PATH)
        try:
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
        finally:
            conn.close()

    def _on_delete(self):
        sel = self._plan_table.selectionModel().selectedRows()
        if not sel:
            return
        ids = [self._plan_model._plans[r.row()]["id"] for r in sel]
        if QMessageBox.question(self, "确认", f"删除 {len(ids)} 条计划？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        conn = sqlite3.connect(DB_PATH)
        conn.executemany("DELETE FROM production_plans WHERE id = ?", [(i,) for i in ids])
        conn.commit()
        conn.close()
        self.load_plans()
        self._refresh_material()

    # ═══════════════════════════════════
    #  材料汇总
    # ═══════════════════════════════════

    def _refresh_material(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT product_type_id, runs, parallels FROM production_plans WHERE status IN ('pending', 'running')")
            plans = c.fetchall()

            if not plans:
                self._mat_table.setModel(None)
                self._mat_summary.setText("无活跃计划")
                return

            material_map: dict[int, int] = {}
            for pid, runs, parallels in plans:
                c.execute("""
                    SELECT bm.material_type_id, bm.quantity
                    FROM blueprint_products bp
                    JOIN blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                        AND bm.activity = bp.activity
                    WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
                """, (pid,))
                for mid, qty in c.fetchall():
                    material_map[mid] = material_map.get(mid, 0) + qty * runs * parallels

            rows = []
            total = 0
            for mid, need in material_map.items():
                c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (mid,))
                r = c.fetchone()
                name = (r[0] or r[1] or str(mid)) if r else str(mid)
                c.execute("SELECT sell_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1", (mid,))
                pr = c.fetchone()
                price = pr[0] or 0 if pr else 0
                subtotal = need * price
                total += subtotal
                rows.append({"name": name, "need": need, "price": price, "total": subtotal})

            rows.sort(key=lambda x: x["total"], reverse=True)
            self._mat_table.setModel(MaterialTableModel(rows))
            self._mat_summary.setText(f"共 {len(rows)} 种材料 | 总成本: {total:,.0f} ISK")
        finally:
            conn.close()

    # ═══════════════════════════════════
    #  刷新
    # ═══════════════════════════════════

    def refresh_display(self):
        self.load_plans()
        self._refresh_material()

"""
工业制造页面 — QTabWidget 容器含 4 个子页
"""
import sqlite3
import concurrent.futures
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QLineEdit, QComboBox, QPushButton, QTableView, QHeaderView,
    QListView, QSplitter, QFrame, QTextBrowser, QListWidget, QListWidgetItem,
    QMessageBox,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
from core.paths import DB_PATH
from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, PRIMARY,
    TEXT_PRIMARY, TEXT_SECONDARY, GREEN, RED, YELLOW, BORDER,
)


class IndustryPage(QWidget):
    """工业制造页"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setStyleSheet(f"background-color: {BG_DARK};")
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._user_skills: dict[int, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(self._build_refining_tab(), "估价/精炼")
        tabs.addTab(self._build_calculator_tab(), "制 造 业")
        tabs.addTab(self._build_planetary_tab(), "行星工业")
        tabs.addTab(self._build_lp_tab(), "忠诚点价值")

        layout.addWidget(tabs)

        # 加载技能
        self._load_skills()

    # ═══════════════════════════════════════
    #  估价/精炼 (占位)
    # ═══════════════════════════════════════

    def _build_refining_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("估价与精炼 — 开发中\n\n输入矿石或物品，计算精炼产出价值。")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 16px; padding: 40px;")
        layout.addWidget(label)
        return w

    # ═══════════════════════════════════════
    #  行星工业 (占位)
    # ═══════════════════════════════════════

    def _build_planetary_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("行星工业 — 开发中\n\n分析行星产物投入产出效率。")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 16px; padding: 40px;")
        layout.addWidget(label)
        return w

    # ═══════════════════════════════════════
    #  忠诚点价值 (占位)
    # ═══════════════════════════════════════

    def _build_lp_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("忠诚点价值 — 开发中\n\n分析 LP 兑换物品的 ISK/LP 效率。")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 16px; padding: 40px;")
        layout.addWidget(label)
        return w

    # ═══════════════════════════════════════
    #  制造计算器
    # ═══════════════════════════════════════

    def _build_calculator_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 搜索工具栏 ──
        toolbar = QWidget()
        toolbar.setStyleSheet(f"background-color: {BG_SURFACE}; border-bottom: 1px solid {BORDER}; padding: 8px 12px;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(8)

        self._bp_search = QLineEdit()
        self._bp_search.setPlaceholderText("输入蓝图名称搜索...")
        self._bp_search.textChanged.connect(self._on_bp_search)
        tb_layout.addWidget(self._bp_search)

        self._activity_combo = QComboBox()
        self._activity_combo.addItems(["manufacturing", "invention", "copying", "reaction"])
        self._activity_combo.setCurrentText("manufacturing")
        self._activity_combo.currentTextChanged.connect(self._recalc)
        tb_layout.addWidget(QLabel("活动:"))
        tb_layout.addWidget(self._activity_combo)

        self._batch_input = QLineEdit("1")
        self._batch_input.setFixedWidth(60)
        self._batch_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._batch_input.textChanged.connect(self._recalc)
        tb_layout.addWidget(QLabel("批次:"))
        tb_layout.addWidget(self._batch_input)

        self._price_combo = QComboBox()
        self._price_combo.addItems(["buy", "sell"])
        self._price_combo.setCurrentText("buy")
        self._price_combo.currentTextChanged.connect(self._recalc)
        tb_layout.addWidget(QLabel("价格:"))
        tb_layout.addWidget(self._price_combo)

        self._tax_input = QLineEdit("0")
        self._tax_input.setFixedWidth(50)
        self._tax_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._tax_input.textChanged.connect(self._recalc)
        tb_layout.addWidget(QLabel("税率%:"))
        tb_layout.addWidget(self._tax_input)

        layout.addWidget(toolbar)

        # ── 候选列表 ──
        self._suggest_list = QListWidget()
        self._suggest_list.setMaximumHeight(200)
        self._suggest_list.setVisible(False)
        self._suggest_list.itemClicked.connect(self._on_suggest_clicked)
        layout.addWidget(self._suggest_list)

        # ── 产品信息行 ──
        self._product_label = QLabel("")
        self._product_label.setStyleSheet(f"color: {TEXT_PRIMARY}; padding: 4px 16px; font-size: 13px;")
        layout.addWidget(self._product_label)

        self._time_label = QLabel("")
        self._time_label.setStyleSheet(f"color: {TEXT_SECONDARY}; padding: 0px 16px; font-size: 12px;")
        layout.addWidget(self._time_label)

        # ── 主内容区（材料表 + 技能面板） ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # 材料表
        self._mat_table = QTableView()
        self._mat_table.setAlternatingRowColors(True)
        self._mat_table.horizontalHeader().setStretchLastSection(True)
        self._mat_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._mat_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._mat_table.customContextMenuRequested.connect(self._on_mat_context_menu)
        splitter.addWidget(self._mat_table)

        # 技能面板
        skill_panel = QWidget()
        skill_panel.setStyleSheet(f"background-color: {BG_SURFACE};")
        skill_layout = QVBoxLayout(skill_panel)
        skill_layout.setContentsMargins(12, 10, 12, 10)
        skill_layout.setSpacing(6)

        skill_header = QLabel("技能等级")
        skill_header.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold; font-size: 14px;")
        skill_layout.addWidget(skill_header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {BORDER};")
        sep.setFixedHeight(1)
        skill_layout.addWidget(sep)

        self._skill_list = QListView()
        self._skill_model = None
        skill_layout.addWidget(self._skill_list)

        save_btn = QPushButton("保存技能等级")
        save_btn.clicked.connect(self._save_skills)
        skill_layout.addWidget(save_btn)

        skill_panel.setFixedWidth(260)
        splitter.addWidget(skill_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        layout.addWidget(splitter)

        # ── 汇总 ──
        self._summary_browser = QTextBrowser()
        self._summary_browser.setFixedHeight(160)
        self._summary_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border-top: 1px solid {BORDER};
                font-size: 13px;
                padding: 8px 16px;
            }}
        """)
        layout.addWidget(self._summary_browser)

        # ── 状态 ──
        self._selected_bp: dict | None = None
        self._blueprint_results: list[dict] = []
        self._materials: list[dict] = []
        self._products: list[dict] = []
        self._bp_skills: list[dict] = []
        self._bp_time: int = 0

        return w

    # ═══════════════════════════════════════
    #  蓝图搜索
    # ═══════════════════════════════════════

    def _on_bp_search(self, text: str):
        if not text or len(text.strip()) < 1:
            self._suggest_list.setVisible(False)
            return
        worker = BPSearchWorker(text.strip(), self)
        worker.finished_signal.connect(self._on_bp_results)
        worker.start()

    def _on_bp_results(self, results: list[dict]):
        self._blueprint_results = results
        self._suggest_list.clear()
        if not results:
            self._suggest_list.addItem("未找到匹配的蓝图")
            self._suggest_list.setVisible(True)
            return

        for r in results:
            label = r.get("zh_name") or r.get("en_name") or str(r.get("type_id"))
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._suggest_list.addItem(item)
        self._suggest_list.setVisible(True)

    def _on_suggest_clicked(self, item: QListWidgetItem):
        bp = item.data(Qt.ItemDataRole.UserRole)
        if bp:
            self._select_blueprint(bp)

    def _select_blueprint(self, bp: dict):
        self._selected_bp = bp
        self._suggest_list.setVisible(False)
        self._bp_search.setText(bp.get("zh_name") or bp.get("en_name") or str(bp.get("type_id")))
        self._load_blueprint_data()

    def _load_blueprint_data(self):
        if not self._selected_bp:
            return
        bp_id = self._selected_bp["type_id"]
        activity = self._activity_combo.currentText()
        worker = BPMaterialsWorker(bp_id, activity, self)
        worker.finished_signal.connect(self._on_materials_loaded)
        worker.start()

    def _on_materials_loaded(self, data: dict):
        self._materials = data.get("materials", [])
        self._products = data.get("products", [])
        self._bp_skills = data.get("skills", [])
        self._bp_time = data.get("time", 0)
        self._render_results()

    # ═══════════════════════════════════════
    #  渲染结果
    # ═══════════════════════════════════════

    def _render_results(self):
        if not self._products:
            self._product_label.setText("无产出物数据")
            return

        price_col = f"{self._price_combo.currentText()}_price"
        try:
            batch = int(self._batch_input.text() or "1")
            if batch < 1:
                batch = 1
        except ValueError:
            batch = 1

        prod = self._products[0]
        prod_name = prod.get("zh_name") or prod.get("en_name") or str(prod.get("type_id"))
        run_qty = prod.get("quantity", 1)
        total_out = run_qty * batch
        prod_price = prod.get(price_col)
        prod_price_str = f"{prod_price:,.2f} ISK" if prod_price else "—"

        # 时间
        time_str = ""
        if self._bp_time:
            mins = self._bp_time // 60
            secs = self._bp_time % 60
            ind_lvl = self._user_skills.get(3380, 5)
            adv_lvl = self._user_skills.get(3388, 5)
            sup_lvl = self._user_skills.get(24268, 5)
            adj_time = self._bp_time * (1 - 0.04 * ind_lvl) * (1 - 0.03 * adv_lvl) * (1 - 0.03 * sup_lvl)
            adj_mins = int(adj_time // 60)
            adj_secs = int(adj_time % 60)
            total_adj = adj_time * batch
            th = int(total_adj // 3600)
            tm = int((total_adj % 3600) // 60)
            ts = int(total_adj % 60)
            time_str = f"单次 {mins}分{secs}秒 → 技能调整 {adj_mins}分{adj_secs}秒 → ×{batch} = {th}h{tm}m{ts}s"

        self._product_label.setText(f"产出: {prod_name} × {total_out}  ({batch} runs × {run_qty})")
        self._time_label.setText(time_str)

        # 材料表
        mat_model = MaterialTableModel(self._materials, price_col, batch)
        self._mat_table.setModel(mat_model)
        self._mat_table.setColumnWidth(0, 180)
        self._mat_table.setColumnWidth(1, 80)
        self._mat_table.setColumnWidth(2, 100)
        self._mat_table.setColumnWidth(3, 100)

        # 技能
        self._build_skill_list()

        # 汇总
        self._render_summary(batch, price_col, prod_price, total_out)

    def _render_summary(self, batch, price_col, prod_price, total_out):
        total_cost = 0.0
        for mat in self._materials:
            qty = mat.get("quantity", 0) * batch
            unit_price = mat.get(price_col) or 0.0
            total_cost += qty * unit_price

        try:
            tax_pct = float(self._tax_input.text() or "0")
        except ValueError:
            tax_pct = 0
        tax_fee = total_cost * (tax_pct / 100)
        grand_total = total_cost + tax_fee

        output_price_val = prod_price if prod_price else 0.0
        total_output = output_price_val * total_out
        profit = total_output - grand_total
        margin = (profit / grand_total * 100) if grand_total > 0 else 0.0

        lines = [
            f"材料成本: {total_cost:,.2f} ISK",
            f"设施税: {tax_fee:,.2f} ISK ({tax_pct:.1f}%)",
            f"──────────────",
            f"总成本:   {grand_total:,.2f} ISK",
            f"产出价值: {total_output:,.2f} ISK ({prod_price:,.2f} × {total_out})",
        ]
        if profit >= 0:
            lines.append(f"利润:     +{profit:,.2f} ISK  ({margin:.1f}%)")
        else:
            lines.append(f"亏损:     {profit:,.2f} ISK  ({margin:.1f}%)")

        self._summary_browser.setText("\n".join(lines))

    def _build_skill_list(self):
        self._skill_data = {}
        # 全局技能
        global_skills = [
            ("Industry", 3380),
            ("Advanced Industry", 3388),
            ("Supply Chain Mgmt", 24268),
        ]
        skill_lines = ["全局制造技能:"]
        for name, sk_id in global_skills:
            cur = self._user_skills.get(sk_id, 5)
            skill_lines.append(f"  {name}: Lv{cur}")
            self._skill_data[sk_id] = cur

        # 蓝图专属
        global_ids = {s[1] for s in global_skills}
        bp_specific = [s for s in self._bp_skills if s["type_id"] not in global_ids]
        if bp_specific:
            skill_lines.append("")
            skill_lines.append("蓝图专属技能:")
            for sk in bp_specific:
                cur_lvl = sk.get("user_level", 5)
                req_lvl = sk.get("required_level", 1)
                name = sk.get("zh_name") or sk.get("en_name") or str(sk["type_id"])
                skill_lines.append(f"  {name}: Lv{cur_lvl} (需 Lv{req_lvl})")
                self._skill_data[sk["type_id"]] = cur_lvl

        # 使用简单的文本列表
        from PySide6.QtCore import QStringListModel
        model = QStringListModel()
        model.setStringList(skill_lines)
        self._skill_list.setModel(model)

    # ═══════════════════════════════════════
    #  技能
    # ═══════════════════════════════════════

    def _load_skills(self):
        worker = LoadSkillsWorker(self)
        worker.finished_signal.connect(self._on_skills_loaded)
        worker.start()

    def _on_skills_loaded(self, skills: dict[int, int]):
        self._user_skills = skills

    def _save_skills(self):
        if not self._skill_data:
            return
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            for sk_id, lvl in self._skill_data.items():
                c.execute("INSERT OR REPLACE INTO user_skills (skill_type_id, level) VALUES (?, ?)", (sk_id, lvl))
            conn.commit()
        finally:
            conn.close()

        for sk_id, lvl in self._skill_data.items():
            self._user_skills[sk_id] = lvl

        self._product_label.setText(self._product_label.text().split(" | ")[0] + " | 技能已保存")

    def _on_mat_context_menu(self, pos):
        index = self._mat_table.currentIndex()
        if not index.isValid():
            return
        menu = QMenu(self)
        view_action = QAction("查看物品详情", self)
        menu.addAction(view_action)
        copy_action = QAction("复制名称", self)
        menu.addAction(copy_action)
        menu.exec(self._mat_table.viewport().mapToGlobal(pos))

    def _recalc(self, *args):
        if self._selected_bp:
            activity = self._activity_combo.currentText()
            # Check if activity changed
            if self._bp_skills and self._selected_bp:
                self._load_blueprint_data()
            else:
                self._render_results()

    def refresh_display(self):
        if self._selected_bp:
            self._render_results()


# ═══════════════════════════════════════
#  后台 Workers
# ═══════════════════════════════════════

class BPSearchWorker(QThread):
    finished_signal = Signal(list)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            like = f"%{self._query}%"
            c.execute("""
                SELECT i.type_id, i.zh_name, i.en_name
                FROM item i
                WHERE i.type_id IN (
                    SELECT DISTINCT blueprint_type_id FROM blueprint_activities
                )
                AND (i.en_name LIKE ? OR i.zh_name LIKE ?)
                ORDER BY i.zh_name, i.en_name
                LIMIT 20
            """, (like, like))
            result = [
                {"type_id": tid, "zh_name": zh or "", "en_name": en or ""}
                for tid, zh, en in c.fetchall()
            ]
            self.finished_signal.emit(result)
        finally:
            conn.close()


class BPMaterialsWorker(QThread):
    finished_signal = Signal(dict)

    def __init__(self, bp_id: int, activity: str, parent=None):
        super().__init__(parent)
        self._bp_id = bp_id
        self._activity = activity

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            data = {}
            c = conn.cursor()

            # Materials
            c.execute("""
                SELECT bm.material_type_id, bm.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_materials bm
                JOIN item i ON bm.material_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE bm.blueprint_type_id = ? AND bm.activity = ?
                ORDER BY i.zh_name, i.en_name
            """, (self._bp_id, self._activity))
            data["materials"] = [
                {"type_id": tid, "quantity": qty, "zh_name": zh or "", "en_name": en or "",
                 "buy_price": buy, "sell_price": sell}
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]

            # Products
            c.execute("""
                SELECT bp.product_type_id, bp.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_products bp
                JOIN item i ON bp.product_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE bp.blueprint_type_id = ? AND bp.activity = ?
            """, (self._bp_id, self._activity))
            data["products"] = [
                {"type_id": tid, "quantity": qty, "zh_name": zh or "", "en_name": en or "",
                 "buy_price": buy, "sell_price": sell}
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]

            # Skills
            c.execute("""
                SELECT bs.skill_type_id, bs.level, i.zh_name, i.en_name,
                       COALESCE(u.level, 0) as user_level
                FROM blueprint_skills bs
                JOIN item i ON bs.skill_type_id = i.type_id
                LEFT JOIN user_skills u ON u.skill_type_id = bs.skill_type_id
                WHERE bs.blueprint_type_id = ? AND bs.activity = ?
                ORDER BY i.zh_name, i.en_name
            """, (self._bp_id, self._activity))
            data["skills"] = [
                {"type_id": tid, "required_level": req, "zh_name": zh or "", "en_name": en or "", "user_level": ulvl}
                for tid, req, zh, en, ulvl in c.fetchall()
            ]

            # Activity time
            c.execute("SELECT time FROM blueprint_activities WHERE blueprint_type_id = ? AND activity = ?",
                      (self._bp_id, self._activity))
            row = c.fetchone()
            data["time"] = row[0] if row else 0

            self.finished_signal.emit(data)
        finally:
            conn.close()


class LoadSkillsWorker(QThread):
    finished_signal = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT skill_type_id, level FROM user_skills")
            result = {row[0]: row[1] for row in c.fetchall()}
            self.finished_signal.emit(result)
        finally:
            conn.close()


class MaterialTableModel(QAbstractTableModel):
    _HEADERS = ["材料", "数量", "单价", "小计"]

    def __init__(self, materials: list[dict], price_col: str, batch: int):
        super().__init__()
        self._rows = []
        for mat in materials:
            qty = mat.get("quantity", 0) * batch
            unit_price = mat.get(price_col) or 0.0
            subtotal = qty * unit_price
            self._rows.append({
                "name": mat.get("zh_name") or mat.get("en_name") or str(mat.get("type_id")),
                "qty": qty,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row["name"]
            elif col == 1:
                return f"{row['qty']:,}"
            elif col == 2:
                return f"{row['unit_price']:,.2f}" if row["unit_price"] else "—"
            elif col == 3:
                return f"{row['subtotal']:,.2f}" if row["subtotal"] else "—"

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 2, 3):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

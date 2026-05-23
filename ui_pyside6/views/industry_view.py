"""
工业制造页面 — 搜索成品 → 查蓝图 → 材料成本计算
"""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QTableView, QHeaderView,
    QSplitter, QTextBrowser, QListWidget, QListWidgetItem, QFrame,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal
from core.paths import DB_PATH
from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, PRIMARY,
    TEXT_PRIMARY, TEXT_SECONDARY, GREEN, BORDER,
)


class IndustryPage(QWidget):
    """工业制造 — 搜索成品 → 查蓝图 → 材料成本"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self._has_bp = False
        self.setObjectName("industry_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 搜索工具栏 ──
        toolbar = QWidget()
        toolbar.setObjectName("industry_toolbar")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 4, 8, 4)
        tb.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入成品名称搜索（如 渡鸦级、Tritanium）...")
        self._search_input.textChanged.connect(self._on_search_text)
        tb.addWidget(self._search_input)

        self._price_combo = QComboBox()
        self._price_combo.addItems(["buy", "sell"])
        self._price_combo.setCurrentText("buy")
        tb.addWidget(QLabel("价格:"))
        tb.addWidget(self._price_combo)

        self._batch_input = QLineEdit("1")
        self._batch_input.setFixedWidth(60)
        self._batch_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        tb.addWidget(QLabel("批次:"))
        tb.addWidget(self._batch_input)

        layout.addWidget(toolbar)

        # ── 候选列表 ──
        self._suggest_list = QListWidget()
        self._suggest_list.setMaximumHeight(200)
        self._suggest_list.setVisible(False)
        self._suggest_list.itemClicked.connect(self._on_suggest_click)
        layout.addWidget(self._suggest_list)

        # ── 蓝图选择行（一个物品可能被多个蓝图产出） ──
        self._bp_selector = QWidget()
        self._bp_selector.setObjectName("bp_selector")
        self._bp_selector.setVisible(False)
        bp_sel = QHBoxLayout(self._bp_selector)
        bp_sel.setContentsMargins(8, 4, 8, 4)
        bp_sel.addWidget(QLabel("选择蓝图:"))
        self._bp_combo = QComboBox()
        self._bp_combo.currentIndexChanged.connect(self._on_bp_selected)
        bp_sel.addWidget(self._bp_combo, 1)
        layout.addWidget(self._bp_selector)

        # ── 产品信息 ──
        self._product_label = QLabel("在上方搜索成品物品，查看制造配方")
        self._product_label.setObjectName("product_label")
        layout.addWidget(self._product_label)

        # ── 材料表 + 汇总 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        self._mat_table = QTableView()
        self._mat_table.setAlternatingRowColors(True)
        self._mat_table.horizontalHeader().setStretchLastSection(True)
        self._mat_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        splitter.addWidget(self._mat_table)

        self._summary = QTextBrowser()
        self._summary.setObjectName("industry_summary")
        self._summary.setFixedWidth(280)
        splitter.addWidget(self._summary)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        layout.addWidget(splitter, 1)

        # ── 状态 ──
        self._selected_item: dict | None = None
        self._bp_list: list[dict] = []
        self._cur_bp: dict | None = None
        self._products: list[dict] = []
        self._materials: list[dict] = []
        self._bp_time: int = 0

        # 检查蓝图数据
        self._check_blueprint_db()

    def _check_blueprint_db(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM blueprint_activities")
            cnt = c.fetchone()[0]
            self._has_bp = cnt > 0
            conn.close()
        except Exception:
            self._has_bp = False

    # ── 搜索 ──

    def _on_search_text(self, text: str):
        if not text or len(text.strip()) < 1:
            self._suggest_list.setVisible(False)
            return
        worker = ProductSearchWorker(text.strip(), self)
        worker.finished_signal.connect(self._on_search_results)
        worker.start()

    def _on_search_results(self, results: list):
        self._suggest_list.clear()
        if not results:
            self._suggest_list.addItem("未找到匹配的物品")
            self._suggest_list.setVisible(True)
            return
        for r in results:
            label = f"[{r['type_id']}] {r.get('zh_name') or ''} ({r.get('en_name') or ''})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._suggest_list.addItem(item)
        self._suggest_list.setVisible(True)

    def _on_suggest_click(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._select_product(data["type_id"])
            self._suggest_list.setVisible(False)
            self._search_input.setText(data.get("zh_name") or data.get("en_name") or str(data["type_id"]))

    # ── 查询蓝图 ──

    def _select_product(self, type_id: int):
        self._selected_item = {"type_id": type_id}
        self._bp_combo.clear()
        self._bp_selector.setVisible(False)
        self._product_label.setText("正在查找制造配方...")

        worker = FindBlueprintWorker(type_id, self)
        worker.finished_signal.connect(self._on_blueprints_found)
        worker.start()

    def _on_blueprints_found(self, bp_list: list, product_name: str):
        if not bp_list or not self._has_bp:
            self._product_label.setText(
                f"{product_name} — 未找到制造配方"
                if not self._has_bp else
                f"{product_name} — 没有蓝图可以制造此物品"
            )
            self._mat_table.setModel(None)
            self._summary.setText("")
            return

        self._bp_list = bp_list
        self._bp_selector.setVisible(len(bp_list) > 1)

        for bp in bp_list:
            name = bp.get("zh_name") or bp.get("en_name") or f"蓝图 {bp['type_id']}"
            activity = bp.get("activity", "manufacturing")
            self._bp_combo.addItem(f"{name} ({activity})", bp["type_id"])

        # 默认选中第一个
        self._bp_combo.setCurrentIndex(0)
        if len(bp_list) == 1:
            self._load_bp_materials(bp_list[0]["type_id"])
            self._product_label.setText(f"{product_name} → 蓝图: {bp_list[0].get('zh_name') or bp_list[0].get('en_name') or ''}")

    def _on_bp_selected(self, idx: int):
        if idx < 0 or idx >= len(self._bp_list):
            return
        bp = self._bp_list[idx]
        self._load_bp_materials(bp["type_id"])

    def _load_bp_materials(self, bp_type_id: int):
        activity = "manufacturing"
        worker = BPMatWorker(bp_type_id, activity, self)
        worker.finished_signal.connect(self._on_materials)
        worker.start()

    def _on_materials(self, data: dict):
        self._materials = data.get("materials", [])
        self._products = data.get("products", [])
        self._bp_time = data.get("time", 0)
        self._render()

    # ── 渲染 ──

    def _render(self):
        price_col = f"{self._price_combo.currentText()}_price"
        try:
            batch = int(self._batch_input.text() or "1")
            batch = max(1, batch)
        except ValueError:
            batch = 1

        prod = self._products[0] if self._products else None
        if prod:
            prod_name = prod.get("zh_name") or prod.get("en_name") or str(prod.get("type_id"))
            run_qty = prod.get("quantity", 1)
            total_out = run_qty * batch
            prod_price = prod.get(price_col)
            self._product_label.setText(f"产出: {prod_name} × {total_out} ({batch} runs × {run_qty})")
        else:
            self._product_label.setText("无产出物数据")

        # 材料表
        model = MatTableModel(self._materials, price_col, batch)
        self._mat_table.setModel(model)
        self._mat_table.setColumnWidth(0, 180)
        self._mat_table.setColumnWidth(1, 80)
        self._mat_table.setColumnWidth(2, 100)
        self._mat_table.setColumnWidth(3, 100)

        # 汇总
        total_cost = sum(
            (m.get("quantity", 0) * batch) * (m.get(price_col) or 0.0)
            for m in self._materials
        )
        out_val = (prod_price or 0.0) * total_out if prod else 0
        profit = out_val - total_cost
        margin = (profit / total_cost * 100) if total_cost > 0 else 0

        lines = [
            f"材料成本: {total_cost:,.2f} ISK",
            f"产出价值: {out_val:,.2f} ISK",
            "──────────────",
        ]
        if profit >= 0:
            lines.append(f"利润: +{profit:,.2f} ISK ({margin:.1f}%)")
        else:
            lines.append(f"亏损: {profit:,.2f} ISK ({margin:.1f}%)")

        if self._bp_time:
            secs = self._bp_time * batch
            h, m = divmod(secs, 3600)
            m, s = divmod(m, 60)
            lines.append(f"\n时间: ×{batch} = {int(h)}h{int(m)}m{int(s)}s")

        self._summary.setText("\n".join(lines))

    def refresh_display(self):
        if self._selected_item:
            self._render()



# ═══════════════════════════════════════
#  Workers
# ═══════════════════════════════════════

class ProductSearchWorker(QThread):
    """搜索物品（成品）"""
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
                SELECT type_id, zh_name, en_name FROM item
                WHERE en_name LIKE ? OR zh_name LIKE ?
                ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                         LENGTH(en_name), type_id
                LIMIT 20
            """, (like, like, f"{self._query}%", f"{self._query}%"))
            result = [
                {"type_id": tid, "zh_name": zh or "", "en_name": en or ""}
                for tid, zh, en in c.fetchall()
            ]
            self.finished_signal.emit(result)
        finally:
            conn.close()


class FindBlueprintWorker(QThread):
    """查询哪些蓝图可以制造指定物品"""
    finished_signal = Signal(list, str)  # bp_list, product_name

    def __init__(self, product_type_id: int, parent=None):
        super().__init__(parent)
        self._pid = product_type_id

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            # 获取物品名称
            c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (self._pid,))
            row = c.fetchone()
            pname = (row[0] or row[1] or str(self._pid)) if row else str(self._pid)

            # 查找产出此物品的蓝图
            c.execute("""
                SELECT DISTINCT bp.blueprint_type_id, i.zh_name, i.en_name, bp.activity
                FROM blueprint_products bp
                JOIN item i ON bp.blueprint_type_id = i.type_id
                WHERE bp.product_type_id = ?
                ORDER BY i.zh_name, i.en_name
            """, (self._pid,))
            bps = [
                {"type_id": tid, "zh_name": zh or "", "en_name": en or "", "activity": act}
                for tid, zh, en, act in c.fetchall()
            ]
            self.finished_signal.emit(bps, pname)
        finally:
            conn.close()


class BPMatWorker(QThread):
    """获取蓝图材料 + 时间"""
    finished_signal = Signal(dict)

    def __init__(self, bp_type_id: int, activity: str, parent=None):
        super().__init__(parent)
        self._bid = bp_type_id
        self._act = activity

    def run(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            data = {}
            c = conn.cursor()

            # 材料
            c.execute("""
                SELECT bm.material_type_id, bm.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_materials bm
                JOIN item i ON bm.material_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE bm.blueprint_type_id = ? AND bm.activity = ?
                ORDER BY i.zh_name
            """, (self._bid, self._act))
            data["materials"] = [
                {"type_id": tid, "quantity": qty, "zh_name": zh or "", "en_name": en or "",
                 "buy_price": buy, "sell_price": sell}
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]

            # 产品
            c.execute("""
                SELECT bp.product_type_id, bp.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_products bp
                JOIN item i ON bp.product_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id)
                WHERE bp.blueprint_type_id = ? AND bp.activity = ?
            """, (self._bid, self._act))
            data["products"] = [
                {"type_id": tid, "quantity": qty, "zh_name": zh or "", "en_name": en or "",
                 "buy_price": buy, "sell_price": sell}
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]

            # 时间
            c.execute("SELECT time FROM blueprint_activities WHERE blueprint_type_id = ? AND activity = ?",
                      (self._bid, self._act))
            row = c.fetchone()
            data["time"] = row[0] if row else 0

            self.finished_signal.emit(data)
        finally:
            conn.close()


class MatTableModel(QAbstractTableModel):
    _HEADERS = ["材料", "数量", "单价", "小计"]

    def __init__(self, materials: list[dict], price_col: str, batch: int):
        super().__init__()
        self._rows = []
        for mat in materials:
            qty = mat.get("quantity", 0) * batch
            up = mat.get(price_col) or 0.0
            self._rows.append({
                "name": mat.get("zh_name") or mat.get("en_name") or str(mat.get("type_id")),
                "qty": qty, "unit_price": up, "subtotal": qty * up,
            })

    def rowCount(self, parent=QModelIndex()): return len(self._rows)
    def columnCount(self, parent=QModelIndex()): return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        r = self._rows[index.row()]; c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0: return r["name"]
            elif c == 1: return f"{r['qty']:,}"
            elif c == 2: return f"{r['unit_price']:,.2f}" if r["unit_price"] else "-"
            elif c == 3: return f"{r['subtotal']:,.2f}" if r["subtotal"] else "-"
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c in (1, 2, 3): return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

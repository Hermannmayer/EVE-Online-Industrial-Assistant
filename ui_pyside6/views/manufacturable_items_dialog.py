"""
??????? ? ????
"""

import json
import os
from datetime import UTC

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.paths import data_dir
from services.scoring_service import cache_key as _ck
from services.scoring_service import get_cache as _cget
from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog
from ui_pyside6.views.all_items_view import JITA_RID, AModel, ItemsW, Proxy, SearchItemsW
from ui_pyside6.views.compare_dialog import CompareDialog
from ui_pyside6.views.score_dialogs import MfgDlg, ScoreW

DASH = chr(8212)

BCOLS = [
    ("??", 36, "i"),
    ("???", 160, "z"),
    ("English", 180, "e"),
    ("??", 100, "bp"),
    ("??", 100, "sp"),
    ("??", 85, "ap"),
    ("??", 70, "v"),
]

MCOLS = [
    ("??", 105, "mc"),
    ("??", 105, "mr"),
    ("??/?", 65, "mh"),
    ("???", 100, "mdp"),
    ("??", 110, "ms"),
    ("??", 75, "_tag"),
    ("???%", 70, "mm"),
]

MFG_CATEGORIES = ["?????", "????(T1)", "????(T2)", "??????", "??"]


class MfgTreeW(QThread):
    """???????????????"""

    done = Signal(list)

    def run(self):
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            c.execute("""
                WITH RECURSIVE ancestors(id) AS (
                    SELECT DISTINCT i.market_group_id
                    FROM item i
                    JOIN blueprint_products bp ON i.type_id = bp.product_type_id
                    WHERE bp.activity = 'manufacturing'
                    UNION ALL
                    SELECT mt.parent_group_id
                    FROM market_tree mt
                    JOIN ancestors a ON mt.market_group_id = a.id
                    WHERE mt.parent_group_id IS NOT NULL
                )
                SELECT DISTINCT mt.market_group_id, mt.parent_group_id, mt.zh_name
                FROM market_tree mt
                WHERE mt.market_group_id IN (SELECT id FROM ancestors)
                ORDER BY mt.zh_name
            """)
            r = [{"id": i, "p": p, "n": z or f"G{i}"} for i, p, z in c.fetchall()]
            self.done.emit(r)


class ManufacturableItemsDialog(QDialog):
    """?????????"""

    def __init__(self, parent=None):
        super().__init__()
        self.setWindowTitle("?????")
        self.resize(1100, 680)
        self.setMinimumSize(800, 400)
        self._data = []
        self._filt = []
        self._mfg = {"hub": "Jita", "char": "main", "tax": 0}
        self._show_score = True
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        self._load_settings()
        self._build_ui()
        self._tw = MfgTreeW(self)
        self._tw.done.connect(self._ot)
        self._tw.start()
        self._iw = ItemsW(rid=JITA_RID, parent=self)
        self._iw.done.connect(self._od)
        self._iw.start()
        theme.add_theme_listener(self._on_theme_changed)

    def closeEvent(self, ev):
        for t in (self._tw, self._iw, self._wp, self._sw):
            if t and t.isRunning():
                t.quit()
                t.wait(2000)
        super().closeEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._refresh_styles()

    def _export_data(self):
        from ui_pyside6.views.export_helper import export_to_csv, export_to_excel, get_save_filename

        if self._md.rowCount() == 0:
            self._st.setText("???????")
            return
        try:
            path = get_save_filename(self, "manufacturable_items.csv", "CSV (*.csv);;Excel (*.xlsx)")
            if not path:
                return
            cols = self._md._cols
            headers = [c[0] for c in cols if c[2] != "i"]
            rows = []
            for row in self._md._rows:
                r = []
                for _, _, key in cols:
                    if key == "i":
                        continue
                    v = row.get(key)
                    if v is None:
                        r.append("")
                    elif isinstance(v, float):
                        r.append(f"{v:.2f}")
                    else:
                        r.append(str(v))
                rows.append(r)
            if path.endswith(".xlsx"):
                export_to_excel(headers, rows, path)
            else:
                export_to_csv(headers, rows, path)
            self._st.setText(f"??? {len(rows)} ?")
        except Exception as e:
            self._st.setText(f"????: {e}")

    def _on_theme_changed(self):
        self._refresh_styles()

    def _refresh_styles(self):
        self.setStyleSheet(
            f"QDialog{{background:{theme.BG_DARK};}}QLabel{{color:{theme.TEXT_SECONDARY};font-size:11px;}}"
        )
        self._st.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:11px;")

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)

        def _bt(t, cb, w=60):
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.setFixedWidth(w)
            b.setStyleSheet(
                f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
                f"border:1px solid {theme.BORDER};border-radius:2px;font-size:11px;padding:0 2px;}}"
                f"QPushButton:hover{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            b.clicked.connect(cb)
            return b

        bx = QHBoxLayout()
        bx.setContentsMargins(2, 0, 2, 0)
        bx.setSpacing(2)
        self._score_btn = _bt("????", self._on_mfg)
        bx.addWidget(self._score_btn)
        bx.addWidget(_bt("??", self._smfg, 30))
        bx.addStretch()
        bx.addWidget(_bt("????", self._on_compare, 60))
        bx.addWidget(_bt("??", self._export_data, 50))
        self._pin_btn = _bt("??", self._on_pin_toggled, 35)
        bx.addWidget(self._pin_btn)
        lay.addLayout(bx)

        fx = QHBoxLayout()
        fx.setContentsMargins(2, 0, 2, 0)
        fx.setSpacing(2)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("??????? ID...")
        self._search_input.setFixedHeight(22)
        self._search_input.textChanged.connect(self._on_search_text)
        fx.addWidget(self._search_input)
        fx.addWidget(QLabel("??:"))
        self._cat = QComboBox()
        self._cat.addItems(MFG_CATEGORIES)
        self._cat.currentIndexChanged.connect(self._apply)
        fx.addWidget(self._cat)
        self._st = QLabel("??")
        fx.addStretch()
        fx.addWidget(self._st)
        lay.addLayout(fx)

        self._pr = QProgressBar()
        self._pr.setFixedHeight(3)
        self._pr.setVisible(False)
        lay.addWidget(self._pr)

        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.setHandleWidth(1)
        self._tr = QTreeWidget()
        self._tr.setHeaderHidden(True)
        self._tr.setMinimumWidth(100)
        self._tr.setMaximumWidth(250)
        self._tr.itemClicked.connect(self._on_tree)
        sp.addWidget(self._tr)

        self._tv = QTableView()
        self._tv.setAlternatingRowColors(True)
        self._tv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tv.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tv.customContextMenuRequested.connect(self._ctx)
        self._tv.doubleClicked.connect(self._dbl)
        self._tv.clicked.connect(self._clk)
        self._tv.verticalHeader().setDefaultSectionSize(28)
        self._tv.setSortingEnabled(True)
        hh = self._tv.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        sp.addWidget(self._tv)
        sp.setSizes([140, 960])
        lay.addWidget(sp, 1)

        self._md = AModel()
        self._px = Proxy()
        self._px.setSourceModel(self._md)
        self._tv.setModel(self._px)
        self._setw(BCOLS)

    def _setw(self, cols):
        for i, (_, w, _) in enumerate(cols):
            self._tv.setColumnWidth(i, w)

    def _on_compare(self):
        sel = self._tv.selectionModel().selectedRows()
        items = []
        for idx in sel:
            row = self._md.data(idx, Qt.ItemDataRole.UserRole)
            if row and row.get("id"):
                items.append({"type_id": row["id"], "name": row.get("z", "")})
        dlg = CompareDialog(initial_items=items)
        dlg.show()

    def _ot(self, items):
        self._tr.clear()
        nm = {}
        for d in items:
            n = QTreeWidgetItem([d["n"]])
            n.setData(0, Qt.ItemDataRole.UserRole, d["id"])
            nm[d["id"]] = n
        for d in items:
            n = nm[d["id"]]
            p = d.get("p")
            if p is not None and p in nm:
                nm[p].addChild(n)
            else:
                self._tr.addTopLevelItem(n)

    def _od(self, rows):
        self._data = rows
        hp = any(r.get("bp") or r.get("sp") for r in rows[:100])
        self._st.setText(f"? {len(rows)} ?" if hp else "?????????????")
        self._apply()

    def _on_tree(self, item):
        ids = set()

        def c(n):
            mid = n.data(0, Qt.ItemDataRole.UserRole)
            if mid:
                ids.add(mid)
            for i in range(n.childCount()):
                c(n.child(i))

        c(item)
        if ids:
            self._search_input.clear()
            self._data = []
            self._iw = ItemsW(list(ids), rid=JITA_RID, parent=self)
            self._iw.done.connect(self._od)
            self._iw.start()

    def _on_search_text(self, text):
        self._search_query = text.strip()
        self._debounce.start(200)

    def _do_search(self):
        q = self._search_query
        if not q:
            return
        if self._sw and self._sw.isRunning():
            self._sw.quit()
            self._sw.wait(1000)
        self._st.setText("???...")
        self._sw = SearchItemsW(q, JITA_RID, self)
        self._sw.done.connect(self._on_search_done)
        self._sw.start()

    def _on_search_done(self, rows):
        self._data = rows
        self._apply()

    def _apply(self):
        data = self._data
        cat = self._cat.currentIndex()
        if data and len(data) > 0:
            with get_container().db.connect("ref", "bp") as conn:
                c = conn.cursor()
                if cat == 0:
                    c.execute("SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity='manufacturing'")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 1:
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        WHERE bp.activity='manufacturing'
                        AND bp.blueprint_type_id NOT IN (
                            SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                        )""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 2:
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        WHERE bp.activity='manufacturing'
                        AND bp.blueprint_type_id IN (
                            SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                        )""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 3:
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        JOIN item i ON bp.product_type_id=i.type_id
                        WHERE bp.activity='manufacturing' AND (
                            i.en_name LIKE '%Navy%' OR i.en_name LIKE '%Faction%'
                            OR i.en_name LIKE '%Imperial%' OR i.en_name LIKE '%Republic%'
                            OR i.en_name LIKE '%Federation%' OR i.en_name LIKE '%State%')""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 4:
                    c.execute("SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity='reaction'")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
        self._filt = data
        self._upd()

    def _load_settings(self):
        p = os.path.join(data_dir(), "mfg_browser_settings.json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
                self._mfg.update(s.get("mfg", {}))
                self._show_score = s.get("show_score", True)
            except Exception:
                pass

    def _save_settings(self):
        p = os.path.join(data_dir(), "mfg_browser_settings.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"mfg": self._mfg, "show_score": self._show_score}, f, ensure_ascii=False, indent=2)

    def _upd(self):
        scroll_pos = None
        vbar = self._tv.verticalScrollBar()
        if vbar:
            scroll_pos = vbar.value()
        if self._show_score:
            cols = list(BCOLS)
            cols[3] = (f"???{self._mfg['hub']}?", 100, "bp")
            cols[4] = (f"???{self._mfg['hub']}?", 100, "sp")
            cols.extend(MCOLS)
            self._md.set_cols(cols)
            self._setw(cols)
            if self._filt:
                self._calc()
            else:
                self._st.setText("???")
        else:
            self._md.set_cols(BCOLS)
            self._setw(BCOLS)
            self._md.set_rows(self._filt)
            self._st.setText(f"? {len(self._filt)} ?" if self._filt else "???")
            if scroll_pos and vbar:
                QTimer.singleShot(0, lambda: vbar.setValue(min(scroll_pos, vbar.maximum())))

    def _calc(self):
        self._pr.setVisible(True)
        self._pr.setRange(0, len(self._filt))
        self._st.setText("?????...")
        self._wp = ScoreW(list(self._filt), True, self._mfg, self)
        self._wp.progress.connect(lambda c, t: self._pr.setValue(c))
        self._wp.done.connect(self._cd)
        self._wp.start()

    def _cd(self, rows):
        self._filt = rows
        self._md.set_rows(rows)
        self._pr.setVisible(False)
        self._st.setText(f"? {len(self._filt)} ? | ?????")

    def _on_mfg(self):
        self._show_score = not self._show_score
        self._score_btn.setText("????" if self._show_score else "????")
        self._save_settings()
        self._upd()

    def _smfg(self):
        dlg = MfgDlg(self._mfg, self)
        if dlg.exec():
            before_hub = self._mfg.get("hub", "Jita")
            self._mfg.update(dlg.get())
            self._save_settings()
            if before_hub != self._mfg.get("hub", "Jita") and self._show_score:
                self._upd()

    def _on_pin_toggled(self, checked):
        if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            self._pin_btn.setText("??")
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self._pin_btn.setText("??")
        self.show()

    def _clk(self, idx):
        row = idx.data(Qt.ItemDataRole.UserRole)
        if not row:
            return
        cols = self._md._cols
        col_idx = idx.column()
        if col_idx < len(cols):
            _, _, key = cols[col_idx]
            val = row.get(key)
            if val is not None and str(val).strip() and str(val) != DASH:
                QApplication.instance().clipboard().setText(str(val))

    def _dbl(self, idx):
        row = idx.data(Qt.ItemDataRole.UserRole)
        if not row:
            return
        tid = row.get("id")
        if not tid:
            return
        from ui_pyside6.views.all_items_view import MatDlg

        dlg = MatDlg(tid, self)
        dlg.exec()

    def _ctx(self, pos):
        idx = self._tv.currentIndex()
        if not idx.isValid():
            return
        r = idx.data(Qt.ItemDataRole.UserRole)
        if not r:
            return
        tid = r.get("id")
        if not tid:
            return

        m = QMenu(self)
        m.setStyleSheet(
            f"QMenu{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};border:1px solid {theme.BORDER};}}"
            f"QMenu::item{{padding:4px 20px;}}"
            f"QMenu::item:selected{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};}}"
        )

        if self._show_score:
            k = _ck(tid, "mfg", self._mfg["hub"], self._mfg["char"])
            res = _cget(k)
            if res:
                d = self._ds(res, True)
                a_brkd = QAction("??????", self)
                a_brkd.triggered.connect(lambda *a: QMessageBox.information(self, "??????", d))
                m.addAction(a_brkd)

        m.addSeparator()
        _ctx_name = r.get("z", "") or r.get("e", "") or str(tid)

        def _do_add_plan():
            score = {}
            if self._show_score:
                k = _ck(tid, "mfg", self._mfg["hub"], self._mfg["char"])
                cached = _cget(k)
                if cached:
                    score = cached
            from datetime import datetime

            dlg = AddPlanDialog(_ctx_name, score, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            with get_container().db.connect("user") as conn:
                iskph = score.get("isk_per_hour", 0) or score.get("breakdown", {}).get("isk_per_hour", 0)
                mat_cost = score.get("breakdown", {}).get("material_cost", 0)
                conn.execute(
                    "INSERT INTO production_plans "
                    "(product_type_id, product_name, runs, parallels, me_level, te_level, "
                    "mat_hub, sell_hub, facility, char_name, status, "
                    "profit, margin, score, iskph, material_cost, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?)",
                    (
                        tid,
                        _ctx_name,
                        data["runs"],
                        data["parallels"],
                        data["me"],
                        data["te"],
                        self._mfg.get("hub", "Jita"),
                        self._mfg.get("hub", "Jita"),
                        data.get("fac", ""),
                        data.get("char", ""),
                        score.get("profit_per_run", 0),
                        score.get("margin_pct", 0),
                        score.get("score", 0),
                        iskph,
                        mat_cost,
                        datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            QMessageBox.information(self, "??", f"???????: {_ctx_name}")

        a_add = QAction("??????", self)
        a_add.triggered.connect(_do_add_plan)
        m.addAction(a_add)
        m.exec(self._tv.viewport().mapToGlobal(pos))

    def _ds(self, r, is_mfg):
        if is_mfg:
            b = r.get("breakdown", {})
            st = r.get("status", "")
            if st:
                tips = {"no_blueprint": "???", "no_price": "?????", "no_mats": "??????"}
                return f"??: {tips.get(st, st)}"
            lines = [
                f"??: {r.get('score', 0):.0f}",
                f"????: {r.get('profit_per_run', 0):,.0f} ISK",
                f"???: {r.get('margin_pct', 0):.1f}%",
                f"?????: {r.get('isk_per_hour', 0):,.0f} ISK",
                f"????: {b.get('material_cost', 0):,.0f} ISK",
            ]
            run_cost = b.get("run_cost", 0)
            if run_cost:
                lines.append(f"????: {run_cost:,.0f} ISK")
            install = b.get("install_fee", 0)
            if install:
                lines.append(f"???: {install:,.0f} ISK")
            broker = b.get("broker_fee", 0)
            if broker:
                lines.append(f"???: {broker:,.0f} ISK")
            sales_tax = b.get("sales_tax", 0)
            if sales_tax:
                lines.append(f"???: {sales_tax:,.0f} ISK")
            _nl = chr(10)
            return _nl.join(lines)
        return ""

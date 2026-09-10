"""
全物品浏览器 — 非模态弹窗
"""

import json
import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.cache import TtlLRUCache
from core.container import get_container
from core.logger import log
from core.paths import ICON_DIR
from services.terminology import term
from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog
from ui_pyside6.models.all_items_models import BCOLS, DASH, MCOLS, TCOLS, AModel, Proxy
from ui_pyside6.views.compare import CompareDialog
from ui_pyside6.views.score_dialogs import MfgDlg, ScoreW, TradeDlg
from ui_pyside6.workers.all_items_workers import JITA_RID, ItemsW, SearchItemsW, TreeW

_cache = TtlLRUCache(max_size=500, ttl_seconds=1800)

CATEGORIES = [
    term.market_category("all"),
    term.market_category("unmanufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
    term.market_category("planetary"),
]
MFG_CATEGORIES = [
    term.market_category("all_manufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
]


class MatDlg(QDialog):
    def __init__(self, tid, parent=None):
        super().__init__(parent)
        self.setWindowTitle("制造材料")
        self.setMinimumSize(460, 280)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        container = get_container()
        nm = container.item_repo.get_name(tid)
        lay.addWidget(
            QLabel(f"制造材料: {nm}", styleSheet=f"color:{theme.PRIMARY};font-size:{theme.fs(13)}px;font-weight:bold;")
        )
        materials = container.blueprint_repo.get_manufacturing_materials(tid)
        if materials is None:
            lay.addWidget(QLabel("此物品无制造蓝图", styleSheet=f"color:{theme.ACCENT_RED};"))
            b = QPushButton("关闭")
            b.clicked.connect(self.accept)
            lay.addWidget(b)
            return
        _, mats = materials
        lst = QListWidget()
        total = 0.0
        for mid, qty, zh, en, sp in mats:
            n = zh or en or str(mid)
            p = sp or 0
            sub = p * qty
            total += sub
            ip = os.path.join(ICON_DIR, f"{mid}.png")
            ic = QIcon(ip) if os.path.exists(ip) else QIcon()
            it = QListWidgetItem(ic, f"  {n} x{qty:,} @ {p:,.2f} = {sub:,.2f}")
            it.setSizeHint(QSize(0, 32))
            lst.addItem(it)
        lay.addWidget(lst)
        lay.addWidget(
            QLabel(
                f"总成本: {total:,.2f} ISK",
                styleSheet=f"color:{theme.ACCENT_GREEN};font-size:{theme.fs(12)}px;font-weight:bold;",
            )
        )
        b = QPushButton("关闭")
        b.clicked.connect(self.accept)
        lay.addWidget(b)


class AllItemsDialog(QDialog):
    def __init__(self, parent=None, manufacturable_only: bool = False):
        super().__init__()  # 无 parent，完全独立窗口
        self.setWindowTitle("全物品查询")
        if manufacturable_only:
            self.setWindowTitle("可制造物品 - 添加至生产计划")
        self.resize(1100, 680)
        self.setMinimumSize(800, 400)
        # 独立窗口 + 任务栏入口，断开与主窗口的关联
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._data: list[dict] = []
        self._manufacturable_only = manufacturable_only
        self._filt: list[dict] = []
        self._bp_cached = None
        self._mfg = {"hub": "Jita", "char": "main", "tax": 0}
        self._trade = {"bh": "Amarr", "sh": "Jita", "bs": "sell", "ss": "sell", "char": "main"}
        self._show_m = False
        self._show_t = False
        self._wp = None
        self._tw = None
        self._iw = None
        self._sw = None
        self._search_query = ""
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        self._load_settings()
        self._build_ui()
        self._tw = TreeW(self)
        self._tw.done.connect(self._ot)
        self._tw.start()
        self._iw = ItemsW(rid=JITA_RID, parent=self)
        self._iw.done.connect(self._od)
        self._iw.start()
        theme.add_theme_listener(self._on_theme_changed)

    def closeEvent(self, ev):
        for t in (self._tw, self._iw, self._wp, self._sw):
            if t and t.isRunning():
                t.requestInterruption()
                t.wait(2000)
        super().closeEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._refresh_styles()

    def _export_data(self):
        """导出当前表格数据为 CSV 或 Excel"""
        from ui_pyside6.views.export_helper import export_to_csv, export_to_excel, get_save_filename

        if self._md.rowCount() == 0:
            self._st.setText("没有数据可导出")
            return

        path = get_save_filename(self, "物品数据.csv", "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not path:
            return

        # 获取当前列信息（跳过图标列）
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
                elif isinstance(v, int | float):
                    r.append(f"{v:,.2f}")
                else:
                    r.append(str(v))
            rows.append(r)

        try:
            if path.endswith(".xlsx"):
                export_to_excel(headers, rows, path)
            else:
                export_to_csv(headers, rows, path)
            self._st.setText(f"已导出 {len(rows)} 行")
        except Exception as e:
            self._st.setText(f"导出失败: {e}")

    def _on_theme_changed(self):
        if self.isVisible():
            self._refresh_styles()

    def _refresh_styles(self):
        self._toolbar.setStyleSheet(f"background:{theme.BG_SURFACE};border-bottom:1px solid {theme.BORDER};")
        self._filter_bar.setStyleSheet(f"background:{theme.BG_DARK};border-bottom:1px solid {theme.BORDER};")
        for b in self._toolbar_btns:
            ss = (
                f"QPushButton{{background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};"
                f"border:1px solid {theme.BORDER};border-radius:2px;padding:2px 6px;"
                f"font-size:{theme.fs(11)}px;min-width:60px;}}"
                f"QPushButton:hover{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            b.setStyleSheet(ss)
        self._pin.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:{theme.fs(11)}px;")
        self._search_input.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:{theme.fs(11)}px;"
        )
        self._cat.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:{theme.fs(11)}px;"
        )
        self._st.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;")

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)

        def _bt(t, cb, w=60):
            b = QPushButton(t)
            ss = (
                f"QPushButton{{background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};"
                f"border:1px solid {theme.BORDER};border-radius:2px;padding:2px 6px;"
                f"font-size:{theme.fs(11)}px;min-width:{w}px;}}"
                f"QPushButton:hover{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            b.setStyleSheet(ss)
            b.clicked.connect(cb)
            return b

        tb = QWidget()
        tb.setStyleSheet(f"background:{theme.BG_SURFACE};border-bottom:1px solid {theme.BORDER};")
        self._toolbar = tb
        bx = QHBoxLayout(tb)
        bx.setContentsMargins(4, 2, 4, 2)
        bx.setSpacing(3)
        bx.addWidget(_bt("制造评分", self._on_mfg))
        bx.addWidget(_bt("设置", self._smfg, 30))
        bx.addWidget(_bt("贸易评分", self._on_trade))
        bx.addWidget(_bt("设置", self._strade, 30))
        bx.addWidget(_bt("批量对比", self._on_compare, 60))
        bx.addWidget(_bt("导出", self._export_data, 50))
        self._toolbar_btns = [
            _bt("制造评分", self._on_mfg),
            _bt("设置", self._smfg, 30),
            _bt("贸易评分", self._on_trade),
            _bt("设置", self._strade, 30),
            _bt("批量对比", self._on_compare, 60),
            _bt("导出", self._export_data, 50),
        ]
        for b in self._toolbar_btns:
            bx.addWidget(b)
        bx.addStretch()
        self._pin = QCheckBox("置顶")
        self._pin.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:{theme.fs(11)}px;")
        self._pin.toggled.connect(self._on_pin_toggled)
        bx.addWidget(self._pin)
        lay.addWidget(tb)
        fb = QWidget()
        fb.setStyleSheet(f"background:{theme.BG_DARK};border-bottom:1px solid {theme.BORDER};")
        self._filter_bar = fb
        fx = QHBoxLayout(fb)
        fx.setContentsMargins(4, 1, 4, 1)
        fx.setSpacing(3)
        fx.addWidget(QLabel("搜索:", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("名称/ID...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:{theme.fs(11)}px;"
        )
        self._search_input.textChanged.connect(self._on_search_text)
        fx.addWidget(self._search_input)
        fx.addWidget(QLabel("类别:", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;"))
        self._cat = QComboBox()
        if self._manufacturable_only:
            self._cat.addItems(MFG_CATEGORIES)
        else:
            self._cat.addItems(CATEGORIES)
        self._cat.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:{theme.fs(11)}px;"
        )
        self._cat.currentIndexChanged.connect(self._apply)
        fx.addWidget(self._cat)
        self._st = QLabel("就绪", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;")
        fx.addStretch()
        fx.addWidget(self._st)
        lay.addWidget(fb)
        self._pr = QProgressBar()
        self._pr.setFixedHeight(3)
        self._pr.setVisible(False)
        self._pr.setStyleSheet(
            f"QProgressBar{{background:{theme.BG_SURFACE};border:none;border-radius:1px;}}QProgressBar::chunk{{background:{theme.PRIMARY};border-radius:1px;}}"
        )
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
        """打开批量对比对话框，传入当前选中物品"""
        sel = self._tv.selectionModel().selectedRows()
        items = []
        for idx in sel:
            row = self._md.data(idx, Qt.ItemDataRole.UserRole)
            if row and row.get("id"):
                items.append({"type_id": row["id"], "name": row.get("z", "")})
        dlg = CompareDialog(initial_items=items, parent=self)
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
        self._st.setText(f"共 {len(rows)} 条" if hp else "暂无价格，请先在主界面更新")
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

    # ── 搜索 ──

    def _on_search_text(self, text):
        self._search_query = text.strip()
        self._debounce.start(200)

    def _do_search(self):
        q = self._search_query
        if not q:
            return
        if self._sw and self._sw.isRunning():
            self._sw.requestInterruption()
            self._sw.wait(1000)
        self._st.setText("搜索中...")
        self._sw = SearchItemsW(q, JITA_RID, self)
        self._sw.done.connect(self._on_search_done)
        self._sw.start()

    def _on_search_done(self, rows):
        self._data = rows
        self._apply()

    def _apply(self):
        data = self._data
        cat = self._cat.currentIndex()
        # manufacturable_only mode
        if self._manufacturable_only:
            if data and len(data) > 0:
                blueprint_repo = get_container().blueprint_repo
                if cat == 0:  # all manufacturable
                    bp_ids = set(blueprint_repo.get_all_product_ids("manufacturing"))
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 1:  # T1
                    bp_ids = blueprint_repo.get_t1_manufacturable_product_ids()
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 2:  # T2 invention
                    bp_ids = blueprint_repo.get_t2_manufacturable_product_ids()
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 3:  # faction
                    bp_ids = blueprint_repo.get_faction_manufacturable_product_ids()
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 4:  # reaction
                    bp_ids = set(blueprint_repo.get_all_product_ids("reaction"))
                    data = [r for r in data if r["id"] in bp_ids]
            self._filt = data
            self._upd()
            return

        # original mode
        if data and cat > 0:
            blueprint_repo = get_container().blueprint_repo
            if cat == 1:  # 无法制造获得 — 没有任何蓝图
                bp_ids = blueprint_repo.get_all_blueprint_product_ids()
                data = [r for r in data if r["id"] not in bp_ids]
            elif cat == 2:  # 蓝图制造 T1 — 有制造蓝图，且该蓝图非发明产物
                bp_ids = blueprint_repo.get_t1_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 3:  # 发明制造 T2 — 有制造蓝图，且该蓝图由发明产出
                bp_ids = blueprint_repo.get_t2_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 4:  # 势力蓝图制造
                bp_ids = blueprint_repo.get_faction_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 5:  # 反应
                bp_ids = set(blueprint_repo.get_all_product_ids("reaction"))
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 6:  # 行星开发
                pi_ids = get_container().item_repo.get_planetary_product_ids()
                data = [r for r in data if r["id"] in pi_ids]
        self._filt = data
        self._upd()

    def _load_settings(self):
        import os

        from core.paths import data_dir

        p = os.path.join(data_dir(), "score_settings.json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
                self._mfg.update(s.get("mfg", {}))
                self._trade.update(s.get("trade", {}))
            except Exception:
                pass

    def _save_settings(self):
        import os

        from core.paths import data_dir

        p = os.path.join(data_dir(), "score_settings.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"mfg": self._mfg, "trade": self._trade}, f, ensure_ascii=False, indent=2)

    def _upd(self):
        vbar = self._tv.verticalScrollBar()
        scroll_pos = vbar.value() if vbar else 0
        if self._show_m:
            cols = list(BCOLS)
            cols[3] = (f"买价（{self._mfg['hub']}）", 100, "bp")
            cols[4] = (f"卖价（{self._mfg['hub']}）", 100, "sp")
            cols.extend(MCOLS)
            self._md.set_cols(cols)
            self._setw(cols)
            if self._filt:
                self._calc(True)
            else:
                self._st.setText("无数据")
        elif self._show_t:
            cols = list(BCOLS)
            ptn = {"buy": "买单", "sell": "卖单"}
            cols[3] = (f"买价（{self._trade['bh']}{ptn.get(self._trade['bs'], '')}）", 100, "bp")
            cols[4] = (f"卖价（{self._trade['sh']}{ptn.get(self._trade['ss'], '')}）", 100, "sp")
            cols.extend(TCOLS)
            self._md.set_cols(cols)
            self._setw(cols)
            if self._filt:
                self._calc(False)
            else:
                self._st.setText("无数据")
        else:
            self._md.set_cols(BCOLS)
            self._setw(BCOLS)
            self._md.set_rows(self._filt)
            self._st.setText(f"共 {len(self._filt)} 条")
            if scroll_pos and vbar:
                QTimer.singleShot(0, lambda: vbar.setValue(min(scroll_pos, vbar.maximum())))

    def _calc(self, is_mfg):
        self._pr.setVisible(True)
        self._pr.setRange(0, len(self._filt))
        self._st.setText("计算评分中...")
        cfg = self._mfg if is_mfg else self._trade
        self._wp = ScoreW(list(self._filt), is_mfg, cfg, self)
        self._wp.progress.connect(lambda c, t: self._pr.setValue(c))
        self._wp.done.connect(self._cd)
        self._wp.start()

    def _cd(self, rows):
        self._pr.setVisible(False)
        self._filt = rows
        self._md.set_rows(self._filt)
        self._st.setText(f"共 {len(self._filt)} 条 | 评分已计算")

    def _on_mfg(self):
        self._show_m = True
        self._show_t = False
        self._upd()

    def _on_trade(self):
        self._show_t = True
        self._show_m = False
        self._upd()

    def _smfg(self):
        d = MfgDlg(self._mfg, self)
        if d.exec():
            self._mfg = d.get()
        self._save_settings()
        if self._show_m:
            self._upd()

    def _strade(self):
        d = TradeDlg(self._trade, self)
        if d.exec():
            self._trade = d.get()
        self._save_settings()
        if self._show_t:
            self._upd()

    def _on_pin_toggled(self, checked):
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes

            hwnd = int(self.winId())
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            swp = ctypes.windll.user32.SetWindowPos
            swp.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            swp.restype = ctypes.wintypes.BOOL
            swp(hwnd, HWND_TOPMOST if checked else HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        else:
            flags = self.windowFlags()
            if checked:
                self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            else:
                self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self.setVisible(True)

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
        r = idx.data(Qt.ItemDataRole.UserRole)
        if r and r.get("id"):
            MatDlg(r["id"], self).exec()

    def _ctx(self, pos):
        idx = self._tv.currentIndex()
        if not idx.isValid():
            return
        r = idx.data(Qt.ItemDataRole.UserRole)
        if not r:
            return
        m = QMenu(self)
        a1 = QAction(f"复制: {r.get('z', '')}", self)
        a1.triggered.connect(lambda: QApplication.instance().clipboard().setText(r.get("z", "")))
        m.addAction(a1)
        a2 = QAction(f"复制ID: {r['id']}", self)
        a2.triggered.connect(lambda: QApplication.instance().clipboard().setText(str(r["id"])))
        m.addAction(a2)
        m.addSeparator()
        tid = r["id"]
        if self._show_m:
            k = f"{tid}|mfg|{self._mfg['hub']}|{self._mfg['char']}"
            res = _cache.get(k)
            if res:
                d = self._ds(res, True)
                a3 = QAction("制造核算明细", self)
                a3.triggered.connect(lambda *a: QMessageBox.information(self, "制造核算明细", d))
                m.addAction(a3)
        if self._show_t:
            k = f"{tid}|trade|{self._trade['bh'] + self._trade['sh']}|{self._trade['char']}"
            res = _cache.get(k)
            if res:
                d = self._ds(res, False)
                a4 = QAction("贸易核算明细", self)
                a4.triggered.connect(lambda *a: QMessageBox.information(self, "贸易核算明细", d))
                m.addAction(a4)
        m.addSeparator()
        _ctx_name = r.get("z", "") or r.get("e", "") or str(tid)

        def _do_add_plan():
            score = {}
            if self._show_m:
                k = f"{tid}|mfg|{self._mfg['hub']}|{self._mfg['char']}"
                cached = _cache.get(k)
                if cached:
                    score = cached
            dlg = AddPlanDialog(_ctx_name, score, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            from services import inventory_manager, user_settings
            from services.plan_service import insert_plan

            mat_hangar_id, solar_system_id = inventory_manager.get_default_mat_hangar_and_system()
            iskph = score.get("isk_per_hour", 0) or score.get("breakdown", {}).get("isk_per_hour", 0)
            mat_cost = score.get("breakdown", {}).get("material_cost", 0)
            metrics = {
                "profit": score.get("profit_per_run", 0) or 0,
                "margin": score.get("margin_pct", 0) or 0,
                "score": score.get("score", 0) or 0,
                "iskph": iskph,
                "material_cost": mat_cost,
                "calculated_time": (score.get("hours_per_run", 0) or 0) * 3600,
                "daily_output": 0,
            }
            insert_plan(
                tid,
                _ctx_name,
                data,
                mat_hub=self._mfg["hub"],
                sell_hub=self._mfg["hub"],
                facility=data["fac"],
                solar_system_id=solar_system_id,
                mat_hangar_id=mat_hangar_id,
                deposit_hangar_id=user_settings.get_default_hangar_id("default_deposit_hangar_id"),
                metrics=metrics,
            )
            QMessageBox.information(self, "提示", f"已加入制造列表: {_ctx_name}")

        a5 = QAction("加入制造列表", self)
        a5.triggered.connect(_do_add_plan)
        m.addAction(a5)

        # 科研入口：仅在选中蓝图时有意义（对物品行点了会提示）
        def _do_research(kind: str):
            def _run():
                self._add_research_plan(tid, _ctx_name, kind)

            return _run

        m.addSeparator()
        a6 = QAction("加入拷贝规划", self)
        a6.triggered.connect(_do_research("copying"))
        m.addAction(a6)
        a7 = QAction("加入发明规划", self)
        a7.triggered.connect(_do_research("invention"))
        m.addAction(a7)
        a8 = QAction("加入效率研究规划", self)
        a8.triggered.connect(_do_research("research"))
        m.addAction(a8)

        m.exec(self._tv.viewport().mapToGlobal(pos))

    def _add_research_plan(self, type_id: int, name: str, kind: str) -> None:
        """从全物品页直接建科研计划。

        物品 → 蓝图：制造蓝图查 blueprint_products；蓝图物品本身就是蓝图 type_id。
        其余情况给出提示（不是所有物品都能拷贝/发明/研究）。
        """
        from core.container import get_container
        from services.research_plans import (
            create_research_plan,
            invention_base_runs,
            resolve_invention_source,
        )

        db = get_container().db
        bp_id = int(type_id)
        try:
            with db.connect("bp", "ref") as conn:
                is_bp_item = bool(
                    conn.execute(
                        "SELECT 1 FROM blueprint_activities WHERE blueprint_type_id = ? LIMIT 1", (bp_id,)
                    ).fetchone()
                )
                if not is_bp_item:
                    row = conn.execute(
                        "SELECT blueprint_type_id FROM blueprint_products " "WHERE product_type_id = ? LIMIT 1",
                        (bp_id,),
                    ).fetchone()
                    if not row:
                        QMessageBox.information(self, "提示", f"「{name}」没有蓝图，无法加入科研规划")
                        return
                    bp_id = int(row[0])
                src = resolve_invention_source(conn, bp_id) if kind == "invention" else None
                copy_row = conn.execute(
                    "SELECT max_production_limit FROM blueprint_activities "
                    "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
                    (bp_id,),
                ).fetchone()
                base_runs = (
                    {
                        int(oc["blueprint_type_id"]): invention_base_runs(
                            conn, int(oc["blueprint_type_id"]), int(src["t1_blueprint_type_id"])
                        )
                        for oc in src["outcomes"]
                    }
                    if src
                    else {}
                )
        except Exception:
            log.exception("读取蓝图信息失败 type_id=%s", type_id)
            QMessageBox.warning(self, "提示", "读取蓝图信息失败，见日志")
            return

        from ui_pyside6.dialogs.research_plan_dialogs import (
            CopyPlanDialog,
            InventionPlanDialog,
            ResearchPlanDialog,
        )

        dlg: QDialog
        if kind == "invention":
            if src is None:
                QMessageBox.information(self, "提示", f"「{name}」不是 T2/T3 蓝图，无法发明")
                return
            dlg = InventionPlanDialog(
                src["t1_name"],
                outcomes=src["outcomes"],
                base_runs_by_outcome=base_runs,
                default_probability={
                    int(o["blueprint_type_id"]): float(o["base_probability"]) for o in src["outcomes"]
                },
                parent=self,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data() or {}
            prod = int(data.get("product_blueprint_type_id") or 0)
            if not prod:
                QMessageBox.information(self, "提示", "未选择发明产物")
                return
            create_research_plan(
                prod,
                activity="invention",
                blueprint_name=data.get("product_name") or str(prod),
                runs=int(data.get("attempts") or 1),
                mat_hangar_id=data.get("mat_hangar_id"),
                deposit_hangar_id=data.get("deposit_hangar_id"),
                solar_system_id=data.get("solar_system_id"),
                char_name=data.get("char_name") or "",
                facility=data.get("facility") or "",
                decryptor_type_id=data.get("decryptor_type_id"),
                success_rate=data.get("success_rate"),
            )
            QMessageBox.information(self, "完成", "已加入发明规划")
            return

        if kind == "copying":
            if not copy_row:
                QMessageBox.information(self, "提示", f"「{name}」没有拷贝活动")
                return
            dlg = CopyPlanDialog(name, max_production_limit=int(copy_row[0] or 1), parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data() or {}
            create_research_plan(
                bp_id,
                activity="copying",
                blueprint_name=name,
                runs=int(data.get("runs_per_copy") or 1),
                parallels=int(data.get("copies") or 1),
                mat_hangar_id=data.get("mat_hangar_id"),
                deposit_hangar_id=data.get("deposit_hangar_id"),
                solar_system_id=data.get("solar_system_id"),
                char_name=data.get("char_name") or "",
                facility=data.get("facility") or "",
            )
            QMessageBox.information(self, "完成", "已加入拷贝规划")
            return

        # 效率研究
        dlg = ResearchPlanDialog(name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data() or {}
        create_research_plan(
            bp_id,
            activity=str(data.get("activity") or "researching_material_efficiency"),
            blueprint_name=name,
            runs=int(data.get("target_level") or 1),
            mat_hangar_id=data.get("mat_hangar_id"),
            deposit_hangar_id=data.get("deposit_hangar_id"),
            solar_system_id=data.get("solar_system_id"),
            char_name=data.get("char_name") or "",
            facility=data.get("facility") or "",
            research_target_level=int(data.get("target_level") or 1),
        )
        QMessageBox.information(self, "完成", "已加入效率研究规划")

    def _ds(self, r, is_mfg):
        if is_mfg:
            b = r.get("breakdown", {})
            st = r.get("status", "")
            if st:
                tips = {
                    "no_blueprint": "此物品没有制造蓝图",
                    "no_price": "查不到价格数据，请在主界面更新价格",
                    "no_materials": "蓝图无材料数据",
                    "no_depth": "市场没有买单",
                }
                return f"{tips.get(st, st)}"
            c = r.get("cost_per_unit", 0) or 0
            rev = r.get("revenue_per_unit", 0) or 0
            prof = r.get("profit_per_run", 0) or 0
            hr = r.get("hours_per_run", 0) or 1
            mats = r.get("materials", []) or []
            mat_lines = "\n".join(
                f"  {m['name']} x{m['qty']:,} @ {m['unit_price']:,.2f} = {m['subtotal']:,.0f}" for m in mats
            )
            broker_relist_fee = b.get("broker_rate", 0) * rev / 100 * (1 - b.get("relist_discount", 50) / 100)
            return (
                f"每批利润核算\n"
                f"{'─' * 24}\n"
                f"材料明细:\n{mat_lines}\n"
                f"材料合计: {sum(m['subtotal'] for m in mats):,.0f} ISK\n\n"
                f"成本/个: {c:,.2f} ISK\n"
                f"收入/个: {rev:,.2f} ISK\n"
                f"单批利润: {prof:,.2f} ISK\n"
                f"利润率: {r.get('margin_pct', 0):.2f}%\n"
                f"制造时间: {hr:.2f}h\n"
                f"产能: {24 / hr:.2f}批/天\n\n"
                f"费用明细\n"
                f"经纪人(挂单): {b.get('broker_rate', 0) * rev / 100:.0f} ISK  ← {b.get('broker_rate', 0):.3f}%\n"
                f"经纪人(改单): {broker_relist_fee:.0f} ISK"
                f"  ← 改单折扣{b.get('relist_discount', 50):.0f}%\n"
                f"销售税: {b.get('sales_tax_rate', 0) * rev / 100:.0f} ISK  ← {b.get('sales_tax_rate', 0):.2f}%\n"
                f"{'─' * 24}\n"
                f"收益等级: {r.get('_tag', '?')}\n"
                f"日利润: {r.get('mdp', 0):,.0f} ISK/天"
            )
        st = r.get("status", "")
        if st:
            return f"状态: {st}"
        tag = r.get("_tag", "?") or "?"
        bc = r.get("buy_cost", 0) or 0
        sr = r.get("sell_revenue", 0) or 0
        gp = r.get("gross_profit", 0) or 0
        mp = r.get("margin_pct", 0) or 0
        pm = r.get("profit_per_m3", 0) or 0
        return (
            f"单件贸易核算\n"
            f"{'─' * 24}\n"
            f"买入: {bc:,.2f} ISK\n"
            f"  (含挂单经纪人费 + 改单费)\n"
            f"卖出: {sr:,.2f} ISK\n"
            f"  (扣挂单经纪人费 + 改单费 + 销售税)\n"
            f"毛利: {gp:,.2f} ISK\n"
            f"利润率: {mp:.2f}%\n"
            f"每方利率: {pm:.2f} ISK/m³\n"
            f"{'─' * 24}\n"
            f"收益等级: {tag}\n"
            f"日利润: 查看收益列(×市场深度)"
        )

"""
可制造物品浏览窗口 — 非模态弹窗
"""

import json
import os

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
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
from core.cache import TtlLRUCache
from core.container import get_container
from core.paths import data_dir
from services.terminology import term
from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog
from ui_pyside6.models.all_items_models import AModel, Proxy
from ui_pyside6.views.compare import CompareDialog
from ui_pyside6.views.score_dialogs import MfgDlg, ScoreW
from ui_pyside6.workers.all_items_workers import JITA_RID, ItemsW, SearchItemsW

_cache = TtlLRUCache(max_size=5000, ttl_seconds=1800)

DASH = chr(8212)

BCOLS = [
    ("图标", 36, "i"),
    ("中文名", 160, "z"),
    ("English", 180, "e"),
    ("买价", 100, "bp"),
    ("卖价", 100, "sp"),
    ("均价", 85, "ap"),
    ("体积", 70, "v"),
]

MCOLS = [
    ("成本", 105, "mc"),
    ("收入", 105, "mr"),
    ("产能/天", 65, "mh"),
    ("日利润", 100, "mdp"),
    ("状态", 110, "ms"),
    ("收益", 75, "_tag"),
    ("利润率%", 70, "mm"),
]

MFG_CATEGORIES = [
    term.market_category("all_manufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
]


class MfgTreeW(QThread):
    """加载可制造物品市场分类树"""

    done = Signal(list)

    def run(self):
        self.done.emit(get_container().blueprint_repo.get_manufacturable_market_tree())


class ManufacturableItemsDialog(QDialog):
    """可制造物品对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("可制造物品")
        self.resize(1100, 680)
        self.setMinimumSize(800, 400)
        self._data = []
        self._filt = []
        self._mfg = {"hub": "Jita", "char": "main", "tax": 0}
        self._wp = None
        self._sw = None
        self._load_settings()
        self._build_ui()
        # 搜索防抖
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        # 树节点点击防抖
        self._tree_debounce = QTimer()
        self._tree_debounce.setSingleShot(True)
        self._tree_debounce.timeout.connect(self._on_tree_delayed)
        self._tree_item = None
        self._tw = MfgTreeW(self)
        self._tw.done.connect(self._ot)
        self._tw.start()
        self._iw = None
        self._st.setText("请选择分类或搜索物品")
        theme.add_theme_listener(self._on_theme_changed)

    def closeEvent(self, ev):
        for t in (self._tw, self._iw, self._wp, self._sw):
            if t is None:
                continue
            if t.isRunning():
                t.requestInterruption()
                t.wait(300)
        super().closeEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._refresh_styles()

    def _export_data(self):
        from ui_pyside6.views.export_helper import export_to_csv, export_to_excel, get_save_filename

        if self._md.rowCount() == 0:
            self._st.setText("没有数据可导出")
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
            self._st.setText(f"已导出 {len(rows)} 行")
        except Exception as e:
            self._st.setText(f"导出失败: {e}")

    def _on_theme_changed(self):
        self._refresh_styles()

    def _refresh_styles(self):
        """全局主题 + 紧凑布局覆盖（字体 11px、精简间距）"""
        compact = """
            QDialog, QDialog * { font-size: 11px; }
            QLineEdit { border-radius: 2px; padding: 2px 4px; }
            QComboBox { border-radius: 2px; padding: 2px 4px; }
            QComboBox::drop-down { border: none; width: 16px; }
            QTableView { border-radius: 0px; }
            QHeaderView::section { padding: 2px 4px; }
            QTreeWidget { border-radius: 0px; }
            QTreeWidget::item { padding: 2px 4px; }
            QPushButton { border-radius: 2px; padding: 0 6px; }
        """
        self.setStyleSheet(theme.get_stylesheet() + compact)
        self._st.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:11px;")

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)

        def _bt(t, cb, w=70):
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.setFixedWidth(w)
            b.clicked.connect(cb)
            return b

        bx = QHBoxLayout()
        bx.setContentsMargins(2, 0, 2, 0)
        bx.setSpacing(4)
        bx.addStretch()
        self._score_btn = _bt("刷新计算", self._on_mfg)
        bx.addWidget(self._score_btn)
        b_sett = _bt("设置", self._smfg, 50)
        bx.addWidget(b_sett)
        b_comp = _bt("批量对比", self._on_compare, 70)
        bx.addWidget(b_comp)
        b_exp = _bt("导出", self._export_data, 50)
        bx.addWidget(b_exp)
        self._pin_btn = _bt("钉", self._on_pin_toggled, 35)
        bx.addWidget(self._pin_btn)
        bx.addStretch()
        lay.addLayout(bx)

        fx = QHBoxLayout()
        fx.setContentsMargins(2, 0, 2, 0)
        fx.setSpacing(2)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索物品名称/ID...")
        self._search_input.setFixedHeight(22)
        self._search_input.textChanged.connect(self._on_search_text)
        fx.addWidget(self._search_input)
        fx.addWidget(QLabel("类别:"))
        self._cat = QComboBox()
        self._cat.addItems(MFG_CATEGORIES)
        self._cat.currentIndexChanged.connect(self._apply)
        fx.addWidget(self._cat)
        self._st = QLabel("就绪")
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
        """树节点点击 — 防抖后加载"""
        self._tree_item = item
        self._tree_debounce.start(200)

    def _on_tree_delayed(self):
        """树节点点击防抖回调 — 加载该分类下所有物品"""
        item = self._tree_item
        if not item:
            return
        ids = set()

        def c(n):
            mid = n.data(0, Qt.ItemDataRole.UserRole)
            if mid:
                ids.add(mid)
            for i in range(n.childCount()):
                c(n.child(i))

        c(item)
        if not ids:
            return

        self._search_input.clear()
        self._data = []

        # 断开旧 ItemsW 信号，避免遗留回调覆盖数据
        if hasattr(self, "_iw") and self._iw is not None:
            try:
                self._iw.done.disconnect()
            except (TypeError, RuntimeError):
                pass
            if self._iw.isRunning():
                self._iw.requestInterruption()
                self._iw.wait(300)

        iw = ItemsW(list(ids), rid=JITA_RID, parent=self)
        iw.done.connect(self._od)
        iw.start()
        self._iw = iw

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
        if data and len(data) > 0:
            blueprint_repo = get_container().blueprint_repo
            if cat == 0:
                bp_ids = set(blueprint_repo.get_all_product_ids("manufacturing"))
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 1:
                bp_ids = blueprint_repo.get_t1_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 2:
                bp_ids = blueprint_repo.get_t2_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 3:
                bp_ids = blueprint_repo.get_faction_manufacturable_product_ids()
                data = [r for r in data if r["id"] in bp_ids]
            elif cat == 4:
                bp_ids = set(blueprint_repo.get_all_product_ids("reaction"))
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
            except Exception:
                pass

    def _save_settings(self):
        p = os.path.join(data_dir(), "mfg_browser_settings.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"mfg": self._mfg}, f, ensure_ascii=False, indent=2)

    def _upd(self):
        """始终显示 BCOLS + MCOLS 所有列，数据先显示再异步算分"""
        cols = list(BCOLS)
        cols[3] = (f"买价（{self._mfg['hub']}）", 100, "bp")
        cols[4] = (f"卖价（{self._mfg['hub']}）", 100, "sp")
        cols.extend(MCOLS)
        self._md.set_cols(cols)
        self._setw(cols)
        if self._filt:
            self._md.set_rows(self._filt)
            self._st.setText(f"共 {len(self._filt)} 条 | 计算评分中...")
            self._calc()
        else:
            self._md.set_rows([])
            self._st.setText("无数据")

    def _calc(self):
        if self._wp is not None:
            self._wp.requestInterruption()
            self._wp.requestInterruption()
            # 断开旧信号避免遗留回调触发 _cd
            try:
                self._wp.progress.disconnect()
                self._wp.done.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._wp = None
        self._pr.setVisible(True)
        self._pr.setRange(0, len(self._filt))
        self._st.setText("计算评分中...")
        self._wp = ScoreW(list(self._filt), True, self._mfg, self)
        self._wp.progress.connect(lambda c, t: self._pr.setValue(c))
        self._wp.done.connect(self._cd)
        self._wp.start()

    def _cd(self, rows):
        self._filt = rows
        self._md.set_rows(rows)
        self._pr.setVisible(False)
        self._st.setText(f"共 {len(self._filt)} 条 | 评分已计算")
        # 固定图标列宽，其余自适应
        hh = self._tv.horizontalHeader()
        for i in range(self._md.columnCount()):
            if i == 0:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(True)

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
            ev.accept()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier and ev.key() == Qt.Key.Key_A:
            self._tv.selectAll()
            self._copy_selection()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _copy_selection(self):
        sel = self._tv.selectionModel().selectedRows()
        if not sel:
            self._st.setText("没有选中行")
            return
        lines = []
        for idx in sel:
            row = self._md._rows[idx.row()]
            parts = []
            for _, _, key in self._md._cols:
                if key == "i":
                    parts.append(str(row.get("id", "")))
                else:
                    parts.append(str(row.get(key, "")))
            lines.append("\t".join(parts))
        if lines:
            QApplication.instance().clipboard().setText("\n".join(lines))
            self._st.setText(f"已复制 {len(lines)} 行")

    def _on_mfg(self):
        """刷新计算前先确认数据库有价格数据，无价格时保留缓存"""
        if not self._filt:
            return
        # 单条 SQL 确认 market_prices 是否有数据，避免 N 次 get_price 调用
        has_prices = get_container().market_repo.has_any_prices()

        if has_prices:
            # 数据库有价格 → 清评分缓存 → 用最新价格重算
            # 注意：清缓存后会惰性重建
            _cache.invalidate()
            self._st.setText("重新计算中...")
            self._calc()
        else:
            self._st.setText("暂无价格数据，请先在主界面更新价格")

    def _smfg(self):
        dlg = MfgDlg(self._mfg, self)
        if dlg.exec():
            before_hub = self._mfg.get("hub", "Jita")
            self._mfg.update(dlg.get())
            self._save_settings()
            if before_hub != self._mfg.get("hub", "Jita"):
                self._upd()

    def _on_pin_toggled(self, checked):
        if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            self._pin_btn.setText("钉")
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self._pin_btn.setText("已钉")
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

        # 始终显示评分详情（该窗口专为制造评分设计）
        k = f"{tid}|mfg|{self._mfg['hub']}|{self._mfg['char']}"
        res = _cache.get(k)
        if res:
            d = self._ds(res, True)
            a_brkd = QAction("制造核算明细", self)
            a_brkd.triggered.connect(lambda *a: QMessageBox.information(self, "制造核算明细", d))
            m.addAction(a_brkd)

        m.addSeparator()
        _ctx_name = r.get("z", "") or r.get("e", "") or str(tid)

        def _do_add_plan():
            score = {}
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
            from services import inventory_manager
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
                mat_hub=self._mfg.get("hub", "Jita"),
                sell_hub=self._mfg.get("hub", "Jita"),
                facility=data.get("fac", ""),
                solar_system_id=solar_system_id,
                mat_hangar_id=mat_hangar_id,
                metrics=metrics,
            )
            QMessageBox.information(self, "提示", f"已加入制造列表: {_ctx_name}")

        a_add = QAction("加入制造列表", self)
        a_add.triggered.connect(_do_add_plan)
        m.addAction(a_add)
        m.exec(self._tv.viewport().mapToGlobal(pos))

    def _ds(self, r, is_mfg):
        if is_mfg:
            b = r.get("breakdown", {})
            st = r.get("status", "")
            if st:
                tips = {"no_blueprint": "此物品没有制造蓝图", "no_price": "查不到价格数据", "no_mats": "蓝图无材料数据"}
                return f"状态: {tips.get(st, st)}"
            lines = [
                f"评分: {r.get('score', 0):.0f}",
                f"单批利润: {r.get('profit_per_run', 0):,.0f} ISK",
                f"利润率: {r.get('margin_pct', 0):.1f}%",
                f"每小时利润: {r.get('isk_per_hour', 0):,.0f} ISK",
                f"材料成本: {b.get('material_cost', 0):,.0f} ISK",
            ]
            run_cost = b.get("run_cost", 0)
            if run_cost:
                lines.append(f"运行成本: {run_cost:,.0f} ISK")
            install = b.get("install_fee", 0)
            if install:
                lines.append(f"安装费: {install:,.0f} ISK")
            broker = b.get("broker_fee", 0)
            if broker:
                lines.append(f"经纪人费: {broker:,.0f} ISK")
            sales_tax = b.get("sales_tax", 0)
            if sales_tax:
                lines.append(f"销售税: {sales_tax:,.0f} ISK")
            _nl = chr(10)
            return _nl.join(lines)
        return ""

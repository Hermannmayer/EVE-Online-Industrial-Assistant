"""
全物品浏览器 — 非模态弹窗
"""

import json
import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
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
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.eve_formulas import resolve_item_name
from core.paths import ICON_DIR
from services.scoring import cache_key as _ck
from services.scoring import get_cache as _cget
from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog, ProcurementDialog
from ui_pyside6.views.compare_dialog import CompareDialog
from ui_pyside6.views.score_dialogs import MfgDlg, ScoreW, TradeDlg

DASH = chr(8212)

JITA_RID = TRADE_HUB_IDS["Jita"]

_SQL = (
    "SELECT i.market_group_id,i.type_id,i.zh_name,i.en_name,i.volume,"
    "mp.buy_price,mp.sell_price,mp.buy_volume,mp.sell_volume "
    "FROM item i "
    "LEFT JOIN mkt.market_prices mp ON mp.type_id=i.type_id "
    "AND mp.region_id=? AND mp.fetch_time=(SELECT MAX(fetch_time) "
    "FROM mkt.market_prices WHERE type_id=i.type_id AND region_id=?) "
)


def _fetch(sql, rid: int, params=None):
    with get_container().db.connect("ref", "mkt") as conn:
        c = conn.cursor()
        if params:
            c.execute(sql, (rid, rid, *params))
        else:
            c.execute(sql, (rid, rid))
        r = []
        for row in c.fetchall():
            mg, tid, zh, en, vol, bp, sp, bv, sv = row
            ap = ((bp or 0) + (sp or 0)) / 2 if bp and sp else (bp or sp)
            r.append(
                {
                    "mg": mg,
                    "id": tid,
                    "z": zh or "",
                    "e": en or "",
                    "v": vol or 0,
                    "bp": bp,
                    "sp": sp,
                    "ap": ap,
                    "bv": bv or 0,
                    "sv": sv or 0,
                }
            )
        return r


CATEGORIES = ["所有类别", "无法制造获得", "蓝图制造(T1)", "发明制造(T2)", "势力蓝图制造", "反应", "行星开发"]
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
TCOLS = [("花费", 105, "tc"), ("收入", 105, "tr"), ("收益", 75, "_tag"), ("利润率%", 70, "tm"), ("每方利率", 90, "tpm")]


class MatDlg(QDialog):
    def __init__(self, tid, parent=None):
        super().__init__(parent)
        self.setWindowTitle("制造材料")
        self.setMinimumSize(460, 280)
        self.setStyleSheet(f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        with get_container().db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()
            nm = resolve_item_name(c, tid)
            lay.addWidget(
                QLabel(f"制造材料: {nm}", styleSheet=f"color:{theme.PRIMARY};font-size:13px;font-weight:bold;")
            )
            c.execute(
                """SELECT blueprint_type_id
                FROM blueprint_products
                WHERE product_type_id=? AND activity='manufacturing' ORDER BY blueprint_type_id LIMIT 1""",
                (tid,),
            )
            bp_row = c.fetchone()
            if not bp_row:
                lay.addWidget(QLabel("此物品无制造蓝图", styleSheet=f"color:{theme.ACCENT_RED};"))
                b = QPushButton("关闭")
                b.clicked.connect(self.accept)
                lay.addWidget(b)
                return
            bp_id = bp_row[0]
            c.execute(
                """SELECT bm.material_type_id,bm.quantity,i.zh_name,i.en_name,mp.sell_price
                FROM blueprint_materials bm JOIN item i ON bm.material_type_id=i.type_id
                LEFT JOIN mkt.market_prices mp ON mp.type_id=i.type_id
                AND mp.fetch_time=(SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id=i.type_id)
                WHERE bm.blueprint_type_id=? AND bm.activity='manufacturing' ORDER BY i.zh_name""",
                (bp_id,),
            )
            mats = c.fetchall()
        lst = QListWidget()
        lst.setStyleSheet(f"background:{theme.BG_SURFACE};border:1px solid {theme.BORDER};border-radius:3px;")
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
                f"总成本: {total:,.2f} ISK", styleSheet=f"color:{theme.ACCENT_GREEN};font-size:12px;font-weight:bold;"
            )
        )
        b = QPushButton("关闭")
        b.clicked.connect(self.accept)
        lay.addWidget(b)


class AModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._cols = BCOLS[:]

    def set_rows(self, r):
        self.beginResetModel()
        self._rows = r
        self.endResetModel()

    def set_cols(self, c):
        self.beginResetModel()
        self._cols = c
        self.endResetModel()

    def rowCount(self, p=QModelIndex()):
        return len(self._rows)

    def columnCount(self, p=QModelIndex()):
        return len(self._cols)

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid():
            return None
        r = self._rows[idx.row()]
        _, _, k = self._cols[idx.column()]
        v = r.get(k)
        if role == Qt.ItemDataRole.DisplayRole:
            if k in ("bp", "sp", "ap", "mc", "mr", "tc", "tr"):
                return f"{v:,.2f}" if isinstance(v, (int, float)) and v is not None else DASH
            if k in ("_tag",):
                return v or DASH
            if k in ("mm", "tm", "tpm", "mdp", "_tag_sort"):
                return f"{float(v):,.1f}" if v is not None else DASH
            if k == "mh":
                return f"{v:.2f}" if isinstance(v, (int, float)) and v else DASH
            if k == "ms":
                s = {"no_blueprint": "无蓝图", "no_price": "无价格", "no_materials": "无材料", "no_depth": "市场无买单"}
                return s.get(v, v) or DASH
            if k in ("z", "e"):
                return v or ""
            if k == "v":
                return f"{v:,.2f}" if v else DASH
            return str(v) if v is not None else ""
        if role == Qt.ItemDataRole.DecorationRole and k == "i":
            tid = r.get("id")
            if tid:
                p = os.path.join(ICON_DIR, f"{tid}.png")
                if os.path.exists(p):
                    px = QPixmap(p)
                    if not px.isNull():
                        return px.scaled(
                            30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if k not in ("i", "z", "e", "ms"):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole:
            if k == "_tag":
                tag = str(v or "")
                if tag.endswith("S"):
                    return QColor(theme.ACCENT_GREEN)
                if tag.endswith("A"):
                    return QColor(theme.PRIMARY)
                if tag.endswith("B"):
                    return QColor(theme.ACCENT_YELLOW)
                if tag.endswith("C"):
                    return QColor(theme.ACCENT_ORANGE)
                if tag.endswith("D") and not tag.startswith("✗"):
                    return QColor(theme.ACCENT_RED)
            if k in ("mm", "tm"):
                vf = float(r.get(k, 0) or 0)
                if vf > 0:
                    return QColor(theme.ACCENT_GREEN)
                elif vf < 0:
                    return QColor(theme.ACCENT_RED)
        if role == Qt.ItemDataRole.UserRole:
            return r
        return None

    def headerData(self, s, o, r=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and r == Qt.ItemDataRole.DisplayRole and s < len(self._cols):
            return self._cols[s][0]
        return None


class Proxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        lv = str(left.data() or "")
        rv = str(right.data() or "")
        # 收益列按等级排序: S > A > B > C > D > ✗
        _rank = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "✗": 0}
        lr = next((_rank[k] for k in _rank if k in lv), -1)
        rr = next((_rank[k] for k in _rank if k in rv), -1)
        if lr >= 0 and rr >= 0:
            return lr < rr
        try:
            ln = float(lv.replace(",", "").replace(DASH, "0"))
            rn = float(rv.replace(",", "").replace(DASH, "0"))
            return ln < rn
        except Exception:
            return lv < rv


class TreeW(QThread):
    done = Signal(list)

    def run(self):
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            c.execute("SELECT market_group_id,parent_group_id,zh_name FROM market_tree ORDER BY zh_name")
            r = [{"id": i, "p": p, "n": z or f"G{i}"} for i, p, z in c.fetchall()]
            self.done.emit(r)


class ItemsW(QThread):
    done = Signal(list)

    def __init__(self, ids=None, rid: int = 0, parent=None):
        super().__init__(parent)
        self._ids = ids
        self._rid = rid

    def run(self):
        if self._ids:
            ph = ",".join("?" * len(self._ids))
            r = _fetch(_SQL + f"WHERE i.market_group_id IN ({ph}) ORDER BY i.zh_name LIMIT 2000", self._rid, self._ids)
        else:
            r = _fetch(_SQL + "ORDER BY i.zh_name LIMIT 2000", self._rid)
        self.done.emit(r)


class SearchItemsW(QThread):
    """按名称/ID 搜索物品"""

    done = Signal(list)

    def __init__(self, query: str, rid: int, parent=None):
        super().__init__(parent)
        self._query = query
        self._rid = rid

    def run(self):
        q = self._query.strip()
        if not q:
            self.done.emit([])
            return
        with get_container().db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()
            rid = self._rid
            like = f"%{q}%"
            if q.isdigit():
                _sql_where = _SQL + "WHERE (i.type_id=? OR i.zh_name LIKE ? OR i.en_name LIKE ?)"
                _sql_where += " ORDER BY i.zh_name LIMIT 500"
                c.execute(_sql_where, (rid, rid, int(q), like, like))
            else:
                _sql_where = _SQL + "WHERE (i.zh_name LIKE ? OR i.en_name LIKE ?)"
                _sql_where += " ORDER BY CASE WHEN i.en_name LIKE ? THEN 0"
                _sql_where += " WHEN i.zh_name LIKE ? THEN 1 ELSE 2 END, i.zh_name LIMIT 500"
                c.execute(_sql_where, (rid, rid, like, like, f"{q}%", f"{q}%"))
            r = []
            for row in c.fetchall():
                mg, tid, zh, en, vol, bp, sp, bv, sv = row
                ap = ((bp or 0) + (sp or 0)) / 2 if bp and sp else (bp or sp)
                r.append(
                    {
                        "mg": mg,
                        "id": tid,
                        "z": zh or "",
                        "e": en or "",
                        "v": vol or 0,
                        "bp": bp,
                        "sp": sp,
                        "ap": ap,
                        "bv": bv or 0,
                        "sv": sv or 0,
                    }
                )
            self.done.emit(r)


class AllItemsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__()  # 无 parent，完全独立窗口
        self.setWindowTitle("全物品查询")
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
        self._data = []
        self._filt = []
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
                t.quit()
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
                elif isinstance(v, (int, float)):
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
                f"font-size:11px;min-width:60px;}}"
                f"QPushButton:hover{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            b.setStyleSheet(ss)
        self._pin.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:11px;")
        self._search_input.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:11px;"
        )
        self._cat.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:11px;"
        )
        self._st.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:11px;")

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)

        def _bt(t, cb, w=60):
            b = QPushButton(t)
            ss = (
                f"QPushButton{{background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};"
                f"border:1px solid {theme.BORDER};border-radius:2px;padding:2px 6px;"
                f"font-size:11px;min-width:{w}px;}}"
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
        self._pin.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:11px;")
        self._pin.toggled.connect(self._on_pin_toggled)
        bx.addWidget(self._pin)
        lay.addWidget(tb)
        fb = QWidget()
        fb.setStyleSheet(f"background:{theme.BG_DARK};border-bottom:1px solid {theme.BORDER};")
        self._filter_bar = fb
        fx = QHBoxLayout(fb)
        fx.setContentsMargins(4, 1, 4, 1)
        fx.setSpacing(3)
        fx.addWidget(QLabel("搜索:", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:11px;"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("名称/ID...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:11px;"
        )
        self._search_input.textChanged.connect(self._on_search_text)
        fx.addWidget(self._search_input)
        fx.addWidget(QLabel("类别:", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:11px;"))
        self._cat = QComboBox()
        self._cat.addItems(CATEGORIES)
        self._cat.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;"
            f"padding:1px 4px;font-size:11px;"
        )
        self._cat.currentIndexChanged.connect(self._apply)
        fx.addWidget(self._cat)
        self._st = QLabel("就绪", styleSheet=f"color:{theme.TEXT_SECONDARY};font-size:11px;")
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
            self._sw.quit()
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
        if data and cat > 0:
            with get_container().db.connect("ref", "bp") as conn:
                c = conn.cursor()
                if cat == 1:  # 无法制造获得 — 没有任何蓝图
                    c.execute("SELECT DISTINCT product_type_id FROM blueprint_products")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] not in bp_ids]
                elif cat == 2:  # 蓝图制造 T1 — 有制造蓝图，且该蓝图非发明产物
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        WHERE bp.activity='manufacturing'
                        AND bp.blueprint_type_id NOT IN (
                            SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                        )""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 3:  # 发明制造 T2 — 有制造蓝图，且该蓝图由发明产出
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        WHERE bp.activity='manufacturing'
                        AND bp.blueprint_type_id IN (
                            SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                        )""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 4:  # 势力蓝图制造
                    c.execute("""SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                        JOIN item i ON bp.product_type_id=i.type_id
                        WHERE bp.activity='manufacturing' AND (
                            i.en_name LIKE '%Navy%' OR i.en_name LIKE '%Faction%'
                            OR i.en_name LIKE '%Imperial%' OR i.en_name LIKE '%Republic%'
                            OR i.en_name LIKE '%Federation%' OR i.en_name LIKE '%State%')""")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 5:  # 反应
                    c.execute("SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity='reaction'")
                    bp_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in bp_ids]
                elif cat == 6:  # 行星开发
                    c.execute("""SELECT DISTINCT i.type_id FROM item i
                        JOIN market_tree mt ON i.market_group_id = mt.market_group_id
                        WHERE mt.parent_group_id IN (
                            SELECT market_group_id FROM market_tree
                            WHERE zh_name LIKE '%行星%' OR en_name LIKE '%Planet%'
                        ) OR mt.parent_group_id IN (
                            WITH RECURSIVE s AS(
                            SELECT market_group_id FROM market_tree
                            WHERE zh_name LIKE '%行星%'
                            OR en_name LIKE '%Planet%'
                            OR en_name LIKE '%Command Center%'
                            UNION ALL
                            SELECT m.market_group_id FROM market_tree m
                            JOIN s ON m.parent_group_id=s.market_group_id)
                            SELECT market_group_id FROM s)""")
                    pi_ids = {r[0] for r in c.fetchall()}
                    data = [r for r in data if r["id"] in pi_ids]
        self._filt = data
        self._upd()

    def _load_settings(self):
        import os

        from core.paths import data_dir

        p = os.path.join(data_dir(), "score_settings.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
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
            cols[4] = (f"买价（{self._mfg['hub']}）", 100, "bp")
            cols[5] = (f"卖价（{self._mfg['hub']}）", 100, "sp")
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
            cols[4] = (f"买价（{self._trade['bh']}{ptn.get(self._trade['bs'], '')}）", 100, "bp")
            cols[5] = (f"卖价（{self._trade['sh']}{ptn.get(self._trade['ss'], '')}）", 100, "sp")
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
            k = _ck(tid, "mfg", self._mfg["hub"], self._mfg["char"])
            res = _cget(k)
            if res:
                d = self._ds(res, True)
                a3 = QAction("制造核算明细", self)
                a3.triggered.connect(lambda *a: QMessageBox.information(self, "制造核算明细", d))
                m.addAction(a3)
        if self._show_t:
            k = _ck(tid, "trade", self._trade["bh"] + self._trade["sh"], self._trade["char"])
            res = _cget(k)
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
                k = _ck(tid, "mfg", self._mfg["hub"], self._mfg["char"])
                cached = _cget(k)
                if cached:
                    score = cached
            from datetime import datetime, timezone

            dlg = AddPlanDialog(_ctx_name, score, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            conn = get_container().db.direct_connect("user")
            try:
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
                        self._mfg["hub"],
                        self._mfg["hub"],
                        data["fac"],
                        data["char"],
                        score.get("profit_per_run", 0),
                        score.get("margin_pct", 0),
                        score.get("score", 0),
                        iskph,
                        mat_cost,
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            QMessageBox.information(self, "提示", f"已加入制造列表: {_ctx_name}")

        a5 = QAction("加入制造列表", self)
        a5.triggered.connect(_do_add_plan)
        m.addAction(a5)

        def _do_add_procurement():
            dlg = ProcurementDialog(tid, _ctx_name, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute(
                    "INSERT INTO procurement_items (type_id, item_name, quantity, hub, priority, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (data["type_id"], data["name"], data["quantity"], data["hub"], data["priority"], data["notes"]),
                )
                conn.commit()
            finally:
                conn.close()
            QMessageBox.information(self, "提示", f"已加入代采购: {_ctx_name}")

        a6 = QAction("加入代采购", self)
        a6.triggered.connect(_do_add_procurement)
        m.addAction(a6)
        m.exec(self._tv.viewport().mapToGlobal(pos))

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

"""
全物品浏览器 — 非模态弹窗
"""
import sqlite3, os, json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem,
    QTableView, QHeaderView, QLabel, QSplitter, QPushButton,
    QCheckBox, QComboBox, QFormLayout, QDialogButtonBox, QDoubleSpinBox,
    QAbstractItemView, QMenu, QMessageBox, QApplication,
    QListWidget, QListWidgetItem, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSize
from PySide6.QtGui import QAction, QPixmap, QColor, QIcon
from core.paths import DB_PATH, ICON_DIR
from ui_pyside6.theme import BG_DARK, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, BORDER, ACCENT_GREEN, ACCENT_RED
from services.scoring import calc_manufacturing_score, calc_trade_score
from services.scoring_cache import cache_key as _ck, get as _cget, set as _cset
from ui_pyside6.views.char_settings_view import get_character_list, get_character

DASH = chr(8212)
REGIONS = ["Jita", "Amarr", "Dodixie", "Rens"]
CATEGORIES = ["所有类别", "无法制造获得", "蓝图制造(T1)", "发明制造(T2)", "势力蓝图制造", "反应", "行星开发"]
BCOLS = [("图标",36,"i"),("ID",60,"id"),("中文名",160,"z"),("English",180,"e"),
         ("买价",100,"bp"),("卖价",100,"sp"),("均价",85,"ap"),("体积",70,"v")]
MCOLS = [("成本",105,"mc"),("收入",105,"mr"),("产能/天",65,"mh"),("日利润",100,"mdp"),
         ("状态",110,"ms"),("评分",65,"mfs"),("利润率%",70,"mm")]
TCOLS = [("花费",105,"tc"),("收入",105,"tr"),("评分",65,"ts"),("利润率%",70,"tm"),("每方利率",90,"tpm")]


class MfgDlg(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("制造评分设置")
        self.setMinimumWidth(260)
        self.setStyleSheet(f"background:{BG_DARK};color:{TEXT_PRIMARY};")
        ss = f"background:{BG_DARK};color:{TEXT_PRIMARY};border:1px solid {BORDER};border-radius:2px;padding:2px 6px;"
        l = QFormLayout(self); l.setSpacing(4)
        self.h = QComboBox(); self.h.addItems(REGIONS); self.h.setStyleSheet(ss); l.addRow("中心:", self.h)
        self.c = QComboBox(); self.c.setStyleSheet(ss)
        cs = get_character_list(); self.c.addItems(cs if cs else ["main"]); l.addRow("人物:", self.c)
        self.t = QDoubleSpinBox(); self.t.setRange(0,100); self.t.setSuffix(" %"); self.t.setStyleSheet(ss); l.addRow("设施税:", self.t)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept); b.rejected.connect(self.reject); l.addRow(b)
    def get(self):
        c = self.c.currentText()
        return {"hub":self.h.currentText(),"char":c if c in get_character_list() else "main","tax":self.t.value()}


class TradeDlg(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("贸易评分设置")
        self.setMinimumWidth(260)
        self.setStyleSheet(f"background:{BG_DARK};color:{TEXT_PRIMARY};")
        ss = f"background:{BG_DARK};color:{TEXT_PRIMARY};border:1px solid {BORDER};border-radius:2px;padding:2px 6px;"
        l = QFormLayout(self); l.setSpacing(4)
        self.bh = QComboBox(); self.bh.addItems(REGIONS); self.bh.setStyleSheet(ss); l.addRow("买入:", self.bh)
        self.sh = QComboBox(); self.sh.addItems(REGIONS); self.sh.setStyleSheet(ss); l.addRow("卖出:", self.sh)
        self.bs = QComboBox(); self.bs.addItems(["卖单","买单"]); self.bs.setStyleSheet(ss); l.addRow("买价:", self.bs)
        self.ss = QComboBox(); self.ss.addItems(["卖单","买单"]); self.ss.setStyleSheet(ss); l.addRow("卖价:", self.ss)
        self.c = QComboBox(); self.c.setStyleSheet(ss)
        cs = get_character_list(); self.c.addItems(cs if cs else ["main"]); l.addRow("人物:", self.c)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept); b.rejected.connect(self.reject); l.addRow(b)
    def get(self):
        c = self.c.currentText()
        return {"bh":self.bh.currentText(),"sh":self.sh.currentText(),
                "bs":"sell" if self.bs.currentIndex()==0 else "buy",
                "ss":"sell" if self.ss.currentIndex()==0 else "buy",
                "char":c if c in get_character_list() else "main"}


class MatDlg(QDialog):
    def __init__(self, tid, parent=None):
        super().__init__(parent)
        self.setWindowTitle("制造材料"); self.setMinimumSize(460,280)
        self.setStyleSheet(f"background:{BG_DARK};color:{TEXT_PRIMARY};")
        l = QVBoxLayout(self); l.setContentsMargins(10,10,10,10)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT zh_name,en_name FROM item WHERE type_id=?", (tid,))
        r = c.fetchone(); nm = (r[0]or r[1]or str(tid)) if r else str(tid)
        l.addWidget(QLabel(f"制造材料: {nm}", styleSheet=f"color:{PRIMARY};font-size:13px;font-weight:bold;"))
        c.execute("""SELECT bm.material_type_id,bm.quantity,i.zh_name,i.en_name,mp.sell_price
            FROM blueprint_materials bm JOIN item i ON bm.material_type_id=i.type_id
            LEFT JOIN market_prices mp ON mp.type_id=i.type_id AND mp.fetch_time=(SELECT MAX(fetch_time) FROM market_prices WHERE type_id=i.type_id)
            WHERE bm.blueprint_type_id IN (SELECT blueprint_type_id FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing')
            AND bm.activity='manufacturing' ORDER BY i.zh_name""", (tid,))
        mats = c.fetchall(); conn.close()
        lst = QListWidget()
        lst.setStyleSheet(f"background:{BG_SURFACE};border:1px solid {BORDER};border-radius:3px;")
        total = 0.0
        for mid,qty,zh,en,sp in mats:
            n = zh or en or str(mid); p = sp or 0; sub = p*qty; total += sub
            ip = os.path.join(ICON_DIR,f"{mid}.png"); ic = QIcon(ip) if os.path.exists(ip) else QIcon()
            it = QListWidgetItem(ic, f"  {n} x{qty:,} @ {p:,.2f} = {sub:,.2f}")
            it.setSizeHint(QSize(0,32)); lst.addItem(it)
        l.addWidget(lst)
        l.addWidget(QLabel(f"总成本: {total:,.2f} ISK", styleSheet=f"color:{ACCENT_GREEN};font-size:12px;font-weight:bold;"))
        b = QPushButton("关闭"); b.clicked.connect(self.accept); l.addWidget(b)


class AModel(QAbstractTableModel):
    def __init__(self): super().__init__(); self._rows=[]; self._cols=BCOLS[:]
    def set_rows(self,r): self.beginResetModel();self._rows=r;self.endResetModel()
    def set_cols(self,c): self.beginResetModel();self._cols=c;self.endResetModel()
    def rowCount(self,p=QModelIndex()): return len(self._rows)
    def columnCount(self,p=QModelIndex()): return len(self._cols)
    def data(self,idx,role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid(): return None
        r=self._rows[idx.row()];_,_,k=self._cols[idx.column()];v=r.get(k)
        if role==Qt.ItemDataRole.DisplayRole:
            if k in ("bp","sp","ap","mc","mr","tc","tr"):
                return f"{v:,.2f}" if isinstance(v,(int,float)) and v is not None else DASH
            if k in ("mfs","ts"):
                return f"{float(v):.0f}" if v and float(v)>0 else DASH
            if k in ("mm","tm","tpm","mdp"):
                return f"{float(v):,.1f}" if v is not None else DASH
            if k=="mh": return f"{v:.2f}" if isinstance(v,(int,float)) and v else DASH
            if k=="ms":
                s={"no_blueprint":"无蓝图","no_price":"无价格","no_materials":"无材料"}
                return s.get(v,v) or DASH
            if k in ("z","e"): return v or ""
            if k=="v": return f"{v:,.2f}" if v else DASH
            return str(v) if v is not None else ""
        if role==Qt.ItemDataRole.DecorationRole and k=="i":
            tid=r.get("id")
            if tid:
                p=os.path.join(ICON_DIR,f"{tid}.png")
                if os.path.exists(p):
                    px=QPixmap(p)
                    if not px.isNull(): return px.scaled(30,30,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        if role==Qt.ItemDataRole.TextAlignmentRole:
            if k not in ("i","z","e","ms"): return Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter
        if role==Qt.ItemDataRole.ForegroundRole:
            if k=="mfs":
                vf=float(r.get(k,0)or 0)
                if vf>=80: return QColor(ACCENT_GREEN)
                elif vf>=50: return QColor("#61afef")
                elif vf>=20: return QColor("#e5c07b")
                elif vf>0: return QColor(ACCENT_RED)
            if k=="ts":
                vf=float(r.get(k,0)or 0)
                if vf>=60: return QColor(ACCENT_GREEN)
                elif vf>=30: return QColor("#61afef")
                elif vf>0: return QColor("#e5c07b")
            if k in ("mm","tm"):
                vf=float(r.get(k,0)or 0)
                if vf>0: return QColor(ACCENT_GREEN)
                elif vf<0: return QColor(ACCENT_RED)
        if role==Qt.ItemDataRole.UserRole: return r
        return None
    def headerData(self,s,o,r=Qt.ItemDataRole.DisplayRole):
        if o==Qt.Orientation.Horizontal and r==Qt.ItemDataRole.DisplayRole and s<len(self._cols): return self._cols[s][0]
        return None


class Proxy(QSortFilterProxyModel):
    def lessThan(self,l,r):
        try:
            ln=float(str(l.data()or"0").replace(",","").replace(DASH,"0"))
            rn=float(str(r.data()or"0").replace(",","").replace(DASH,"0"))
            return ln<rn
        except: return str(l.data()or"")<str(r.data()or"")


_SQL = "SELECT i.market_group_id,i.type_id,i.zh_name,i.en_name,i.volume,mp.buy_price,mp.sell_price,mp.buy_volume,mp.sell_volume FROM item i LEFT JOIN market_prices mp ON mp.type_id=i.type_id AND mp.fetch_time=(SELECT MAX(fetch_time) FROM market_prices WHERE type_id=i.type_id) "


def _fetch(sql,params=None):
    conn=sqlite3.connect(DB_PATH);c=conn.cursor()
    if params: c.execute(sql,params)
    else: c.execute(sql)
    r=[]
    for row in c.fetchall():
        mg,tid,zh,en,vol,bp,sp,bv,sv=row
        ap=((bp or 0)+(sp or 0))/2 if bp and sp else (bp or sp)
        r.append({"mg":mg,"id":tid,"z":zh or "","e":en or "","v":vol or 0,"bp":bp,"sp":sp,"ap":ap,"bv":bv or 0,"sv":sv or 0})
    conn.close(); return r


class TreeW(QThread):
    done=Signal(list)
    def run(self):
        conn=sqlite3.connect(DB_PATH);c=conn.cursor()
        c.execute("SELECT market_group_id,parent_group_id,zh_name FROM market_tree ORDER BY zh_name")
        r=[{"id":i,"p":p,"n":z or f"G{i}"} for i,p,z in c.fetchall()]; conn.close(); self.done.emit(r)


class ItemsW(QThread):
    done=Signal(list)
    def __init__(self, ids=None, parent=None): super().__init__(parent); self._ids=ids
    def run(self):
        if self._ids:
            ph=",".join("?"*len(self._ids))
            r=_fetch(_SQL+f"WHERE i.market_group_id IN ({ph}) ORDER BY i.zh_name LIMIT 2000",self._ids)
        else: r=_fetch(_SQL+"ORDER BY i.zh_name LIMIT 2000")
        self.done.emit(r)


class ScoreW(QThread):
    progress=Signal(int,int);done=Signal(list)
    def __init__(self,items,is_mfg,cfg,parent=None): super().__init__(parent);self._items=items;self._mfg=is_mfg;self._cfg=cfg
    def run(self):
        char=get_character(self._cfg.get("char","")) if self._cfg.get("char") else None
        total=len(self._items)
        for i,row in enumerate(self._items):
            tid=row["id"]
            if self._mfg:
                k=_ck(tid,"mfg",self._cfg["hub"],self._cfg["char"]);r=_cget(k)
                if not r:
                    r=calc_manufacturing_score(tid,char or {},self._cfg["hub"],self._cfg["hub"],self._cfg.get("tax",0))
                    _cset(k,r)
                h=r.get("hours_per_run",1) or 1
                runs_per_day = 24/h
                row.update({"mc":r.get("cost_per_unit"),"mr":r.get("revenue_per_unit"),
                    "mh":runs_per_day,"ms":r.get("status",""),"mfs":r.get("score"),
                    "mm":r.get("margin_pct"),"mdp":(r.get("profit_per_run",0) or 0)*runs_per_day})
            else:
                k=_ck(tid,"trade",self._cfg["bh"]+self._cfg["sh"],self._cfg["char"]);r=_cget(k)
                if not r:
                    r=calc_trade_score(tid,self._cfg["bh"],self._cfg["sh"],self._cfg["bs"],self._cfg["ss"],char or {})
                    _cset(k,r)
                row.update({"tc":r.get("buy_cost"),"tr":r.get("sell_revenue"),"ts":r.get("score"),"tm":r.get("margin_pct"),"tpm":r.get("profit_per_m3")})
            if i%50==0: self.progress.emit(i,total)
        self.done.emit(self._items)


class AllItemsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle("全物品查询");self.resize(1100,680);self.setMinimumSize(800,400)
        self._data=[];self._filt=[];self._bp_cached=None
        self._mfg={"hub":"Jita","char":"main","tax":0}
        self._trade={"bh":"Amarr","sh":"Jita","bs":"sell","ss":"sell","char":"main"}
        self._show_m=False;self._show_t=False;self._wp=None;self._tw=None;self._iw=None
        self._load_settings()
        self._build_ui()
        self._tw = TreeW(self); self._tw.done.connect(self._ot); self._tw.start()
        self._iw = ItemsW(parent=self); self._iw.done.connect(self._od); self._iw.start()

    def closeEvent(self, ev):
        for t in (self._tw, self._iw, self._wp):
            if t and t.isRunning():
                t.quit(); t.wait(2000)
        super().closeEvent(ev)

    def _build_ui(self):
        l=QVBoxLayout(self);l.setContentsMargins(2,2,2,2);l.setSpacing(1)
        def _bt(t,cb,w=60):
            b=QPushButton(t);b.setStyleSheet(f"QPushButton{{background:{BG_DARK};color:{TEXT_PRIMARY};border:1px solid {BORDER};border-radius:2px;padding:2px 6px;font-size:11px;min-width:{w}px;}}QPushButton:hover{{background:{PRIMARY};color:white;}}")
            b.clicked.connect(cb);return b
        tb=QWidget();tb.setStyleSheet(f"background:{BG_SURFACE};border-bottom:1px solid {BORDER};")
        bx=QHBoxLayout(tb);bx.setContentsMargins(4,2,4,2);bx.setSpacing(3)
        bx.addWidget(QLabel("来源:",styleSheet=f"color:{TEXT_SECONDARY};font-size:11px;"))
        self._hub=QComboBox();self._hub.addItems(REGIONS)
        self._hub.setStyleSheet(f"background:{BG_DARK};color:{TEXT_PRIMARY};border:1px solid {BORDER};border-radius:2px;padding:1px 4px;font-size:11px;")
        bx.addWidget(self._hub)
        bx.addWidget(_bt("制造评分",self._on_mfg));bx.addWidget(_bt("设置",self._smfg,30))
        bx.addWidget(_bt("贸易评分",self._on_trade));bx.addWidget(_bt("设置",self._strade,30))
        bx.addStretch()
        self._pin=QCheckBox("置顶")
        self._pin.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:11px;")
        self._pin.toggled.connect(lambda c:(self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,c),self.show()))
        bx.addWidget(self._pin);l.addWidget(tb)
        fb=QWidget();fb.setStyleSheet(f"background:{BG_DARK};border-bottom:1px solid {BORDER};")
        fx=QHBoxLayout(fb);fx.setContentsMargins(4,1,4,1);fx.setSpacing(3)
        fx.addWidget(QLabel("类别:",styleSheet=f"color:{TEXT_SECONDARY};font-size:11px;"))
        self._cat=QComboBox();self._cat.addItems(CATEGORIES)
        self._cat.setStyleSheet(f"background:{BG_SURFACE};color:{TEXT_PRIMARY};border:1px solid {BORDER};border-radius:2px;padding:1px 4px;font-size:11px;")
        self._cat.currentIndexChanged.connect(self._apply)
        fx.addWidget(self._cat)
        self._st=QLabel("就绪",styleSheet=f"color:{TEXT_SECONDARY};font-size:11px;");fx.addStretch();fx.addWidget(self._st)
        l.addWidget(fb)
        self._pr=QProgressBar();self._pr.setFixedHeight(3);self._pr.setVisible(False)
        self._pr.setStyleSheet(f"QProgressBar{{background:{BG_SURFACE};border:none;border-radius:1px;}}QProgressBar::chunk{{background:{PRIMARY};border-radius:1px;}}");l.addWidget(self._pr)
        sp=QSplitter(Qt.Orientation.Horizontal);sp.setHandleWidth(1)
        self._tr=QTreeWidget();self._tr.setHeaderHidden(True);self._tr.setMinimumWidth(100);self._tr.setMaximumWidth(250)
        self._tr.itemClicked.connect(self._on_tree);sp.addWidget(self._tr)
        self._tv=QTableView();self._tv.setAlternatingRowColors(True);self._tv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tv.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tv.customContextMenuRequested.connect(self._ctx);self._tv.doubleClicked.connect(self._dbl);self._tv.clicked.connect(self._clk)
        self._tv.verticalHeader().setDefaultSectionSize(28);self._tv.setSortingEnabled(True)
        hh=self._tv.horizontalHeader();hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive);hh.setStretchLastSection(True)
        sp.addWidget(self._tv);sp.setSizes([140,960]);l.addWidget(sp,1)
        self._md=AModel();self._px=Proxy();self._px.setSourceModel(self._md);self._tv.setModel(self._px);self._setw(BCOLS)

    def _setw(self,cols):
        for i,(_,w,_) in enumerate(cols): self._tv.setColumnWidth(i,w)

    def _ot(self,items):
        self._tr.clear();nm={}
        for d in items:
            n=QTreeWidgetItem([d["n"]]);n.setData(0,Qt.ItemDataRole.UserRole,d["id"]);nm[d["id"]]=n
        for d in items:
            n=nm[d["id"]];p=d.get("p")
            if p is not None and p in nm: nm[p].addChild(n)
            else: self._tr.addTopLevelItem(n)

    def _od(self,rows):
        self._data=rows;hp=any(r.get("bp")or r.get("sp")for r in rows[:100])
        self._st.setText(f"共 {len(rows)} 条"if hp else"暂无价格，请先在主界面更新");self._apply()

    def _on_tree(self,item):
        ids=set()
        def c(n):
            mid=n.data(0,Qt.ItemDataRole.UserRole)
            if mid: ids.add(mid)
            for i in range(n.childCount()): c(n.child(i))
        c(item)
        if ids:
            self._data = []
            self._iw=ItemsW(list(ids),parent=self);self._iw.done.connect(self._od);self._iw.start()

    def _apply(self):
        data = self._data
        cat = self._cat.currentIndex()
        if data and cat > 0:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
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
            elif cat == 4:  # 势力蓝图制造 — 名称含 Navy/Faction/Imperial/Republic/Federation 的制造蓝图
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
            elif cat == 6:  # 行星开发 — 行星管理相关 market_group
                c.execute("""SELECT DISTINCT i.type_id FROM item i
                    JOIN market_tree mt ON i.market_group_id = mt.market_group_id
                    WHERE mt.parent_group_id IN (
                        SELECT market_group_id FROM market_tree WHERE zh_name LIKE '%行星%' OR en_name LIKE '%Planet%'
                    ) OR mt.parent_group_id IN (
                        WITH RECURSIVE s AS(SELECT market_group_id FROM market_tree WHERE zh_name LIKE '%行星%' OR en_name LIKE '%Planet%' OR en_name LIKE '%Command Center%'
                        UNION ALL SELECT m.market_group_id FROM market_tree m JOIN s ON m.parent_group_id=s.market_group_id)
                        SELECT market_group_id FROM s)""")
                pi_ids = {r[0] for r in c.fetchall()}
                data = [r for r in data if r["id"] in pi_ids]
            conn.close()
        self._filt = data
        self._upd()

    def _load_settings(self):
        import json, os
        p = os.path.join(os.path.dirname(DB_PATH), '..', 'data', 'score_settings.json')
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f: s = json.load(f)
                self._mfg.update(s.get("mfg", {}))
                self._trade.update(s.get("trade", {}))
            except: pass

    def _save_settings(self):
        import json, os
        p = os.path.join(os.path.dirname(DB_PATH), '..', 'data', 'score_settings.json')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({"mfg": self._mfg, "trade": self._trade}, f, ensure_ascii=False, indent=2)

    def _upd(self):
        if self._show_m:
            cols=BCOLS[:];cols.extend(MCOLS);self._md.set_cols(cols);self._setw(cols)
            if self._filt: self._calc(True)
            else: self._st.setText("无数据")
        elif self._show_t:
            cols=BCOLS[:];cols.extend(TCOLS);self._md.set_cols(cols);self._setw(cols)
            if self._filt: self._calc(False)
            else: self._st.setText("无数据")
        else: self._md.set_cols(BCOLS);self._setw(BCOLS);self._md.set_rows(self._filt);self._st.setText(f"共 {len(self._filt)} 条")

    def _calc(self,is_mfg):
        self._pr.setVisible(True);self._pr.setRange(0,len(self._filt));self._st.setText("计算评分中...")
        cfg=self._mfg if is_mfg else self._trade
        self._wp=ScoreW(list(self._filt),is_mfg,cfg,self)
        self._wp.progress.connect(lambda c,t:self._pr.setValue(c))
        self._wp.done.connect(self._cd);self._wp.start()

    def _cd(self,rows):
        self._pr.setVisible(False);self._filt=rows;self._md.set_rows(self._filt);self._st.setText(f"共 {len(self._filt)} 条 | 评分已计算")

    def _on_mfg(self): self._show_m=True;self._show_t=False;self._upd()
    def _on_trade(self): self._show_t=True;self._show_m=False;self._upd()

    def _smfg(self):
        d=MfgDlg(self)
        if d.exec(): self._mfg=d.get();self._save_settings()
        if self._show_m and self._filt: self._calc(True)

    def _strade(self):
        d=TradeDlg(self)
        if d.exec(): self._trade=d.get();self._save_settings()
        if self._show_t and self._filt: self._calc(False)

    def _clk(self,idx):
        t=idx.data(Qt.ItemDataRole.DisplayRole)
        if t and t!=DASH: QApplication.instance().clipboard().setText(str(t))

    def _dbl(self,idx):
        r=idx.data(Qt.ItemDataRole.UserRole)
        if r and r.get("id"): MatDlg(r["id"],self).exec()

    def _ctx(self,pos):
        idx=self._tv.currentIndex()
        if not idx.isValid(): return
        r=idx.data(Qt.ItemDataRole.UserRole)
        if not r: return
        m=QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{BG_SURFACE};border:1px solid {BORDER};border-radius:4px;padding:4px;color:{TEXT_PRIMARY};}}QMenu::item{{padding:4px 24px;border-radius:3px;}}QMenu::item:selected{{background:{PRIMARY};color:white;}}")
        a1=QAction(f"复制: {r.get('z','')}",self);a1.triggered.connect(lambda:QApplication.instance().clipboard().setText(r.get('z','')));m.addAction(a1)
        a2=QAction(f"复制ID: {r['id']}",self);a2.triggered.connect(lambda:QApplication.instance().clipboard().setText(str(r['id'])));m.addAction(a2)
        m.addSeparator();tid=r["id"]
        if self._show_m:
            k=_ck(tid,"mfg",self._mfg["hub"],self._mfg["char"]);res=_cget(k)
            if res:
                d=self._ds(res,True);a3=QAction("制造核算明细",self)
                a3.triggered.connect(lambda *a:QMessageBox.information(self,"制造核算明细",d));m.addAction(a3)
        if self._show_t:
            k=_ck(tid,"trade",self._trade["bh"]+self._trade["sh"],self._trade["char"]);res=_cget(k)
            if res:
                d=self._ds(res,False);a4=QAction("贸易核算明细",self)
                a4.triggered.connect(lambda *a:QMessageBox.information(self,"贸易核算明细",d));m.addAction(a4)
        m.addSeparator()
        a5=QAction("加入制造列表",self);a5.triggered.connect(lambda:QMessageBox.information(self,"提示","待实现"));m.addAction(a5)
        a6=QAction("加入代采购",self);a6.triggered.connect(lambda:QMessageBox.information(self,"提示","待实现"));m.addAction(a6)
        m.exec(self._tv.viewport().mapToGlobal(pos))

    def _ds(self,r,is_mfg):
        if is_mfg:
            b=r.get("breakdown",{});st=r.get("status","")
            if st: return f"状态: {st}"
            return (f"成本/个: {r.get('cost_per_unit',0):,.2f} ISK\n收入/个: {r.get('revenue_per_unit',0):,.2f} ISK\n单次利润: {r.get('profit_per_run',0):,.2f} ISK\n利润率: {r.get('margin_pct',0):.2f}%\n时间: {r.get('hours_per_run',0):.2f}h\n产能: {1/r.get('hours_per_run',1):.2f}个/h\n\n评分:\n利润率分: {b.get('profit_score',0):.1f}/40\n市场需求分: {b.get('volume_score',0):.1f}/30\n效率分: {b.get('efficiency_score',0):.1f}/30\nISK/h: {b.get('isk_per_hour',0):,.0f}\n\n总分: {r.get('score',0):.1f}/100")
        st=r.get("status","")
        if st: return f"状态: {st}"
        return (f"买入: {r.get('buy_cost',0):,.2f} ISK\n卖出: {r.get('sell_revenue',0):,.2f} ISK\n毛利: {r.get('gross_profit',0):,.2f} ISK\n利润率: {r.get('margin_pct',0):.2f}%\n每方利率: {r.get('profit_per_m3',0):.2f} ISK/m3\n\n总分: {r.get('score',0):.1f}/100")

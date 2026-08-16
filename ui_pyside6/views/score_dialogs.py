"""
评分弹窗与评分 Worker — 从 all_items_view.py 拆分而来
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)

from core.cache import TtlLRUCache
from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.container import get_container
from ui_pyside6.icon_cache import load_item_icon
from ui_pyside6.views.char_settings_view import get_character, get_character_list
from ui_pyside6.workers.base_worker import BaseBatchScoreWorker

_cache = TtlLRUCache(max_size=5000, ttl_seconds=1800)

REGIONS = TRADE_HUBS


def _icon_label(type_id: int, size: int = 32) -> QLabel | None:
    """创建物品图标标签，无图标时返回 None"""
    pix = load_item_icon(type_id, size=size)
    if pix is None:
        return None
    lbl = QLabel()
    lbl.setPixmap(pix)
    return lbl


class MfgDlg(QDialog):
    def __init__(self, current: dict | None = None, parent=None, type_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("制造评分设置")
        self.setMinimumWidth(260)
        form = QFormLayout(self)
        form.setSpacing(4)

        # 物品图标（如果有 type_id）
        if type_id is not None:
            icon = _icon_label(type_id)
            if icon:
                icon_row = QHBoxLayout()
                icon_row.addStretch()
                icon_row.addWidget(icon)
                icon_row.addStretch()
                form.addRow(icon_row)
            # 在标题中显示物品名
            try:
                name = get_container().item_repo.get_name(type_id)
                if name and name != str(type_id):
                    self.setWindowTitle(f"制造评分 — {name}")
            except Exception:
                pass

        cur = current or {}
        self.h = QComboBox()
        self.h.addItems(REGIONS)
        self.h.setCurrentText(cur.get("hub", "Jita"))
        form.addRow("中心:", self.h)
        self.c = QComboBox()
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        self.t = QDoubleSpinBox()
        self.t.setRange(0, 100)
        self.t.setSuffix(" %")
        self.t.setValue(cur.get("tax", 0))
        form.addRow("设施税:", self.t)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def get(self):
        c = self.c.currentText()
        return {
            "hub": self.h.currentText(),
            "char": c if c in get_character_list() else "main",
            "tax": self.t.value(),
        }


class TradeDlg(QDialog):
    def __init__(self, current: dict | None = None, parent=None, type_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("贸易评分设置")
        self.setMinimumWidth(260)
        form = QFormLayout(self)
        form.setSpacing(4)

        # 物品图标（如果有 type_id）
        if type_id is not None:
            icon = _icon_label(type_id)
            if icon:
                icon_row = QHBoxLayout()
                icon_row.addStretch()
                icon_row.addWidget(icon)
                icon_row.addStretch()
                form.addRow(icon_row)
            # 在标题中显示物品名
            try:
                name = get_container().item_repo.get_name(type_id)
                if name and name != str(type_id):
                    self.setWindowTitle(f"贸易评分 — {name}")
            except Exception:
                pass

        cur = current or {}
        self.bh = QComboBox()
        self.bh.addItems(REGIONS)
        self.bh.setCurrentText(cur.get("bh", "Jita"))
        form.addRow("买入:", self.bh)
        self.sh = QComboBox()
        self.sh.addItems(REGIONS)
        self.sh.setCurrentText(cur.get("sh", "Jita"))
        form.addRow("卖出:", self.sh)
        self.bs = QComboBox()
        self.bs.addItems(["卖单", "买单"])
        self.bs.setCurrentText("卖单" if cur.get("bs", "sell") == "sell" else "买单")
        form.addRow("买价:", self.bs)
        self.ss = QComboBox()
        self.ss.addItems(["卖单", "买单"])
        self.ss.setCurrentText("卖单" if cur.get("ss", "sell") == "sell" else "买单")
        form.addRow("卖价:", self.ss)
        self.c = QComboBox()
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def get(self):
        c = self.c.currentText()
        return {
            "bh": self.bh.currentText(),
            "sh": self.sh.currentText(),
            "bs": "sell" if self.bs.currentIndex() == 0 else "buy",
            "ss": "sell" if self.ss.currentIndex() == 0 else "buy",
            "char": c if c in get_character_list() else "main",
        }


class ScoreW(BaseBatchScoreWorker):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, items, is_mfg, cfg, parent=None):
        char_name = cfg.get("char", "")
        char = get_character(char_name) if char_name else None
        super().__init__(items, char_config=char, char_name=char_name, parent=parent)
        self._mfg = is_mfg
        self._cfg = cfg

    def run(self):
        """ScoreW 自定义 run：预加载市场数据，迭代 _calc_item 并 emit done(list)"""
        total = len(self._items)
        # 批量预加载所有物品的市场价和成交量（一次查询代替 N 次）
        hub = self._cfg.get("hub", "Jita") if self._mfg else self._cfg.get("sh", "Jita")
        mkt_id = TRADE_HUB_IDS.get(hub, 10000002)
        self._batch_market: dict[int, dict[str, float | int | None]] = {}
        try:
            tids = [row.get("id") for row in self._items if row.get("id")]
            if tids:
                with get_container().db.connect("mkt") as conn:
                    ph = ",".join("?" * len(tids))
                    cur = conn.cursor()
                    cur.execute(
                        f"SELECT type_id, buy_price, sell_price, buy_volume, sell_volume "
                        f"FROM market_prices WHERE region_id=? AND type_id IN ({ph})",
                        (mkt_id, *tids),
                    )
                    for r in cur.fetchall():
                        self._batch_market[r[0]] = {
                            "bp": r[1],
                            "sp": r[2],
                            "bv": r[3] or 0,
                            "sv": r[4] or 0,
                        }
        except Exception:
            self._batch_market = {}

        # SCI 按默认材料机库星系（制造/反应生效；None → 回退吉他，与旧行为一致）
        from services.inventory_manager import get_default_mat_hangar_system_id

        self._system_id = get_default_mat_hangar_system_id()

        for i, item in enumerate(self._items):
            if self.isInterruptionRequested():
                return
            try:
                self._calc_item(item)
            except Exception:
                pass
            if (i + 1) % 50 == 0 or i == total - 1:
                self.progress.emit(i + 1, total)
        self.done.emit(self._items)

    def _calc_item(self, row) -> dict:
        tid = row.get("id")
        if not tid:
            return row  # type: ignore[no-any-return]

        if self._mfg:
            hub = self._cfg["hub"]
            k = f"{tid}|mfg|{hub}|{self._cfg['char']}|{self._system_id or ''}"
            r = _cache.get(k)
            if not r:
                r = (
                    get_container()
                    .scoring_service()
                    .calc_manufacturing_score(
                        tid,
                        self._char_config,
                        hub,
                        hub,
                        self._cfg.get("tax", 0),
                        system_id=self._system_id,
                    )
                )
                _cache.set(k, r)
            h = r.get("hours_per_run", 1) or 1
            runs_per_day = 24 / h
            st = r.get("status", "")
            mkt = self._batch_market.get(tid, {})
            bvol = mkt.get("bv", 0) or 0
            profit_per_run = r.get("profit_per_run", 0) or 0
            daily_out = min(runs_per_day, bvol)
            daily_profit = profit_per_run * daily_out
            veto = st or (bvol == 0 and "no_depth")
            tag = _fmt_tag(daily_profit, veto)
            row.update(
                {
                    "mc": r.get("cost_per_unit"),
                    "mr": r.get("revenue_per_unit"),
                    "mh": runs_per_day,
                    "ms": st,
                    "_tag": tag,
                    "mm": r.get("margin_pct"),
                    "mdp": daily_profit,
                    "bp": mkt.get("bp"),
                    "sp": mkt.get("sp"),
                }
            )
        else:
            bh = self._cfg["bh"]
            sh = self._cfg["sh"]
            k = f"{tid}|trade|{bh + sh}|{self._cfg['char']}"
            r = _cache.get(k)
            if not r:
                r = (
                    get_container()
                    .scoring_service()
                    .calc_trade_score(
                        tid,
                        bh,
                        sh,
                        self._cfg["bs"],
                        self._cfg["ss"],
                        self._char_config,
                    )
                )
                _cache.set(k, r)
            st = r.get("status", "")
            mkt = self._batch_market.get(tid, {})
            bvol = mkt.get("bv", 0) or 0
            gp = r.get("gross_profit", 0) or 0
            sellable = min(bvol, 5000)
            daily_profit = gp * sellable
            veto = st or (bvol == 0 and "no_depth")
            tag = _fmt_tag(daily_profit, veto)
            row.update(
                {
                    "tc": r.get("buy_cost"),
                    "tr": r.get("sell_revenue"),
                    "_tag": tag,
                    "tm": r.get("margin_pct"),
                    "tpm": r.get("profit_per_m3"),
                    "bp": mkt.get("bp"),
                    "sp": mkt.get("sp"),
                }
            )
        return row  # type: ignore[no-any-return]


def _fmt_tag(daily_profit: float, veto: str | bool = "") -> str:
    """将日均利润格式化为等级标签"""
    if veto:
        return "✗"
    if daily_profit >= 50_000_000:
        return f"{daily_profit / 100_000_000:.1f}亿 S"
    if daily_profit >= 10_000_000:
        return f"{daily_profit / 10_000:.0f}万 A"
    if daily_profit >= 1_000_000:
        return f"{daily_profit / 10_000:.0f}万 B"
    if daily_profit >= 100_000:
        return f"{daily_profit / 10_000:.0f}万 C"
    return f"{daily_profit / 10_000:.0f}万 D"

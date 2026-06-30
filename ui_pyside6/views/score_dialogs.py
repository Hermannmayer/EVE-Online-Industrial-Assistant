"""
评分弹窗与评分 Worker — 从 all_items_view.py 拆分而来
"""
import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.container import get_container
from core.paths import ICON_DIR
from services.scoring_cache import cache_key as _ck
from services.scoring_cache import get as _cget
from services.scoring_cache import set as _cset
from ui_pyside6.views.char_settings_view import get_character, get_character_list

REGIONS = TRADE_HUBS


def _icon_label(type_id: int, size: int = 32) -> QLabel | None:
    """创建物品图标标签，无图标时返回 None"""
    from PySide6.QtCore import Qt as _Qt
    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
    if not os.path.exists(icon_path):
        return None
    lbl = QLabel()
    lbl.setPixmap(QPixmap(icon_path).scaled(
        size, size, _Qt.AspectRatioMode.KeepAspectRatio, _Qt.TransformationMode.SmoothTransformation,
    ))
    return lbl


class MfgDlg(QDialog):
    def __init__(self, current: dict | None = None, parent=None, type_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("制造评分设置")
        self.setMinimumWidth(260)
        self.setStyleSheet(f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};")
        ss = (
            f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;padding:2px 6px;"
        )
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
                with get_container().db.connect("ref") as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT zh_name FROM item WHERE type_id = ?", (type_id,))
                    r = cur.fetchone()
                    if r and r[0]:
                        self.setWindowTitle(f"制造评分 — {r[0]}")
            except Exception:
                pass

        cur = current or {}
        self.h = QComboBox()
        self.h.addItems(REGIONS)
        self.h.setStyleSheet(ss)
        self.h.setCurrentText(cur.get("hub", "Jita"))
        form.addRow("中心:", self.h)
        self.c = QComboBox()
        self.c.setStyleSheet(ss)
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        self.t = QDoubleSpinBox()
        self.t.setRange(0, 100)
        self.t.setSuffix(" %")
        self.t.setStyleSheet(ss)
        self.t.setValue(cur.get("tax", 0))
        form.addRow("设施税:", self.t)
        b = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
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
        self.setStyleSheet(f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};")
        ss = (
            f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:2px;padding:2px 6px;"
        )
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
                with get_container().db.connect("ref") as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT zh_name FROM item WHERE type_id = ?", (type_id,))
                    r = cur.fetchone()
                    if r and r[0]:
                        self.setWindowTitle(f"贸易评分 — {r[0]}")
            except Exception:
                pass

        cur = current or {}
        self.bh = QComboBox()
        self.bh.addItems(REGIONS)
        self.bh.setStyleSheet(ss)
        self.bh.setCurrentText(cur.get("bh", "Jita"))
        form.addRow("买入:", self.bh)
        self.sh = QComboBox()
        self.sh.addItems(REGIONS)
        self.sh.setStyleSheet(ss)
        self.sh.setCurrentText(cur.get("sh", "Jita"))
        form.addRow("卖出:", self.sh)
        self.bs = QComboBox()
        self.bs.addItems(["卖单", "买单"])
        self.bs.setStyleSheet(ss)
        self.bs.setCurrentText("卖单" if cur.get("bs", "sell") == "sell" else "买单")
        form.addRow("买价:", self.bs)
        self.ss = QComboBox()
        self.ss.addItems(["卖单", "买单"])
        self.ss.setStyleSheet(ss)
        self.ss.setCurrentText("卖单" if cur.get("ss", "sell") == "sell" else "买单")
        form.addRow("卖价:", self.ss)
        self.c = QComboBox()
        self.c.setStyleSheet(ss)
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        b = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
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


class ScoreW(QThread):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, items, is_mfg, cfg, parent=None):
        super().__init__(parent)
        self._items = items
        self._mfg = is_mfg
        self._cfg = cfg

    def run(self):
        char = get_character(self._cfg.get("char", "")) if self._cfg.get("char") else None
        from services.scoring import get_price as _gp
        total = len(self._items)
        with get_container().db.connect('ref', 'mkt', 'bp') as conn:
            cur = conn.cursor()
            for i, row in enumerate(self._items):
                tid = row["id"]
                if self._mfg:
                    hub = self._cfg["hub"]
                    k = _ck(tid, "mfg", hub, self._cfg["char"])
                    r = _cget(k)
                    if not r:
                        r = get_container().scoring_service().calc_manufacturing_score(
                            tid, char or {}, hub, hub, self._cfg.get("tax", 0),
                        )
                        _cset(k, r)
                    h = r.get("hours_per_run", 1) or 1
                    runs_per_day = 24 / h
                    st = r.get("status", "")
                    # 市场深度检查
                    mkt_id = TRADE_HUB_IDS.get(hub, 10000002)
                    depth = cur.execute(
                        "SELECT buy_volume FROM mkt.market_prices"
                        " WHERE type_id=? AND region_id=? LIMIT 1",
                        (tid, mkt_id),
                    ).fetchone()
                    bvol = depth[0] if depth else 0
                    profit_per_run = r.get("profit_per_run", 0) or 0
                    daily_out = min(runs_per_day, bvol)
                    daily_profit = profit_per_run * daily_out
                    veto = st or (bvol == 0 and "no_depth")
                    tag = _fmt_tag(daily_profit, veto)
                    row.update({
                        "mc": r.get("cost_per_unit"),
                        "mr": r.get("revenue_per_unit"),
                        "mh": runs_per_day,
                        "ms": st,
                        "_tag": tag,
                        "mm": r.get("margin_pct"),
                        "mdp": daily_profit,
                        "bp": _gp(tid, "buy", hub),
                        "sp": _gp(tid, "sell", hub),
                    })
                else:
                    bh = self._cfg["bh"]
                    sh = self._cfg["sh"]
                    k = _ck(tid, "trade", bh + sh, self._cfg["char"])
                    r = _cget(k)
                    if not r:
                        r = get_container().scoring_service().calc_trade_score(
                            tid, bh, sh, self._cfg["bs"], self._cfg["ss"], char or {},
                        )
                        _cset(k, r)
                    st = r.get("status", "")
                    mkt_id = TRADE_HUB_IDS.get(sh, 10000002)
                    depth = cur.execute(
                        "SELECT buy_volume FROM mkt.market_prices"
                        " WHERE type_id=? AND region_id=? LIMIT 1",
                        (tid, mkt_id),
                    ).fetchone()
                    bvol = depth[0] if depth else 0
                    gp = r.get("gross_profit", 0) or 0
                    sellable = min(bvol, 5000)
                    daily_profit = gp * sellable
                    veto = st or (bvol == 0 and "no_depth")
                    tag = _fmt_tag(daily_profit, veto)
                    row.update({
                        "tc": r.get("buy_cost"),
                        "tr": r.get("sell_revenue"),
                        "_tag": tag,
                        "tm": r.get("margin_pct"),
                        "tpm": r.get("profit_per_m3"),
                        "bp": _gp(tid, self._cfg["bs"], bh),
                        "sp": _gp(tid, self._cfg["ss"], sh),
                    })
                if (i + 1) % 50 == 0 or i == total - 1:
                    self.progress.emit(i + 1, total)


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

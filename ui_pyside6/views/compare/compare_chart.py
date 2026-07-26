"""对比后台计算 — CompareWorker + 物品搜索/名称辅助函数"""

from PySide6.QtCore import QThread, Signal

from core.cache import TtlLRUCache
from core.container import get_container
from ui_pyside6.views.char_settings_view import get_character

_cache = TtlLRUCache(max_size=500, ttl_seconds=1800)

# ── 搜索 SQL（参数化） ──
_SEARCH_SQL = (
    "SELECT i.type_id, i.zh_name, i.en_name "
    "FROM item i "
    "WHERE (i.type_id = ? OR i.zh_name LIKE ? OR i.en_name LIKE ?) "
    "ORDER BY CASE WHEN i.en_name LIKE ? THEN 0 "
    "WHEN i.zh_name LIKE ? THEN 1 ELSE 2 END, i.zh_name "
    "LIMIT 50"
)


def search_items(query: str) -> list[dict]:
    """按名称/ID 搜索物品"""
    q = query.strip()
    if not q:
        return []
    like = f"%{q}%"
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        if q.isdigit():
            c.execute(_SEARCH_SQL, (int(q), like, like, f"{q}%", f"{q}%"))
        else:
            c.execute(_SEARCH_SQL, (0, like, like, f"{q}%", f"{q}%"))
        return [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]


def item_name(type_id: int) -> str:
    """获取物品中文名"""
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        return (row[0] or row[1] or str(type_id)) if row else str(type_id)


class CompareWorker(QThread):
    """后台对比计算 Worker"""

    progress = Signal(int, int)
    item_done = Signal(int, dict)
    done = Signal(list)

    def __init__(self, items: list[dict], mode: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._items = items
        self._mode = mode
        self._cfg = cfg
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._items)
        results = []
        char_cfg = None
        char_name = self._cfg.get("char", "")
        if char_name:
            char_cfg = get_character(char_name)

        for i, item in enumerate(self._items):
            if self._cancelled:
                break

            tid = item["type_id"]
            name = item.get("name") or item_name(tid)
            row = {"type_id": tid, "name": name}

            try:
                if self._mode == "mfg":
                    self._calc_mfg(tid, row, char_cfg)
                elif self._mode == "trade":
                    self._calc_trade(tid, row, char_cfg)
                elif self._mode == "reaction":
                    self._calc_reaction(tid, row, char_cfg)
            except Exception as e:
                row["status"] = f"错误: {e}"

            results.append(row)
            self.progress.emit(i + 1, total)
            self.item_done.emit(i + 1, row)

        self.done.emit(results)

    def _calc_mfg(self, tid: int, row: dict, char_cfg: dict | None):
        hub = self._cfg.get("hub", "Jita")
        tax = self._cfg.get("tax", 0)
        me = self._cfg.get("me", 0)
        te = self._cfg.get("te", 0)

        k = f"{tid}|mfg|{hub}|{self._cfg.get('char', '')}"
        r = _cache.get(k)
        if not r:
            r = (
                get_container()
                .scoring_service()
                .calc_manufacturing_score(
                    tid,
                    char_cfg or {},
                    hub,
                    hub,
                    tax,
                    bp_me=me,
                    bp_te=te,
                )
            )
            _cache.set(k, r)

        h = r.get("hours_per_run", 1) or 1
        runs_per_day = 24 / h
        row.update(
            {
                "cost": r.get("cost_per_unit", 0),
                "revenue": r.get("revenue_per_unit", 0),
                "profit": r.get("profit_per_run", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "isk_per_hour": r.get("isk_per_hour", 0),
                "runs_per_day": runs_per_day,
                "status": r.get("status", ""),
            }
        )

    def _calc_trade(self, tid: int, row: dict, char_cfg: dict | None):
        bh = self._cfg.get("bh", "Jita")
        sh = self._cfg.get("sh", "Jita")
        bs = self._cfg.get("bs", "sell")
        ss = self._cfg.get("ss", "sell")

        k = f"{tid}|trade|{bh + sh}|{self._cfg.get('char', '')}"
        r = _cache.get(k)
        if not r:
            r = get_container().scoring_service().calc_trade_score(tid, bh, sh, bs, ss, char_cfg or {})
            _cache.set(k, r)

        row.update(
            {
                "buy_cost": r.get("buy_cost", 0),
                "sell_revenue": r.get("sell_revenue", 0),
                "gross_profit": r.get("gross_profit", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "profit_per_m3": r.get("profit_per_m3", 0),
                "status": r.get("status", ""),
            }
        )

    def _calc_reaction(self, tid: int, row: dict, char_cfg: dict | None):
        hub = self._cfg.get("hub", "Jita")
        tax = self._cfg.get("tax", 0)

        k = f"{tid}|reaction|{hub}|{self._cfg.get('char', '')}"
        r = _cache.get(k)
        if not r:
            r = (
                get_container()
                .scoring_service()
                .calc_reaction_score(
                    tid,
                    char_cfg or {},
                    hub,
                    hub,
                    tax,
                )
            )
            _cache.set(k, r)

        h = r.get("hours_per_run", 1) or 1
        runs_per_day = 24 / h
        row.update(
            {
                "cost": r.get("cost_per_unit", 0),
                "revenue": r.get("revenue_per_unit", 0),
                "profit": r.get("profit_per_run", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "isk_per_hour": r.get("isk_per_hour", 0),
                "runs_per_day": runs_per_day,
                "status": r.get("status", ""),
            }
        )

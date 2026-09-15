"""评分线程 `ScoreW`（原先在 `ui_pyside6/views/score_dialogs.py`）。

QML 侧（全物品页 / 可制造页）与 Widgets 对话框共用这一份。
"""

from PySide6.QtCore import Signal

from core.cache import TtlLRUCache
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.formatting import fmt_tag as _fmt_tag
from services import char_config_resolver
from ui_qml.workers.base_worker import BaseBatchScoreWorker

#: 单次评分的中间结果缓存（原先在 `score_dialogs.py`，随 ScoreW 一起搬来）
_cache = TtlLRUCache(max_size=5000, ttl_seconds=1800)


class ScoreW(BaseBatchScoreWorker):
    progress = Signal(int, int)
    done = Signal(list)  # type: ignore[assignment]  # 自定义 run 用 done 带结果 list，与基类 done=Signal(float) 语义不同

    def __init__(self, items, is_mfg, cfg, parent=None):
        char_name = cfg.get("char", "")
        char = char_config_resolver.get_character(char_name) if char_name else None
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
                self._batch_market = get_container().market_repo.get_batch_market_snapshot(tids, mkt_id)
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

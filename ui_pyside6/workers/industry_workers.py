"""工业制造 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from services.scoring_service import calc_manufacturing_score
from ui_pyside6.workers.base_worker import BaseBatchScoreWorker, BaseScoreWorker


class SearchWorker(QThread):
    """搜索可制造物品"""

    finished = Signal(list)

    def __init__(self, query: str, db, parent=None):
        super().__init__(parent)
        self._query = query
        self._db = db

    def run(self):
        with self._db.connect("ref") as conn:
            c = conn.cursor()
            like = f"%{self._query}%"
            c.execute(
                """
                SELECT type_id, zh_name, en_name FROM item
                WHERE en_name LIKE ? OR zh_name LIKE ?
                ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                         LENGTH(en_name), type_id
                LIMIT 30
            """,
                (like, like, f"{self._query}%", f"{self._query}%"),
            )
            rows = [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]
            self.finished.emit(rows)


class ScoreWorker(BaseScoreWorker):
    """单项制造评分 — 继承 BaseScoreWorker"""

    def __init__(
        self,
        type_id: int,
        bp_me: int,
        bp_te: int,
        mat_hub: str,
        sell_hub: str,
        tax: float,
        mat_price_type: str = "sell",
        runs: int = 1,
        parent=None,
        char_name: str | None = None,
    ):
        super().__init__(type_id, char_name=char_name, parent=parent)
        self._bp_me = bp_me
        self._bp_te = bp_te
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._tax = tax
        self._mat_price_type = mat_price_type
        self._runs = runs

    def _compute(self) -> dict:
        return calc_manufacturing_score(
            type_id=self._type_id,
            char_config=self._char_config,
            bp_me=self._bp_me,
            bp_te=self._bp_te,
            mat_source_hub=self._mat_hub,
            sell_hub=self._sell_hub,
            facility_tax_pct=self._tax,
            price_type_mat=self._mat_price_type,
            price_type_prod="sell",
        )


class BatchPlanCalcWorker(BaseBatchScoreWorker):
    """后台批量重算所有生产计划的利润/评分"""

    finished = Signal(list)  # [(plan_id, profit, margin, score, iskph, material_cost), ...]

    def __init__(self, plans: list[dict], char_config: dict, parent=None, char_name: str | None = None):
        super().__init__(plans, char_config=char_config, char_name=char_name, parent=parent)

    def _calc_item(self, item) -> dict:
        plan_id = item.get("id")
        if not plan_id:
            return None
        try:
            sell_hub = item.get("sell_hub", "Jita")
            # 从角色配置读取设施税率（如未设置则为 0）
            fac_tax = self._char_config.get("market", {}).get(sell_hub.lower(), {}).get("facility_tax", 0.0)
            r = calc_manufacturing_score(
                type_id=item.get("product_type_id"),
                char_config=self._char_config,
                bp_me=item.get("me_level", 0),
                bp_te=item.get("te_level", 0),
                mat_source_hub=item.get("mat_hub", "Jita"),
                sell_hub=sell_hub,
                facility_tax_pct=fac_tax,
                price_type_mat="sell",
                price_type_prod="sell",
            )
            return (
                plan_id,
                r.get("profit_per_run", 0),
                r.get("margin_pct", 0),
                r.get("score", 0),
                r.get("isk_per_hour", 0),
                r.get("breakdown", {}).get("material_cost", 0),
                r.get("hours_per_run", 0),  # 制造时长（小时）
            )
        except Exception:
            return (plan_id, 0, 0, 0, 0, 0, 0)

    def run(self):
        """BatchPlanCalcWorker 的 run 覆盖：直接遍历 _items 生成结果列表"""
        results = []
        for item in self._items:
            r = self._calc_item(item)
            if r is not None:
                results.append(r)
        self.finished.emit(results)


class RankWorker(QThread):
    """批量评分所有可制造物品"""

    progress = Signal(int, int)
    result = Signal(list)
    done = Signal(float)

    def __init__(
        self,
        mat_hub: str,
        sell_hub: str,
        mat_price_type: str,
        bp_me: int,
        bp_te: int,
        tax: float,
        db,
        parent=None,
        top_n: int | None = None,
        char_name: str | None = None,
    ):
        super().__init__(parent)
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._mat_price_type = mat_price_type
        self._bp_me = bp_me
        self._bp_te = bp_te
        self._tax = tax
        self._db = db
        self._top_n = top_n
        self._char_name = char_name

    def run(self):
        import time

        from services.scoring_service import resolve_char_config

        started = time.time()
        results = []

        # 加载实际角色技能配置
        char_config = resolve_char_config(char_name=self._char_name)

        with self._db.connect("bp", "mkt") as conn:
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT product_type_id FROM blueprint_products
                WHERE activity = 'manufacturing'
            """)
            tids = [r[0] for r in c.fetchall()]

        total = len(tids)
        for i, tid in enumerate(tids):
            r = calc_manufacturing_score(
                type_id=tid,
                char_config=char_config,
                bp_me=self._bp_me,
                bp_te=self._bp_te,
                mat_source_hub=self._mat_hub,
                sell_hub=self._sell_hub,
                facility_tax_pct=self._tax,
                price_type_mat=self._mat_price_type,
                price_type_prod="sell",
            )
            if not r.get("status"):
                r["_type_id"] = tid
                results.append(r)

            if (i + 1) % 100 == 0:
                self.progress.emit(i + 1, total)

        results.sort(key=lambda x: x.get("isk_per_hour", 0), reverse=True)

        if self._top_n and self._top_n < len(results):
            results = results[: self._top_n]

        self.result.emit(results)
        self.done.emit(time.time() - started)

"""工业制造 — 后台 Worker 线程"""

from typing import Any

from PySide6.QtCore import QThread, Signal

from core.container import get_container
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
        system_id: int | None = None,
    ):
        super().__init__(type_id, char_name=char_name, parent=parent)
        self._bp_me = bp_me
        self._bp_te = bp_te
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._tax = tax
        self._mat_price_type = mat_price_type
        self._runs = runs
        self._system_id = system_id

    def _compute(self) -> dict:
        return (  # type: ignore[no-any-return]
            get_container()
            .scoring_service()
            .calc_manufacturing_score(
                type_id=self._type_id,
                char_config=self._char_config,
                bp_me=self._bp_me,
                bp_te=self._bp_te,
                mat_source_hub=self._mat_hub,
                sell_hub=self._sell_hub,
                facility_tax_pct=self._tax,
                price_type_mat=self._mat_price_type,
                price_type_prod="sell",
                system_id=self._system_id,
            )
        )


class BatchPlanCalcWorker(BaseBatchScoreWorker):
    """后台批量重算所有生产计划的利润/评分"""

    finished = Signal(
        list
    )  # [(plan_id, profit, margin, score, iskph, material_cost, hours, daily, personal_margin), ...]

    def __init__(
        self,
        plans: list[dict],
        char_config: dict,
        parent=None,
        char_name: str | None = None,
        mat_hub: str = "Jita",
        mat_price_type: str = "sell",
        prod_hub: str = "Jita",
        prod_price_type: str = "sell",
    ):
        super().__init__(plans, char_config=char_config, char_name=char_name, parent=parent)
        self._char_name_internal = char_name or ""
        self._char_config_cache: dict[str, dict] = {self._char_name_internal: self._char_config}
        self._mat_hub = mat_hub
        self._mat_price_type = mat_price_type
        self._prod_hub = prod_hub
        self._prod_price_type = prod_price_type
        self._inv_map: dict[int, tuple[int, float]] | None = None  # 批量重算期间库存快照只取一次

    def _resolve_char_config(self, plan_char_name: str) -> dict:
        """按计划角色名解析配置，带缓存"""
        if not plan_char_name or plan_char_name == self._char_name_internal:
            return self._char_config
        if plan_char_name not in self._char_config_cache:
            from services.char_config_resolver import resolve_char_config

            self._char_config_cache[plan_char_name] = resolve_char_config(char_name=plan_char_name) or {}
        return self._char_config_cache[plan_char_name]

    def _calc_item(self, item) -> Any:
        plan_id = item.get("id")
        if not plan_id:
            return None
        try:
            # 按计划实际设定人物解析配置
            plan_char = (item.get("char_name") or "").strip()
            char_config = self._resolve_char_config(plan_char)

            # 统一调用 calculate_plan_metrics()，所有路径参数决议一致
            result = (
                get_container()
                .scoring_service()
                .calculate_plan_metrics(
                    item,
                    char_config,
                    price_type_mat=self._mat_price_type,
                    price_type_prod=self._prod_price_type,
                )
            )
            return (
                plan_id,
                result.get("profit", 0),
                result.get("margin", 0),
                result.get("score", 0),
                result.get("iskph", 0),
                result.get("material_cost", 0),
                result.get("calculated_time", 0) / 3600,  # 秒→小时
                result.get("daily_output", 0),
                self._calc_personal_margin(item, result),
            )
        except Exception:
            return (plan_id, 0, 0, 0, 0, 0, 0, 0, 0)

    def _calc_personal_margin(self, plan: dict, result: dict) -> float:
        """计算考虑库存成本的个人利润率（%）。

        数据源完全来自 calculate_plan_metrics 的 result
        （revenue_per_run / fees_per_run / materials），不再直连蓝图库/市场库；
        库存经 get_inventory_cost_map() 批量重算期间只取一次。
        无库存时结果与市场利润率在 2 位小数内严格相等。
        """
        from services.scoring_service import ScoringService

        runs = max(int(plan.get("runs", 1)), 1)
        parallels = max(int(plan.get("parallels", 1)), 1)
        try:
            return ScoringService.calculate_personal_margin(result, self._get_inventory_cost_map(), runs, parallels)
        except Exception:
            return result.get("margin", 0) or 0

    def _get_inventory_cost_map(self) -> dict[int, tuple[int, float]]:
        """批量重算期间库存快照只取一次（避免每计划重复聚合查询）"""
        if self._inv_map is None:
            from services.inventory_manager import get_inventory_cost_map

            self._inv_map = get_inventory_cost_map()
        return self._inv_map

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
        system_id: int | None = None,
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
        self._system_id = system_id

    def run(self):
        import time

        from services.char_config_resolver import resolve_char_config

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
            r = (
                get_container()
                .scoring_service()
                .calc_manufacturing_score(
                    type_id=tid,
                    char_config=char_config,
                    bp_me=self._bp_me,
                    bp_te=self._bp_te,
                    mat_source_hub=self._mat_hub,
                    sell_hub=self._sell_hub,
                    facility_tax_pct=self._tax,
                    price_type_mat=self._mat_price_type,
                    price_type_prod="sell",
                    system_id=self._system_id,
                )
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

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
                self._calc_personal_margin(item, result.get("material_cost", 0), result.get("margin", 0)),
            )
        except Exception:
            return (plan_id, 0, 0, 0, 0, 0, 0, 0, 0)

    def _calc_personal_margin(self, plan: dict, market_mat_cost: float, market_margin: float) -> float:
        """计算考虑库存成本的个人利润率"""
        import sqlite3

        from core.paths import BP_DB_PATH, USR_DB_PATH
        from services.manufacturing_calculator import calc_material_for_runs
        from services.scoring_service import get_price

        type_id = plan.get("product_type_id")
        me = int(plan.get("me_level", 0) or 0)
        runs = max(int(plan.get("runs", 1)), 1)
        parallels = max(int(plan.get("parallels", 1)), 1)
        total_mult = runs * parallels

        try:
            # 1. 获取蓝图材料列表
            conn_bp = sqlite3.connect(BP_DB_PATH)
            c = conn_bp.cursor()
            c.execute(
                "SELECT bm.material_type_id, bm.quantity, ba.quantity AS prod_qty "
                "FROM blueprint_products bp "
                "JOIN blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id "
                "    AND bm.activity = bp.activity "
                "JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id "
                "    AND ba.activity = bp.activity "
                "WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'",
                (type_id,),
            )
            mat_rows = c.fetchall()
            conn_bp.close()
            if not mat_rows:
                return market_margin

            # 2. 获取库存数据
            conn_usr = sqlite3.connect(USR_DB_PATH)
            cur = conn_usr.cursor()
            cur.execute(
                "SELECT type_id, SUM(quantity), AVG(cost_price) FROM inventory_items "
                "WHERE quantity > 0 AND cost_price > 0 GROUP BY type_id"
            )
            inv_rows = cur.fetchall()
            conn_usr.close()
            inv_map: dict[int, tuple[int, float]] = {}
            for tid, qty, cost in inv_rows:
                inv_map[tid] = (int(qty), float(cost or 0))

            # 3. 计算个人材料成本（考虑库存）
            total_personal_cost = 0.0
            revenue = 0.0
            for mat_id, mat_qty, _prod_qty in mat_rows:
                need = calc_material_for_runs(mat_qty, 10, me, total_mult)
                stock_qty, stock_cost = inv_map.get(mat_id, (0, 0))
                market_price = get_price(mat_id, self._mat_price_type, self._mat_hub, _db=get_container().db) or 0

                if stock_qty >= need:
                    # 库存足够：全部用库存成本
                    mat_cost = need * stock_cost if stock_cost > 0 else need * market_price
                elif stock_qty > 0:
                    # 部分库存：混合成本
                    mat_cost = stock_qty * stock_cost + (need - stock_qty) * market_price
                else:
                    # 无库存：全用市场价
                    mat_cost = need * market_price

                total_personal_cost += mat_cost

            # 4. 计算收入（用市场价）
            prod_price = get_price(type_id, self._prod_price_type, self._prod_hub, _db=get_container().db) or 0
            revenue = prod_price * total_mult

            # 5. 个人利润率
            if total_personal_cost <= 0:
                return 0.0
            personal_profit = revenue - total_personal_cost
            return round(personal_profit / total_personal_cost * 100, 2)

        except Exception:
            return market_margin

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

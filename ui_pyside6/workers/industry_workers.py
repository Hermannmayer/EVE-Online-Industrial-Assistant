"""工业制造 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from services.plan_aggregator import aggregate_procurement
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

    def _calc_base(self, item) -> dict:
        """单计划基准指标（calculate_plan_metrics），异常返回空 dict。"""
        plan_id = item.get("id")
        if not plan_id:
            return {}
        try:
            plan_char = (item.get("char_name") or "").strip()
            char_config = self._resolve_char_config(plan_char)
            result: dict = (
                get_container()
                .scoring_service()
                .calculate_plan_metrics(
                    item,
                    char_config,
                    price_type_mat=self._mat_price_type,
                    price_type_prod=self._prod_price_type,
                )
            )
            return result
        except Exception:
            return {}

    def _apply_mother_subitem_cost(self, item, result, base_results) -> dict[int, float]:
        """拆解母项成本改按子项制造价合计。

        母项直接材料中由子项产线自制的组件，其成本从「市场价」改为「子项制造价」；
        未拆解的直接材料仍按市场价。返回 cost_overrides {type_id: 子项制造价}，
        供个人利润率计算使用。非母项/无子项时返回空 dict（不改动）。
        """
        gid = item.get("group_id") or item.get("group_number")
        if not gid:
            return {}
        lvl = int(item.get("child_level") or item.get("sub_level") or 0)
        subs = [
            (p, r)
            for pid, (p, r) in base_results.items()
            if (p.get("group_id") or p.get("group_number")) == gid
            and int(p.get("child_level") or p.get("sub_level") or 0) > lvl
        ]
        if not subs:
            return {}
        sub_cost_map = {p.get("product_type_id"): (r.get("material_cost", 0) or 0) for p, r in subs}

        runs = max(int(item.get("runs", 1)), 1)
        parallels = max(int(item.get("parallels", 1)), 1)
        total_mult = runs * parallels
        revenue = result.get("revenue", 0) or 0
        fees = result.get("fees", 0) or 0

        new_material_cost = 0.0
        cost_overrides: dict[int, float] = {}
        for mat in result.get("materials", []) or []:
            mid = mat.get("type_id")
            qty_per_run = mat.get("qty", 0) or 0
            if qty_per_run <= 0:
                continue
            if mid in sub_cost_map:
                new_material_cost += sub_cost_map[mid]
                cost_overrides[mid] = sub_cost_map[mid]
            else:
                new_material_cost += qty_per_run * total_mult * (mat.get("unit_price", 0) or 0)
        result["material_cost"] = round(new_material_cost, 2)
        profit = revenue - new_material_cost - fees
        result["profit"] = round(profit, 2)
        denom = new_material_cost + fees
        result["margin"] = round(profit / denom * 100, 2) if denom > 0 else 0.0
        return cost_overrides

    def _calc_personal_margin(self, plan: dict, result: dict, cost_overrides: dict[int, float] | None = None) -> float:
        """计算考虑库存成本的个人利润率（%）。

        数据源完全来自 calculate_plan_metrics 的 result
        （revenue_per_run / fees_per_run / materials），不再直连蓝图库/市场库；
        库存经 get_inventory_cost_map() 批量重算期间只取一次。
        无库存时结果与市场利润率在 2 位小数内严格相等。
        拆解母项的子项自制件经 cost_overrides 按其制造价计。
        """
        from services.scoring_service import ScoringService

        runs = max(int(plan.get("runs", 1)), 1)
        parallels = max(int(plan.get("parallels", 1)), 1)
        try:
            return ScoringService.calculate_personal_margin(
                result,
                self._get_inventory_cost_map(),
                runs,
                parallels,
                cost_overrides=cost_overrides,
            )
        except Exception:
            return result.get("margin", 0) or 0

    def _get_inventory_cost_map(self) -> dict[int, tuple[int, float]]:
        """批量重算期间库存快照只取一次（避免每计划重复聚合查询）"""
        if self._inv_map is None:
            from services.inventory_manager import get_inventory_cost_map

            self._inv_map = get_inventory_cost_map()
        return self._inv_map

    def run(self):
        """两遍计算：先算所有计划基准指标，再对拆解母项按子项制造价调整成本。"""
        base_results: dict[int, tuple[dict, dict]] = {}
        for item in self._items:
            pid = item.get("id")
            if pid:
                base_results[pid] = (item, self._calc_base(item))

        results = []
        for pid, (item, result) in base_results.items():
            overrides = self._apply_mother_subitem_cost(item, result, base_results)
            personal = self._calc_personal_margin(item, result, overrides)
            results.append(
                (
                    pid,
                    result.get("profit", 0),
                    result.get("margin", 0),
                    result.get("score", 0),
                    result.get("iskph", 0),
                    result.get("material_cost", 0),
                    result.get("calculated_time", 0) / 3600,  # 秒→小时
                    result.get("daily_output", 0),
                    personal,
                )
            )
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


class ProcurementSummaryWorker(QThread):
    """后台聚合「备料中」计划的待采购金额/体积（统计条模式，按计划机库扣库存）"""

    finished = Signal(float, float)  # total_cost, total_volume

    def __init__(
        self,
        plans: list[dict],
        *,
        default_mat_hangar_id: int | None = None,
        region_id: int = 10000002,
        price_type: str = "sell",
        parent=None,
    ):
        super().__init__(parent)
        self._plans = plans
        self._default_mat_hangar_id = default_mat_hangar_id
        self._region_id = region_id
        self._price_type = price_type

    def run(self):
        try:
            with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
                _rows, cost, vol = aggregate_procurement(
                    conn,
                    self._plans,
                    hangar_id=None,
                    default_hangar_id=self._default_mat_hangar_id,
                    region_id=self._region_id,
                    price_type=self._price_type,
                )
            self.finished.emit(cost, vol)
        except Exception:
            from core.logger import log

            log.exception("备料中采购汇总失败")
            self.finished.emit(0.0, 0.0)

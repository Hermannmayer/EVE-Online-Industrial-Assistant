"""工业制造 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from core.logger import log
from ui_pyside6.workers.base_worker import BaseBatchScoreWorker, BaseScoreWorker

# 估值失败的状态：`calculate_plan_metrics` 对它们返回**全零** dict（含 material_cost=0）。
# 这类行不得写回数据库 —— 否则一次失败就把库里正确的成本覆盖成 0，下线时按 0 成本入库。
_ZERO_COST_STATUSES = frozenset({"no_price", "no_blueprint", "no_materials"})


class SearchWorker(QThread):
    """搜索可制造物品"""

    finished_signal = Signal(list)

    def __init__(self, query: str, db, parent=None):
        super().__init__(parent)
        self._query = query
        self._db = db

    def run(self):
        from services.ui_data_service import search_manufacturable_items

        self.finished_signal.emit(search_manufacturable_items(self._query, db=self._db))


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

    finished_signal = Signal(
        list
    )  # [(plan_id, profit, margin, score, iskph, material_cost, hours, daily, personal_margin, market_margin), ...]

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
        mat_mult: float = 1.0,
        prod_mult: float = 1.0,
    ):
        super().__init__(plans, char_config=char_config, char_name=char_name, parent=parent)
        self._char_name_internal = char_name or ""
        self._char_config_cache: dict[str, dict] = {self._char_name_internal: self._char_config}
        self._mat_hub = mat_hub
        self._mat_price_type = mat_price_type
        self._prod_hub = prod_hub
        self._prod_price_type = prod_price_type
        self._mat_mult = mat_mult
        self._prod_mult = prod_mult
        self._inv_map: dict[int, tuple[int, float]] | None = None  # 批量重算期间库存快照只取一次
        self.failed_names: list[str] = []  # 本轮估值失败、已跳过不写库的计划（供 UI 提示）

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
                    mat_mult=self._mat_mult,
                    prod_mult=self._prod_mult,
                )
            )
            return result
        except Exception:
            # 不能静默 return {}：run() 会对空 dict 取 material_cost=0 并写成「有值」发出去，
            # 把库里原本正确的成本覆盖成 0。这里记日志，调用方据空 dict 跳过该行。
            log.exception("计划 %s 基准指标计算失败，本轮跳过不写库", plan_id)
            return {}

    def _apply_mother_subitem_cost(self, item, result, base_results) -> dict[int, float]:
        """拆解母项成本改按子项制造价合计（材料 + 子项制造作业费）。

        母项直接材料中由子项产线自制的组件，其成本从「市场价」改为「子项制造价」；
        未拆解的直接材料仍按市场价。返回 cost_overrides {type_id: 子项制造价}，
        供个人利润率计算使用。非母项/无子项时返回空 dict（不改动）。
        """
        from services.plan_metrics import adjust_mother_metrics, mother_subitem_cost_map

        sub_cost_map = mother_subitem_cost_map(base_results, item)
        if not sub_cost_map:
            return {}
        total_mult = max(int(item.get("runs", 1)), 1) * max(int(item.get("parallels", 1)), 1)
        mat_cost, profit, margin, overrides = adjust_mother_metrics(result, sub_cost_map, total_mult)
        result["material_cost"] = mat_cost
        result["profit"] = profit
        result["margin"] = margin
        return overrides

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
        """两遍计算：先算所有计划基准指标，再对拆解母项按子项制造价调整成本。

        深度优先（子级深者先算），保证嵌套拆解里子项先按孙项制造价调整，
        母项再读到正确的子项制造价；调整前留存市场利润率供「市场利润率」列使用。

        **估值失败的行不发出去**（评分异常返回空 dict、或 status 属于
        `_ZERO_COST_STATUSES`）——它们的 material_cost 是 0，写回会把库里的正确值清零。
        失败的条目记在 `failed_names`，供 UI 提示「成本沿用上次值」。
        """
        base_results: dict[int, tuple[dict, dict]] = {}
        for item in self._items:
            pid = item.get("id")
            if pid:
                base_results[pid] = (item, self._calc_base(item))

        # ── 本轮要跳过的计划 ──
        # ① 自身估值失败：评分异常 → 空 dict；或 status ∈ _ZERO_COST_STATUSES（全零 dict）
        # ② 母项连带：同组存在更深的失败子项时，mother_subitem_cost_map 会拿空 dict 去算
        #    子项制造价 → 母项成本被算**偏低**。宁可不写，也不写一个错的成本。
        def _grp(p: dict):
            return p.get("group_id") or p.get("group_number")

        def _lvl(p: dict) -> int:
            return int(p.get("child_level") or p.get("sub_level") or 0)

        bad_own = {pid for pid, (_i, r) in base_results.items() if not r or r.get("status") in _ZERO_COST_STATUSES}
        worst_bad_level: dict[int, int] = {}
        for pid, (item, _r) in base_results.items():
            if pid in bad_own and _grp(item):
                g = int(_grp(item))
                worst_bad_level[g] = max(worst_bad_level.get(g, -1), _lvl(item))

        def _skip(pid: int, item: dict) -> bool:
            """自身失败，或同组有更深的失败子项（母项连带）。"""
            if pid in bad_own:
                return True
            g = _grp(item)
            return bool(g) and worst_bad_level.get(int(g), -1) > _lvl(item)

        ordered = sorted(
            base_results.items(),
            key=lambda kv: -(int(kv[1][0].get("child_level") or kv[1][0].get("sub_level") or 0)),
        )
        results = []
        self.failed_names = []
        for pid, (item, result) in ordered:
            if _skip(pid, item):
                self.failed_names.append(str(item.get("product_name") or pid))
                continue
            try:
                market_margin = result.get("margin", 0) or 0  # 调整前留存市场口径利润率
                overrides = self._apply_mother_subitem_cost(item, result, base_results)
                personal = self._calc_personal_margin(item, result, overrides)
            except Exception:
                # 单条计划数据异常（如子项制造价调整收到非法值）不应让整个批量重算线程
                # 崩溃并抛到 Qt 事件循环；跳过该条，保留库中原值。
                log.exception("批量重算计划 %s 失败，已跳过", pid)
                self.failed_names.append(str(item.get("product_name") or pid))
                continue
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
                    market_margin,
                )
            )
        self.finished_signal.emit(results)


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

        from services.ui_data_service import get_all_manufacturable_product_ids

        tids = get_all_manufacturable_product_ids(db=self._db)

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

    finished_signal = Signal(float, float)  # total_cost, total_volume

    def __init__(
        self,
        plans: list[dict],
        *,
        default_mat_hangar_id: int | None = None,
        region_id: int = 10000002,
        price_type: str = "sell",
        price_mult: float = 1.0,
        parent=None,
    ):
        super().__init__(parent)
        self._plans = plans
        self._default_mat_hangar_id = default_mat_hangar_id
        self._region_id = region_id
        self._price_type = price_type
        self._price_mult = price_mult

    def run(self):
        try:
            from services.ui_data_service import aggregate_procurement_summary

            cost, vol = aggregate_procurement_summary(
                self._plans,
                default_mat_hangar_id=self._default_mat_hangar_id,
                region_id=self._region_id,
                price_type=self._price_type,
                price_mult=self._price_mult,
                db=get_container().db,
            )
            self.finished_signal.emit(cost, vol)
        except Exception:
            from core.logger import log

            log.exception("备料中采购汇总失败")
            self.finished_signal.emit(0.0, 0.0)

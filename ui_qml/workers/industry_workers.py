"""工业制造 — 后台 Worker 线程"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from core.logger import log
from ui_qml.workers.base_worker import BaseBatchScoreWorker, BaseScoreWorker

if TYPE_CHECKING:
    from services.plan_metrics import SubitemCost

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

    def _subitem_output_qty(self, mother: dict, base_results: dict) -> dict[int, int]:
        """同组更深子项产线的**实际产出量** `{子项 plan_id: runs × parallels × 单轮产出}`。

        子项产线排的是**净需求**（`services.plan_rebuild.plan_net_runs` 会先扣掉母项机库里
        已有的成品库存），所以它的产出量常常**小于**母项的材料需求（实测 紫外晶体 XL：
        需求 1368、产出 1310，差的 58 件在库存里）。拿不到产出量时调用方会退回
        「整线覆盖全部需求」的旧口径，等于把那 58 件当 0 成本。

        每条子线的产出量走 `services/blueprint_reader.plan_output_qty`（单轮产出按计划自己的
        activity 查配方、连接带 `ref` 才能排除 CCP 测试蓝图；「0 轮 = 不产出」也只有那一份规则）
        —— 查看核算桥用的是同一个函数，别再各写一份。
        取不到 / 出异常 → 返回 `{}`（旧口径，不报错）。
        """
        from services.blueprint_reader import plan_output_qty
        from services.plan_job_kinds import normalize as normalize_activity

        gid = mother.get("group_id") or mother.get("group_number")
        if not gid:
            return {}
        lvl = int(mother.get("child_level") or mother.get("sub_level") or 0)
        subs = [
            p
            for _pid, (p, _r) in base_results.items()
            if (p.get("group_id") or p.get("group_number")) == gid
            and int(p.get("child_level") or p.get("sub_level") or 0) > lvl
        ]
        if not subs:
            return {}
        out: dict[int, int] = {}
        try:
            with get_container().db.connect("ref", "bp") as conn:
                for p in subs:
                    pid = int(p.get("id") or 0)
                    qty = plan_output_qty(conn, p, activity=normalize_activity(p.get("activity")))
                    if pid and qty > 0:
                        out[pid] = qty
        except Exception:
            log.exception("读子项每轮产出失败，母项按「覆盖全部需求」的旧口径")
            return {}
        return out

    def _apply_mother_subitem_cost(self, item, result, base_results) -> dict[int, SubitemCost]:
        """拆解母项的自制子项制造价 → cost_overrides（**只供个人利润率使用**）。

        「成本」「利润」两列按**市场口径**（用户 2026-10-03 拍板）：因此本方法**不再覆写**
        `result` 的 material_cost / profit / margin —— 它们保持 calculate_plan_metrics 的市场口径。
        自制子项按自己制造价计的口径只体现在 `_calc_personal_margin(..., cost_overrides=...)`
        产出的「个人利润率%」列（它反映的是自己的成本优势，与市场口径各归其位）。

        返回 cost_overrides {子项 product_type_id: `SubitemCost`（单件制造价 + 覆盖数量）}；
        非母项/无子项时返回空 dict。0 轮子项的制造价为 0，已被 `mother_subitem_cost_map`
        剔除、进不了 override（否则个人利润率会凭空调高）。
        `output_qty_by_plan` 带上子项产线的**实际产出量**：子项产线排净需求，产出常小于母项
        需求，缺口得由消费方按库存/市价补齐（见 `services.plan_metrics.SubitemCost`）。
        """
        from services.plan_metrics import adjust_mother_metrics, mother_subitem_cost_map

        sub_cost_map = mother_subitem_cost_map(
            base_results,
            item,
            output_qty_by_plan=self._subitem_output_qty(item, base_results),
        )
        if not sub_cost_map:
            return {}
        total_mult = max(int(item.get("runs", 1)), 1) * max(int(item.get("parallels", 1)), 1)
        # 只取 overrides：mat/profit/margin 是个人口径，**不写回 result**（列语义走市场口径）
        _mat, _profit, _margin, overrides = adjust_mother_metrics(result, sub_cost_map, total_mult)
        return overrides

    def _calc_personal_margin(
        self, plan: dict, result: dict, cost_overrides: dict[int, SubitemCost] | None = None
    ) -> float:
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
        """两遍计算：先算所有计划基准指标，再按子项制造价算拆解母项的**个人利润率**。

        深度优先（子级深者先算），保证嵌套拆解里子项先按孙项制造价算好，
        母项再读到正确的子项制造价。子项制造价只经 cost_overrides 进「个人利润率%」列；
        **成本 / 利润 / 利润率列保持市场口径**（用户 2026-10-03 拍板），市场利润率另列留存。

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
                # 调整前留存市场口径利润率（「市场利润率%」列）：_apply_mother_subitem_cost 不再
                # 覆写 result["margin"]，所以这一份与「利润率%」列同值，二者都是市场口径。
                market_margin = result.get("margin", 0) or 0
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
                    result.get("profit", 0),  # 市场口径（industry_view 写 production_plans.profit）
                    result.get("margin", 0),  # 市场口径（写 production_plans.margin，与 profit 自洽）
                    result.get("score", 0),
                    result.get("iskph", 0),
                    result.get("material_cost", 0),  # 市场口径（写 production_plans.material_cost）
                    result.get("calculated_time", 0) / 3600,  # 秒→小时
                    result.get("daily_output", 0),
                    personal,  # 个人（库存/自制）口径 → production_plans.personal_margin
                    market_margin,  # 市场口径 → production_plans.market_margin（与 margin 同值）
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

        # 研究成本整批一次算好：逐件算会让每件重跑一遍拷贝/发明查询
        # （实测这条占批量耗时 93%）。system_id 必须与下面逐件传入的一致。
        from services.research_calculator import research_costs_batch

        with self._db.connect("bp") as bp_conn:
            research_costs = research_costs_batch(bp_conn, tids, solar_system_id=self._system_id)

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
                    research_costs=research_costs,
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
        self_made: set[int] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._plans = plans
        self._default_mat_hangar_id = default_mat_hangar_id
        self._region_id = region_id
        self._price_type = price_type
        self._price_mult = price_mult
        #: 由子项产线自制、不该买的产物 id（见 `plan_aggregator.self_made_type_ids`）。
        #: **必须由调用方按全量计划算好传进来** —— 本 worker 收到的 `plans` 是筛过的
        #: 「备料中」那份，拿它现算会把正在生产的子线漏掉。
        self._self_made = self_made

    def run(self):
        try:
            from services.ui_data_service import aggregate_procurement_summary

            cost, vol = aggregate_procurement_summary(
                self._plans,
                default_mat_hangar_id=self._default_mat_hangar_id,
                region_id=self._region_id,
                price_type=self._price_type,
                price_mult=self._price_mult,
                self_made=self._self_made,
                db=get_container().db,
            )
            self.finished_signal.emit(cost, vol)
        except Exception:
            from core.logger import log

            log.exception("备料中采购汇总失败")
            self.finished_signal.emit(0.0, 0.0)

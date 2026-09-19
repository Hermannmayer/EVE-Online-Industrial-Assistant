"""
评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

包含:
  - ScoringCache：线程安全、有界 TTL 缓存
  - 模块级便利函数：get_price / get_volume / get_system_cost_index / calc_*_score
    （评分链路取价直查 market.db market_prices，不经 PricingService）
  - ScoringService：可注入的评分服务类（同接口 + calc_reaction_score）；calc_*_score
    为薄委托 → scoring_facade 编排（读 DB/缓存）→ domain.scoring 纯算法
被 industry/trade 页各评分 Worker 消费。
"""

from __future__ import annotations

from core.cache import TtlLRUCache
from core.constants import TRADE_HUB_SYSTEM_IDS
from core.container import get_container
from core.eve_formulas import (
    calc_broker_rate,
    calc_relist_discount,
    calc_sales_tax_rate,
)
from domain.formulas import material_total_for_runs
from domain.scoring import REACTION_INSTALL_FEE_RATE  # noqa: F401  # 向后兼容 re-export
from services.blueprint_reader import (
    get_blueprint_materials,  # noqa: F401  # 由 application 门面经模块属性访问 + 测试 patch
)
from services.char_config_resolver import DEFAULT_SKILLS, resolve_char_config  # noqa: F401  # 向后兼容 re-export
from services.database_manager import DatabaseManager
from services.name_resolver import resolve_item_name  # noqa: F401  # 由 application 门面经模块属性访问
from services.repositories.market_repository import MarketRepository


def _hub_to_system_id(hub: str) -> int | None:
    """将贸易中心名称映射为太阳系 ID。"""
    return TRADE_HUB_SYSTEM_IDS.get(hub)


def _sum_materials(
    per_line: list[dict],
    runs: int = 1,
    structure_mat_saving: float = 1.0,
) -> list[dict]:
    """各并行线的单轮材料明细按 `type_id` 合并（qty 求和、subtotal 重算）。

    供 `material_requirements` 这类**要求精确**的消费方：结果配套乘 `runs`
    （**不再**乘 `parallels`，因为各线已经在这里加总过了）。

    每条另带 `total_qty`（各线**整批取整**后的合计）。EVE 里每条并行线是**独立作业**、
    各带自己的 ME，所以必须**逐线** `ceil(基础量 × runs × (100-ME_i)/100 × 减免)` 再求和；
    先把各线基础量加总、再取一次整会**少要货**。
    """
    merged: dict[int, dict] = {}
    for result in per_line:
        line_me = int((result.get("breakdown") or {}).get("bp_me") or 0)
        for mat in result.get("materials", []) or []:
            tid = mat.get("type_id")
            if not tid:
                continue
            batch = material_total_for_runs(mat, runs, me_level=line_me, structure_mat_saving=structure_mat_saving)
            if tid in merged:
                row = merged[tid]
                row["qty"] = (row.get("qty") or 0) + (mat.get("qty") or 0)
                row["total_qty"] = (row.get("total_qty") or 0) + batch
                row["subtotal"] = round((row.get("unit_price") or 0) * row["qty"], 2)
            else:
                merged[tid] = {**mat, "total_qty": batch}
    return list(merged.values())


def _batch_materials(materials: list[dict], total_runs: int, me_level: int, saving: float) -> list[dict]:
    """给材料明细列表加一份 `total_qty`（整批取整），**返回新列表**。

    必须是新列表、新条目：`per_run["materials"]` 与评分缓存是**同一个对象**
    （`scoring_facade` 的 cache key 不含 runs），就地写会把 `total_qty` 灌进缓存，
    让不同 runs 的计划互相串值。
    """
    return [
        {**mat, "total_qty": material_total_for_runs(mat, total_runs, me_level=me_level, structure_mat_saving=saving)}
        for mat in materials or []
    ]


def _default_db() -> DatabaseManager:
    """惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。"""
    return get_container().db


# ════════════════════════════════════════════════════════════════════
#  评分结果缓存 — 30 分钟 TTL，有界 LRU 淘汰（线程安全）
#  统一使用 core.cache.TtlLRUCache（容器注入与模块级共用同一实现）
# ════════════════════════════════════════════════════════════════════


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


# 模块级缓存函数（委托给默认实例）


def invalidate_cache():
    """清空模块级研究成本缓存（价格刷新后调用）。

    评分结果缓存走 ScoringService 实例（容器注入），由实例的 invalidate_cache 清理；
    此处只负责模块级 _research_cost_cache，避免两套缓存失效遗漏。
    """
    _clear_research_cost_cache()


# ════════════════════════════════════════════════════════════════════
#  定价查询（模块级 + ScoringService 实例方法共享）
# ════════════════════════════════════════════════════════════════════


# 取价的**单一定义处**在 `services/repositories/market_repository.py`；
# 这里保留同名模块级函数是为了维持既有调用方与测试的 patch 语义
# （`@patch("services.scoring_service.get_price")`，见 tests/test_scoring_service.py）。
# 合并前两处各有一份等价 SQL（原 `pricing_service.py` 的 docstring 记着
# 「改价需两边同步」—— 这个分裂已实际致过缓存串值缺陷）。
def get_price(
    type_id: int,
    price_type: str,
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> float | None:
    """从 market_prices 获取指定区域的价格。price_type: 'buy' / 'sell'。"""
    return MarketRepository(_db or _default_db()).get_price(type_id, price_type, hub)


def get_volume(
    type_id: int,
    vol_type: str = "total",
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> int:
    """获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'"""
    return MarketRepository(_db or _default_db()).get_volume(type_id, vol_type, hub)


def get_system_cost_index(
    system_id: int | None,
    activity: str = "manufacturing",
    _db: DatabaseManager | None = None,
    hub: str = "Jita",
) -> float:
    """星系的制造成本指数。system_id=None 时从 hub 推断。"""
    # 注意参数顺序：本函数的 `_db` 在第三个（历史签名，调用方按位置传），
    # 而 MarketRepository 的签名是 (system_id, activity, hub) —— 必须走关键字。
    return MarketRepository(_db or _default_db()).get_system_cost_index(system_id, activity, hub=hub)


def get_adjusted_price(
    type_id: int,
    _db: DatabaseManager | None = None,
) -> float | None:
    """获取 ESI adjusted price（EIV 计算用）。兜底 None → 用 sell_price。"""
    return MarketRepository(_db or _default_db()).get_adjusted_price(type_id)


# 研究成本进程内缓存（type_id|solar_system_id → cost|None）— 价格刷新时由 invalidate_cache 一并清空
_research_cost_cache = TtlLRUCache(max_size=2000, ttl_seconds=3600)
_RESEARCH_MISS = object()


def _research_cost_cached(_db: DatabaseManager, type_id: int, *, solar_system_id: int | None = None) -> float:
    """按 type_id + 设施星系计算研究成本（拷贝/发明），带进程内缓存；失败返回 0。

    SCI 按设施星系 solar_system_id 查询；None → research_calculator 内部回落默认科研机库星系。
    """
    key = f"{type_id}|{solar_system_id}"
    cached = _research_cost_cache.get(key)
    if cached is not None:
        return 0.0 if cached is _RESEARCH_MISS else float(cached)
    try:
        from services.research_calculator import research_cost_for_item

        with _db.connect("bp") as conn:
            cost = research_cost_for_item(conn, type_id, solar_system_id=solar_system_id)
        if cost is None:
            _research_cost_cache.set(key, _RESEARCH_MISS)
            return 0.0
        _research_cost_cache.set(key, cost)
        return float(cost)
    except Exception:
        _research_cost_cache.set(key, _RESEARCH_MISS)
        return 0.0


def _clear_research_cost_cache() -> None:
    """清空研究成本缓存（价格刷新时调用）。"""
    _research_cost_cache.invalidate()


# ════════════════════════════════════════════════════════════════════
#  科研作业辅助（拷贝/发明/研究的返回值组装）
# ════════════════════════════════════════════════════════════════════


def _empty_plan_metrics() -> dict:
    """计划指标的零值骨架（键与制造路径一致，供失败分支直接返回）。"""
    return {
        "material_cost": 0,
        "profit": 0,
        "margin": 0,
        "score": 0,
        "iskph": 0,
        "calculated_time": 0,
        "daily_output": 0,
        "revenue": 0,
        "fees": 0,
        "materials": [],
        "revenue_per_run": 0,
        "fees_per_run": 0,
    }


def _resolve_blueprint_for_product(db, product_type_id) -> int:
    """按产物 type_id 反查它的制造蓝图（旧计划行只带 product_type_id 时用）。缺失 → 0。"""
    if not product_type_id:
        return 0
    try:
        with db.connect("bp") as conn:
            row = conn.execute(
                "SELECT blueprint_type_id FROM blueprint_products "
                "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                (int(product_type_id),),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        from core.logger import log

        log.debug("反查蓝图失败 product=%s", product_type_id, exc_info=True)
        return 0


def materials_with_names(db, mats: list[tuple[int, int]], prices: dict[int, float]) -> list[dict]:
    """[(type_id, qty)] + 单价 → [{type_id, name, qty, unit_price}]（供个人利润率/明细展示）。

    名称批量解析（一次查询），不在循环里逐个查库。
    """
    pairs = [(int(mid), int(qty)) for mid, qty in mats if mid]
    if not pairs:
        return []
    names: dict[int, str] = {}
    try:
        from services.name_resolver import resolve_item_names_batch

        with db.connect("ref") as conn:
            names = resolve_item_names_batch(conn, [mid for mid, _q in pairs])
    except Exception:
        from core.logger import log

        log.debug("科研材料名称解析失败", exc_info=True)
    return [
        {
            "type_id": mid,
            "name": names.get(mid, str(mid)),
            "qty": qty,
            "unit_price": float(prices.get(mid, 0.0)),
        }
        for mid, qty in pairs
    ]


# ════════════════════════════════════════════════════════════════════
#  ScoringService — 可注入的评分服务类
# ════════════════════════════════════════════════════════════════════


class ScoringService:
    def __init__(self, db: DatabaseManager, cache: TtlLRUCache, char_config: dict | None = None):
        self._db = db
        self._cache = cache
        self._char_config = char_config or {}

    def invalidate_cache(self) -> None:
        """清空评分缓存（价格刷新后调用，避免旧价格评分被复用）"""
        _clear_research_cost_cache()
        if self._cache:
            self._cache.invalidate()

    # ── 经纪人费率计算（去重：制造/贸易共用） ──

    def _calc_broker_rate(self, skills: dict, market_data: dict) -> float:
        return calc_broker_rate(skills, market_data)

    def _calc_relist_discount(self, skills: dict) -> float:
        return calc_relist_discount(skills)

    def _calc_sales_tax_rate(self, skills: dict) -> float:
        return calc_sales_tax_rate(skills)

    # ── runs/parallels 总数值辅助计算 ──

    @staticmethod
    def calculate_total_metrics(
        per_run: dict,
        runs: int = 1,
        parallels: int = 1,
    ) -> dict:
        """将 per-run 评分结果按 runs/parallels 缩放到计划总数值。

        Args:
            per_run: calc_manufacturing_score() 的返回 dict（含 profit_per_run 等）
            runs: 流程数
            parallels: 并行数

        Returns:
            更新后的 dict，包含 total_ 前缀的总数值字段。
        """
        total_mult = max(runs, 1) * max(parallels, 1)
        runs_only = max(runs, 1)
        hours_per_run = per_run.get("hours_per_run", 0) or 1
        profit_per_run = per_run.get("profit_per_run", 0) or 0
        breakdown = per_run.get("breakdown") or {}
        mat_cost = breakdown.get("material_cost", 0) or 0
        revenue_per_run = per_run.get("revenue_per_run", 0) or 0

        # 材料按**整批**取整（见 domain.formulas.material_total_for_runs）。
        # 旧口径是「单轮取整 × 总倍数」，对基础量 ≥2 的材料系统性多要货。
        materials = _batch_materials(
            per_run.get("materials") or [],
            total_mult,
            int(breakdown.get("bp_me") or 0),
            float(breakdown.get("structure_mat_saving") or 1.0),
        )
        total_mat_cost = sum((m.get("total_qty") or 0) * (m.get("unit_price") or 0) for m in materials)

        # 利润用**增量式**重算：只把材料省下的那部分加回去。
        # 不能自己拼 `total_cost = 材料 + 费用` —— `fees_per_run` 里**没有** research_cost，
        # 那是在 `domain/scoring.py:165` 才加进 total_cost 的，自己拼会让 T2/T3
        # （拷贝/发明）计划的利润虚高 `research_cost × 倍数`。
        total_profit = profit_per_run * total_mult + (mat_cost * total_mult - total_mat_cost)
        total_time_hours = hours_per_run * runs_only
        total_iskph = total_profit / total_time_hours if total_time_hours > 0 else 0
        daily_output = (24.0 / hours_per_run) * parallels if hours_per_run > 0 else 0

        # 利润率随材料口径一起重算。以前「比值不变」是因为各项都线性；
        # 材料不再线性，再沿用单轮 margin 就会与新的利润对不上。
        total_revenue = revenue_per_run * total_mult
        total_cost = total_revenue - total_profit
        total_margin = total_profit / total_cost * 100 if total_cost > 0 else 0.0

        # 保留原始 per_run 字段 + 新增 total_ 字段
        result = dict(per_run)
        result["materials"] = materials
        result.update(
            {
                "total_material_cost": round(total_mat_cost, 2),
                "total_profit": round(total_profit, 2),
                "total_time_hours": round(total_time_hours, 2),
                "total_isk_per_hour": round(total_iskph, 2),
                "total_daily_output": round(daily_output, 1),
                "total_margin_pct": round(total_margin, 2),
            }
        )
        return result

    # ── 逐线汇总（并行产线各按自己绑定蓝图的 ME/TE 结算）──

    @staticmethod
    def combine_per_line(per_line: list[dict], runs: int = 1) -> tuple[dict, dict]:
        """逐线结果 → 计划级 ``(per_run, total)``。

        并行产线**同时开跑**，故：

        - 材料 / 作业费 / 收入 / 利润 → **Σ 各线**
        - 生产时长 → **max**（取最慢那条；单次路径的 `hours_per_run × runs` 是其均匀特例）
        - 日产出 → Σ(24 / hours_i)
        - 利润率 → Σ利润 / Σ总成本（与单线的 ``profit / total_cost`` 同式，均匀时等价）

        ``per_run`` 刻意保持「**单线单轮**」语义（取**最差线**），并额外带一份
        ``materials_all_lines``（Σ 各线单轮量）：`materials` / `revenue_per_run` /
        `fees_per_run` 的既有消费方都会再乘 `runs × parallels`，这里若放汇总值会被**重复放大**。
        """
        runs = max(int(runs or 1), 1)
        worst = min(per_line, key=lambda r: r.get("profit_per_run", 0) or 0)
        hours = [float(r.get("hours_per_run", 0) or 0) for r in per_line]
        max_hours = max(hours) if hours else 0.0

        structure_saving = float((worst.get("breakdown") or {}).get("structure_mat_saving") or 1.0)
        # 各线**各自整批取整**后求和（每条并行线是独立作业、各带自己的 ME）
        materials_all_lines = _sum_materials(per_line, runs, structure_saving)
        old_mat = sum(float((r.get("breakdown") or {}).get("material_cost", 0) or 0) for r in per_line) * runs
        total_mat = sum((m.get("total_qty") or 0) * (m.get("unit_price") or 0) for m in materials_all_lines)

        total_revenue = sum((r.get("revenue_per_run", 0) or 0) for r in per_line) * runs
        total_fees = sum((r.get("fees_per_run", 0) or 0) for r in per_line) * runs
        # 同样走**增量式**：只把材料省下的部分加回去，其余项（含 research_cost）自动保留
        total_profit = sum((r.get("profit_per_run", 0) or 0) for r in per_line) * runs + (old_mat - total_mat)
        total_hours = max_hours * runs
        # domain 里 profit = revenue - total_cost（total_cost 含材料 + 安装费 + 经纪/改单/销售税）
        total_cost = total_revenue - total_profit

        per_run = dict(worst)
        per_run["materials_all_lines"] = materials_all_lines
        # `materials`（最差线单轮）也补 `total_qty`，与既有消费方 `runs × parallels` 的倍数保持同口径
        per_run["materials"] = _batch_materials(
            per_run.get("materials") or [],
            runs * max(len(per_line), 1),
            int((worst.get("breakdown") or {}).get("bp_me") or 0),
            structure_saving,
        )
        total = {
            "total_material_cost": round(total_mat, 2),
            "total_profit": round(total_profit, 2),
            "total_revenue": round(total_revenue, 2),
            "total_fees": round(total_fees, 2),
            "total_time_hours": round(total_hours, 2),
            "total_isk_per_hour": round(total_profit / total_hours, 2) if total_hours > 0 else 0.0,
            "total_daily_output": round(sum(24.0 / h for h in hours if h > 0), 1),
            "total_margin_pct": round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0.0,
        }
        return per_run, total

    # ── 统一计划计算方法 ──

    @staticmethod
    def calculate_plan_metrics(
        plan_data: dict,
        char_config: dict,
        *,
        mat_hub: str | None = None,
        sell_hub: str | None = None,
        price_type_mat: str | None = None,
        price_type_prod: str | None = None,
        system_id: int | None = None,
        mat_mult: float = 1.0,
        prod_mult: float = 1.0,
    ) -> dict:
        """从一条生产计划数据计算所有派生指标。

        统一所有计算路径的参数决议逻辑，确保结果一致。

        参数优先级：显式传入 override > plan_data 字段值 > 材料机库所在星系 > sell_hub 推断（默认 Jita）。

        Args:
            plan_data: 生产计划 dict（至少含 product_type_id, me_level, te_level, runs, parallels）
            char_config: 角色配置（含 skills, market 等）
            mat_hub: 覆盖材料贸易枢纽（不传则用 plan_data 的 mat_hub，为空则用 Jita）
            sell_hub: 覆盖销售枢纽（不传则用 plan_data 的 sell_hub，为空则用 Jita）
            price_type_mat: 覆盖材料价格类型（不传则用 plan_data 的或 "sell"）
            price_type_prod: 覆盖成品价格类型（不传则用 plan_data 的或 "sell"）
            mat_mult: 材料价格调整系数（工具栏「材料倍率」）
            prod_mult: 成品价格调整系数（工具栏「成品倍率」）

        Returns:
            dict 包含：material_cost, profit, margin, score, iskph, calculated_time(秒), daily_output，
            以及个人利润率输入 revenue/fees/materials/revenue_per_run/fees_per_run
        """
        type_id = plan_data.get("product_type_id")
        if not type_id:
            return {
                "material_cost": 0,
                "profit": 0,
                "margin": 0,
                "score": 0,
                "iskph": 0,
                "calculated_time": 0,
                "daily_output": 0,
                "revenue": 0,
                "fees": 0,
                "materials": [],
                "revenue_per_run": 0,
                "fees_per_run": 0,
            }

        me = int(plan_data.get("me_level", 0) or 0)
        te = int(plan_data.get("te_level", 0) or 0)
        runs = max(int(plan_data.get("runs", 1)), 1)
        parallels = max(int(plan_data.get("parallels", 1)), 1)

        # 统一的参数决议：传入 > plan 字段 > 默认值
        resolved_mat_hub = mat_hub or plan_data.get("mat_hub") or "Jita"
        resolved_sell_hub = sell_hub or plan_data.get("sell_hub") or "Jita"
        resolved_price_type_mat = price_type_mat or "sell"
        resolved_price_type_prod = price_type_prod or "sell"
        # 星系：显式 override > 计划快照 > 材料机库所在星系 > sell_hub 推断（默认 Jita）
        resolved_system_id = system_id if system_id is not None else plan_data.get("solar_system_id")

        from core.container import get_container

        svc = get_container().scoring_service()
        if resolved_system_id is None:
            # 快照为空时从材料机库带出星系（与下方结构加成解析对称）
            from services.inventory_manager import get_hangar_system_id

            resolved_system_id = get_hangar_system_id(plan_data.get("mat_hangar_id"), _db=getattr(svc, "_db", None))
        # 仍为 None → calc_manufacturing_score 内部按 sell_hub 推断；此处算出实际生效星系供展示
        effective_system_id = (
            resolved_system_id if resolved_system_id is not None else _hub_to_system_id(resolved_sell_hub)
        )
        # 机库工业配置解析（材料机库决定设施类型/改件/税；用 svc._db 保证测试隔离）
        from domain.formulas import FACILITY_TAX_NPC
        from services.hangar_industry_config import resolve_hangar_industry_config

        hangar_cfg = resolve_hangar_industry_config(plan_data.get("mat_hangar_id"), _db=getattr(svc, "_db", None))
        # 成本倍率：计划 facility_cost_mult 显式(≠1.0) > 机库 > 1.0
        plan_mult = float(plan_data.get("facility_cost_mult", 1.0) or 1.0)
        structure_cost_mult = plan_mult if plan_mult != 1.0 else hangar_cfg["structure_cost_mult"]
        structure_bonus = structure_cost_mult - 1.0
        structure_time_mod = hangar_cfg["structure_time_mod"]
        structure_mat_saving = hangar_cfg["structure_mat_saving"]
        # 设施税（%）：计划显式 > 机库 > char_config > NPC 0.25%
        plan_tax = plan_data.get("facility_tax")
        hub_mkt = char_config.get("market", {}).get(resolved_sell_hub.lower(), {})
        if plan_tax is not None:
            fac_tax = plan_tax
        elif hangar_cfg["facility_tax"] is not None:
            fac_tax = hangar_cfg["facility_tax"]
        elif hub_mkt:
            fac_tax = hub_mkt.get("facility_tax", 0.0)
        else:
            fac_tax = FACILITY_TAX_NPC * 100

        per_run: dict = {}
        total: dict = {}
        try:
            # 科研作业（拷贝/发明/研究）走独立分支：产物是蓝图而非制造品，
            # 材料不吃 ME、作业次数口径也不同，不能复用制造评分链路。
            from domain.research import SCIENCE_ACTIVITIES

            activity = str(plan_data.get("activity") or "manufacturing")
            if activity in SCIENCE_ACTIVITIES:
                return ScoringService._calculate_research_metrics(
                    plan_data,
                    char_config,
                    activity=activity,
                    mat_hub=resolved_mat_hub,
                    sell_hub=resolved_sell_hub,
                    price_type_mat=resolved_price_type_mat,
                    price_type_prod=resolved_price_type_prod,
                    system_id=resolved_system_id,
                    effective_system_id=effective_system_id,
                    structure_cost_mult=structure_cost_mult,
                    structure_time_mod=structure_time_mod,
                    fac_tax=fac_tax,
                    runs=runs,
                    parallels=parallels,
                )
            per_run = svc.calc_manufacturing_score(
                type_id=type_id,
                char_config=char_config,
                bp_me=me,
                bp_te=te,
                mat_source_hub=resolved_mat_hub,
                sell_hub=resolved_sell_hub,
                facility_tax_pct=fac_tax,
                price_type_mat=resolved_price_type_mat,
                price_type_prod=resolved_price_type_prod,
                structure_bonus=structure_bonus,
                structure_time_mod=structure_time_mod,
                structure_mat_saving=structure_mat_saving,
                system_id=resolved_system_id,
                mat_price_mult=mat_mult,
                prod_price_mult=prod_mult,
            )
            total = ScoringService.calculate_total_metrics(per_run, runs, parallels) or {}

            # 逐线：各并行产线按**各自绑定蓝图**的 ME/TE 独立结算。
            # 短路条件是「与**计划级**完全一致」——不是「各线彼此一致」：
            # 绑的 5 张都是 ME8、而计划级写着 10 时也必须走逐线，否则改绑等级不生效。
            line_levels = [(int(a), int(b)) for a, b in (plan_data.get("line_levels") or [])]
            if any(pair != (me, te) for pair in line_levels):
                per_line = [
                    svc.calc_manufacturing_score(
                        type_id=type_id,
                        char_config=char_config,
                        bp_me=line_me,
                        bp_te=line_te,
                        mat_source_hub=resolved_mat_hub,
                        sell_hub=resolved_sell_hub,
                        facility_tax_pct=fac_tax,
                        price_type_mat=resolved_price_type_mat,
                        price_type_prod=resolved_price_type_prod,
                        structure_bonus=structure_bonus,
                        structure_time_mod=structure_time_mod,
                        structure_mat_saving=structure_mat_saving,
                        system_id=resolved_system_id,
                        mat_price_mult=mat_mult,
                        prod_price_mult=prod_mult,
                    )
                    for line_me, line_te in line_levels
                ]
                per_run, total = ScoringService.combine_per_line(per_line, runs)
            else:
                per_run = svc.calc_manufacturing_score(
                    type_id=type_id,
                    char_config=char_config,
                    bp_me=me,
                    bp_te=te,
                    mat_source_hub=resolved_mat_hub,
                    sell_hub=resolved_sell_hub,
                    facility_tax_pct=fac_tax,
                    price_type_mat=resolved_price_type_mat,
                    price_type_prod=resolved_price_type_prod,
                    structure_bonus=structure_bonus,
                    structure_time_mod=structure_time_mod,
                    structure_mat_saving=structure_mat_saving,
                    system_id=resolved_system_id,
                    mat_price_mult=mat_mult,
                    prod_price_mult=prod_mult,
                )
                total = ScoringService.calculate_total_metrics(per_run, runs, parallels) or {}
        except Exception:
            from core.logger import log

            log.exception(
                "计划评分计算失败 type_id=%s me=%s te=%s",
                type_id,
                me,
                te,
            )

        revenue_per_run = per_run.get("revenue_per_run", 0) or 0
        fees_per_run = per_run.get("fees_per_run", 0) or 0
        total_mult = runs * parallels
        # 逐线时 `total` 已带**总**收入/费用（Σ 各线 × runs）；单次路径没有这两个键，
        # 回退既有的 `单线单轮 × runs × parallels`（逐值不变）。
        total_revenue = total.get("total_revenue")
        total_fees = total.get("total_fees")

        return {
            "material_cost": round(total.get("total_material_cost", 0), 2),
            "profit": round(total.get("total_profit", 0), 2),
            "margin": round(total.get("total_margin_pct", 0), 2),
            "score": per_run.get("score", 0),
            "iskph": round(total.get("total_isk_per_hour", 0), 2),
            "calculated_time": round(total.get("total_time_hours", 0) * 3600),
            "daily_output": round(total.get("total_daily_output", 0), 1),
            # ── 个人利润率输入（新增）──
            "revenue": round(total_revenue if total_revenue is not None else revenue_per_run * total_mult, 2),
            "fees": round(total_fees if total_fees is not None else fees_per_run * total_mult, 2),
            # 每轮量（含 ME 单件豁免）**外加** `total_qty`（整批取整后的量）。
            # `qty` 语义与取值一律不变 —— 既有消费方仍乘 runs×parallels；
            # 要求精确的消费方改读 `total_qty`（缺失时才回退旧乘法）。
            "materials": total.get("materials") or per_run.get("materials", []),
            # 仅供 `material_requirements` 这类**要求精确**的消费方：
            # 各并行线的单轮量之和，以及逐线各自整批取整后再求和的 `total_qty`。
            "materials_all_lines": per_run.get("materials_all_lines"),
            "revenue_per_run": revenue_per_run,  # 未取整，供精确计算
            "fees_per_run": fees_per_run,
            "structure_mat_saving": round(structure_mat_saving, 4),
            "structure_time_mod": round(structure_time_mod, 4),
            "structure_cost_mult": round(structure_cost_mult, 4),
            "facility_tax_pct": round(fac_tax, 3),
            "solar_system_id": effective_system_id,
            "status": per_run.get("status", ""),
            "breakdown": per_run.get("breakdown", {}),
        }

    # ── 科研作业（拷贝 / 发明 / ME-TE 研究）──

    @staticmethod
    def _research_skill_levels(conn, blueprint_type_id: int, activity: str, skills: dict) -> tuple[int, int, int, str]:
        """从 blueprint_skills 解析该活动的技能要求并读角色等级。

        发明成功率需要「两个科学技能 + 一个加密技术原理」：
        名称含「加密技术原理」/`Encryption Methods` 的归加密，其余按 type_id 升序取前两个。

        Returns: (科学1等级, 科学2等级, 加密等级, 说明文本)
        """
        rows = conn.execute(
            "SELECT bs.skill_type_id, i.zh_name, i.en_name FROM blueprint_skills bs "
            "LEFT JOIN ref.item i ON i.type_id = bs.skill_type_id "
            "WHERE bs.blueprint_type_id = ? AND bs.activity = ? ORDER BY bs.skill_type_id",
            (blueprint_type_id, activity),
        ).fetchall()
        science: list[tuple[int, str]] = []
        encryption: tuple[int, str] | None = None
        for sid, zh, en in rows:
            name = zh or en or str(sid)
            if "加密技术原理" in name or "Encryption" in (en or ""):
                if encryption is None:
                    encryption = (int(sid), name)
            else:
                science.append((int(sid), name))

        def _lv(name: str) -> int:
            return int(skills.get(name, 0) or 0)

        s1 = _lv(science[0][1]) if len(science) > 0 else 0
        s2 = _lv(science[1][1]) if len(science) > 1 else 0
        enc = _lv(encryption[1]) if encryption else 0
        parts = []
        if len(science) > 0:
            parts.append(f"{science[0][1]} L{s1}")
        if len(science) > 1:
            parts.append(f"{science[1][1]} L{s2}")
        if encryption:
            parts.append(f"{encryption[1]} L{enc}")
        return s1, s2, enc, " / ".join(parts)

    @staticmethod
    def _calculate_research_metrics(
        plan_data: dict,
        char_config: dict,
        *,
        activity: str,
        mat_hub: str,
        sell_hub: str,
        price_type_mat: str,
        price_type_prod: str,
        system_id: int | None,
        effective_system_id: int | None,
        structure_cost_mult: float,
        structure_time_mod: float,
        fac_tax: float,
        runs: int,
        parallels: int,
    ) -> dict:
        """拷贝/发明/研究作业的指标（编排：查蓝图/SDE → 调 services.plan_metrics 纯函数）。

        与制造的关键差异（见 services.plan_job_kinds 的活动契约）：
        - 产物是**蓝图**（product_type_id = 蓝图 type_id），不是制造品；
        - 材料不吃 ME；安装费 SCI 按本活动取；
        - 「作业次数」口径：发明 = 尝试次数、拷贝 = 总授权流程、研究 = 目标等级。

        plan_data 字段约定:
            product_type_id    本计划产物（科研恒为蓝图 type_id）
            blueprint_type_id  输入蓝图（发明 = T1 蓝图；拷贝/研究 = 同一张蓝图）
            runs               发明 = 每线尝试次数 / 拷贝 = 每份拷贝流程 / 研究 = 目标等级
            parallels          发明 = 并行作业数（总尝试 = runs × parallels）/
                               拷贝 = 产出份数（其余按 1 计）
            decryptor_type_id / success_rate / actual_output_runs  仅发明使用
        """
        from core.container import get_container
        from core.logger import log
        from domain.research import (
            ACTIVITY_COPYING,
            ACTIVITY_INVENTION,
            MATERIAL_ACTIVITY,
            METALLURGY_TIME_SKILL,
            RESEARCH_TIME_SKILL,
            SCIENCE_TIME_SKILL,
            copy_job_runs,
            get_decryptor,
            science_job_time,
        )
        from services.plan_metrics import (
            copying_plan_cost,
            invention_plan_cost,
            research_plan_cost,
        )

        empty = _empty_plan_metrics()
        db = get_container().db
        # 本计划的蓝图 = 输入/产出蓝图，两者对科研是同一张：
        #   拷贝/研究 → 被拷贝/被研究的 BPO；发明 → 被发明的 T2 蓝图（T1 由它反查）。
        # blueprint_type_id 缺失时按 product_type_id 反查制造蓝图（沿用旧计划行的口径）。
        blueprint_type_id = int(plan_data.get("blueprint_type_id") or 0)
        if not blueprint_type_id:
            blueprint_type_id = _resolve_blueprint_for_product(db, plan_data.get("product_type_id"))
        if not blueprint_type_id:
            empty["status"] = "no_blueprint"
            return empty

        skills = (char_config or {}).get("skills", {}) or {}
        decryptor = get_decryptor(plan_data.get("decryptor_type_id")) if activity == ACTIVITY_INVENTION else None

        bp_materials: list[tuple[int, int]] = []
        base_time = 0
        max_production_limit = 0
        base_probability = 0.0
        input_bp_type_id = blueprint_type_id
        s1 = s2 = enc = 0
        skill_note = ""

        with db.connect("bp", "ref") as conn:
            mat_act = MATERIAL_ACTIVITY.get(activity, activity)
            bp_materials = [
                (int(r[0]), int(r[1] or 0))
                for r in conn.execute(
                    "SELECT material_type_id, quantity FROM blueprint_materials "
                    "WHERE blueprint_type_id = ? AND activity = ?",
                    (blueprint_type_id, mat_act),
                ).fetchall()
            ]
            # 注意连接启用了 sqlite3.Row：不能元组解包，须按索引取
            # blueprint_activities 的活动名：copying / invention / researching_material_efficiency …
            # 旧数据里研究活动可能写作 research_material / research_time，做一次回退。
            _act_name = activity
            _act_row = conn.execute(
                "SELECT time, max_production_limit FROM blueprint_activities "
                "WHERE blueprint_type_id = ? AND activity = ? LIMIT 1",
                (blueprint_type_id, _act_name),
            ).fetchone()
            if _act_row is None and activity in MATERIAL_ACTIVITY:
                _act_row = conn.execute(
                    "SELECT time, max_production_limit FROM blueprint_activities "
                    "WHERE blueprint_type_id = ? AND activity = ? LIMIT 1",
                    (blueprint_type_id, MATERIAL_ACTIVITY[activity]),
                ).fetchone()
            base_time = int(_act_row[0] or 0) if _act_row else 0
            max_production_limit = int(_act_row[1] or 0) if _act_row else 0
            if activity == ACTIVITY_INVENTION:
                inv = conn.execute(
                    "SELECT blueprint_type_id, probability FROM blueprint_products "
                    "WHERE activity = 'invention' AND product_type_id = ? LIMIT 1",
                    (blueprint_type_id,),
                ).fetchone()
                if not inv:
                    empty["status"] = "no_blueprint"
                    return empty
                # 发明作业跑在**输入**（T1）蓝图上：基础时长/产出上限取自它，不是产物那张蓝图
                ans = conn.execute(
                    "SELECT time, max_production_limit FROM blueprint_activities "
                    "WHERE blueprint_type_id = ? AND activity = 'invention' LIMIT 1",
                    (int(inv[0]),),
                ).fetchone()
                if ans:
                    base_time = int(ans[0] or 0)
                    max_production_limit = int(ans[1] or 0)
                input_bp_type_id, base_probability = int(inv[0]), float(inv[1] or 0.0)
                # 数据核心来自 T1 蓝图的 invention 行
                bp_materials = [
                    (int(r[0]), int(r[1] or 0))
                    for r in conn.execute(
                        "SELECT material_type_id, quantity FROM blueprint_materials "
                        "WHERE blueprint_type_id = ? AND activity = 'invention'",
                        (input_bp_type_id,),
                    ).fetchall()
                ]
                # 产出 BPC 基础流程数 = SDE invention 行的 quantity（唯一口径，
                # 与 services.research_plans.invention_base_runs 同源）
                from services.research_plans import invention_base_runs

                max_production_limit = invention_base_runs(conn, blueprint_type_id, input_bp_type_id)
                s1, s2, enc, skill_note = ScoringService._research_skill_levels(
                    conn, input_bp_type_id, "invention", skills
                )

        # 材料单价：adjusted_price 优先（0/缺失 → sell_price）
        prices: dict[int, float] = {}
        mat_ids = {mid for mid, _q in bp_materials if mid}
        if decryptor:
            mat_ids.add(decryptor.type_id)
        if mat_ids:
            with db.connect("mkt") as conn:
                for mid in mat_ids:
                    row = conn.execute(
                        "SELECT adjusted_price, sell_price, buy_price FROM market_prices "
                        "WHERE type_id = ? ORDER BY (adjusted_price > 0) DESC, fetch_time DESC LIMIT 1",
                        (mid,),
                    ).fetchone()
                    if row:
                        prices[mid] = float(row[0] or 0) or float(row[1] or 0) or float(row[2] or 0)

        sci = 0.0
        try:
            sci = float(get_system_cost_index(system_id, activity, _db=db, hub=sell_hub) or 0.0)
        except Exception:
            log.debug("取 SCI 失败 activity=%s system=%s", activity, system_id, exc_info=True)

        structure_mult = max(0.0, float(structure_cost_mult or 1.0))
        facility_tax = float(fac_tax) / 100.0  # plan_metrics 收小数口径

        if activity == ACTIVITY_INVENTION:
            base_runs = max(1, max_production_limit)
            # 总尝试 = 每线尝试次数 × 并行作业数。与执行侧扣料口径一致：
            # plan_execution 为每条绑定产线消耗 runs 个 T1 流程，共 parallels 条线。
            total_attempts = max(1, runs) * max(1, parallels)
            cost = invention_plan_cost(
                base_probability=base_probability,
                materials=bp_materials,
                prices=prices,
                sci=sci,
                science_skill_1=s1,
                science_skill_2=s2,
                encryption_skill=enc,
                decryptor=decryptor,
                base_runs=base_runs,
                attempts_override=total_attempts,
                input_bpc_cost_per_run=float(plan_data.get("input_bpc_cost_per_run") or 0.0),
                success_rate_override=plan_data.get("success_rate"),
                actual_output_runs=plan_data.get("actual_output_runs"),
                structure_mult=structure_mult,
                facility_tax=facility_tax,
            )
            # 墙钟 = 每线 runs 次串行 × 单次时长；并行线同时跑，不乘 parallels
            job_k = max(1, runs)
            output_runs = int(cost["output_runs"])
            extra = {
                "success_rate": cost["success_rate"],
                "attempts": cost["attempts"],
                "runs_per_bpc": cost["runs_per_bpc"],
                "bpc_unit_cost": cost["bpc_unit_cost"],
                "output_runs": output_runs,
                "expected_runs": cost["expected_runs"],
                "is_actual": cost["is_actual"],
                "base_probability": round(base_probability, 4),
                "skills": skill_note,
                "decryptor": decryptor.name if decryptor else "",
            }
        elif activity == ACTIVITY_COPYING:
            copies = max(1, parallels)
            total_runs = copy_job_runs(copies, runs, max_production_limit)
            cost = copying_plan_cost(
                materials=bp_materials,
                prices=prices,
                sci=sci,
                total_copy_runs=total_runs,
                copies=copies,
                structure_mult=structure_mult,
                facility_tax=facility_tax,
            )
            job_k = total_runs
            output_runs = total_runs
            extra = {
                "copies": copies,
                "runs_per_copy": cost["runs_per_copy"],
                "per_copy_cost": cost["per_copy_cost"],
                "max_production_limit": max_production_limit,
            }
        else:  # ME/TE 研究
            target_level = max(1, runs)
            cost = research_plan_cost(
                materials=bp_materials,
                prices=prices,
                sci=sci,
                target_level=target_level,
                structure_mult=structure_mult,
                facility_tax=facility_tax,
            )
            job_k = target_level
            output_runs = 1
            extra = {"target_level": target_level, "time_is_approximate": True}

        time_per_job = science_job_time(
            base_time,
            activity=activity,
            research_skill=int(skills.get(RESEARCH_TIME_SKILL, 0) or 0),
            metallurgy_skill=int(skills.get(METALLURGY_TIME_SKILL, 0) or 0),
            science_skill=int(skills.get(SCIENCE_TIME_SKILL, 0) or 0),
            te_level=int(plan_data.get("te_level", 0) or 0),
            structure_time_mod=structure_time_mod,
        )
        total_seconds = time_per_job * job_k

        # 收入：产物（蓝图）市价 × 产出件数（拷贝一次产出 copies 份 BPC）
        product_id = int(plan_data.get("product_type_id") or 0)
        product_price = 0.0
        if product_id:
            with db.connect("mkt") as conn:
                row = conn.execute(
                    "SELECT sell_price, buy_price FROM market_prices WHERE type_id = ? LIMIT 1",
                    (product_id,),
                ).fetchone()
                if row:
                    product_price = float(row[0] or 0) or float(row[1] or 0)
        revenue = product_price * output_runs

        material_cost = float(cost.get("material_cost", cost.get("total_material_cost", 0.0)))
        fee = float(cost.get("fee", cost.get("total_fee", 0.0)))
        input_bpc_cost = float(cost.get("input_bpc_cost", 0.0))
        total_cost = material_cost + fee + input_bpc_cost
        profit = revenue - total_cost
        margin = (profit / total_cost * 100) if total_cost > 0 else 0.0
        hours_per_job = (time_per_job / 3600) if time_per_job else 0.0

        return {
            "material_cost": round(material_cost, 2),
            "profit": round(profit, 2),
            "margin": round(margin, 2),
            "score": 0.0,
            "iskph": round(profit / (total_seconds / 3600), 2) if total_seconds > 0 else 0.0,
            "calculated_time": round(total_seconds),
            "daily_output": round((24.0 / hours_per_job) if hours_per_job > 0 else 0.0, 1),
            "revenue": round(revenue, 2),
            "fees": round(fee, 2),
            "materials": materials_with_names(db, cost.get("materials", []), prices),
            "revenue_per_run": round(revenue, 2),
            "fees_per_run": fee,
            "structure_mat_saving": 1.0,  # 科研不吃材料减免
            "structure_time_mod": round(structure_time_mod, 4),
            "structure_cost_mult": round(structure_mult, 4),
            "facility_tax_pct": round(fac_tax, 3),
            "solar_system_id": effective_system_id,
            "status": "",
            "activity": activity,
            "input_blueprint_type_id": input_bp_type_id,
            "breakdown": {
                "activity": activity,
                "material_cost": round(material_cost, 2),
                "installation_fee": round(fee, 2),
                "input_bpc_cost": round(input_bpc_cost, 2),
                "sci": round(sci, 6),
                "structure_cost_mult": round(structure_mult, 4),
                "structure_time_mod": round(structure_time_mod, 4),
                "facility_tax_pct": round(fac_tax, 3),
                "job_count": job_k,
                "time_per_job": round(time_per_job),
                "total_time": round(total_seconds),
                "prod_price": round(product_price, 2),
                **extra,
            },
        }

    # ── 计划指标（纯算法已抽到 services.plan_metrics，此处保留 thin delegate 向后兼容）──

    @staticmethod
    def calculate_personal_margin(
        result: dict,
        inv_map: dict[int, tuple[int, float]],
        runs: int = 1,
        parallels: int = 1,
        cost_overrides: dict[int, float] | None = None,
    ) -> float:
        """计算考虑库存成本的个人利润率（%）。实现见 services.plan_metrics。"""
        from services.plan_metrics import calculate_personal_margin as _f

        return _f(result, inv_map, runs, parallels, cost_overrides)

    @staticmethod
    def child_manufacturing_cost(plan: dict, metrics: dict) -> float:
        """一条子项产线的总制造价 = 材料成本 + 制造作业费。实现见 services.plan_metrics。"""
        from services.plan_metrics import child_manufacturing_cost as _f

        return _f(plan, metrics)

    @staticmethod
    def adjust_mother_metrics(
        metrics: dict,
        sub_cost_map: dict[int, float],
        total_mult: int,
    ) -> tuple[float, float, float, dict[int, float]]:
        """把拆解母项的自制子项按其制造价计入成本。实现见 services.plan_metrics。"""
        from services.plan_metrics import adjust_mother_metrics as _f

        return _f(metrics, sub_cost_map, total_mult)

    # ── 制造评分 ──

    def calc_manufacturing_score(
        self,
        type_id: int,
        char_config: dict,
        mat_source_hub: str = "Jita",
        sell_hub: str = "Jita",
        facility_tax_pct: float = 0.0,
        price_type_mat: str = "sell",
        price_type_prod: str = "sell",
        bp_me: int = 0,
        bp_te: int = 0,
        system_id: int | None = None,
        structure_bonus: float = 0.0,
        structure_time_mod: float = 1.0,
        structure_mat_saving: float = 1.0,
        is_alpha: bool = False,
        mat_price_mult: float = 1.0,
        prod_price_mult: float = 1.0,
        research_costs: dict[int, float | None] | None = None,
    ) -> dict:
        """计算制造评分。

        纯算法在 domain.scoring，编排（读 DB/缓存）在 services.scoring_facade，
        本方法仅做薄委托，保持签名与默认值不变。

        ``research_costs``：批量场景由调用方整批算好传入（见 research_calculator），
        传 None 即按件现算。
        """
        from services.scoring_facade import calc_manufacturing_score as _facade

        return _facade(
            self._db,
            self._cache,
            type_id=type_id,
            char_config=char_config,
            mat_source_hub=mat_source_hub,
            sell_hub=sell_hub,
            facility_tax_pct=facility_tax_pct,
            price_type_mat=price_type_mat,
            price_type_prod=price_type_prod,
            bp_me=bp_me,
            bp_te=bp_te,
            system_id=system_id,
            structure_bonus=structure_bonus,
            structure_time_mod=structure_time_mod,
            structure_mat_saving=structure_mat_saving,
            is_alpha=is_alpha,
            mat_price_mult=mat_price_mult,
            prod_price_mult=prod_price_mult,
            research_costs=research_costs,
        )

    # ── 贸易评分 ──

    def calc_trade_score(
        self,
        type_id: int,
        buy_hub: str = "Jita",
        sell_hub: str = "Jita",
        buy_price_type: str = "buy",
        sell_price_type: str = "sell",
        char_config: dict | None = None,
        quantity: int = 1,
    ) -> dict:
        """计算贸易评分。纯算法在 domain.scoring，编排在 services.scoring_facade。"""
        from services.scoring_facade import calc_trade_score as _facade

        return _facade(
            self._db,
            self._cache,
            type_id=type_id,
            buy_hub=buy_hub,
            sell_hub=sell_hub,
            buy_price_type=buy_price_type,
            sell_price_type=sell_price_type,
            char_config=char_config,
            quantity=quantity,
        )

    # ── 反应评分 ──

    def calc_reaction_score(
        self,
        type_id: int,
        char_config: dict,
        mat_source_hub: str = "Jita",
        sell_hub: str = "Jita",
        facility_tax_pct: float = 0.0,
        price_type_mat: str = "sell",
        price_type_prod: str = "sell",
        system_id: int | None = None,
        structure_bonus: float = 0.0,
    ) -> dict:
        """计算反应（Reaction）利润评分。纯算法在 domain.scoring，编排在 services.scoring_facade。"""
        from services.scoring_facade import calc_reaction_score as _facade

        return _facade(
            self._db,
            type_id=type_id,
            char_config=char_config,
            mat_source_hub=mat_source_hub,
            sell_hub=sell_hub,
            facility_tax_pct=facility_tax_pct,
            price_type_mat=price_type_mat,
            price_type_prod=price_type_prod,
            system_id=system_id,
            structure_bonus=structure_bonus,
        )

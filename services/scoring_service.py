"""
评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

包含:
  - ScoringCache：线程安全、有界 TTL 缓存
  - 模块级便利函数：get_price / get_volume / get_system_cost_index / calc_*_score
  - ScoringService：可注入的评分服务类（同接口 + calc_reaction_score）
"""

from __future__ import annotations

from core.cache import TtlLRUCache
from core.constants import TRADE_HUB_SYSTEM_IDS
from core.container import get_container
from core.eve_formulas import (
    _hub_region_id,
    calc_broker_rate,
    calc_relist_discount,
    calc_sales_tax_rate,
)
from domain.scoring import REACTION_INSTALL_FEE_RATE  # noqa: F401  # 向后兼容 re-export
from services.blueprint_reader import (
    get_blueprint_materials,  # noqa: F401  # 由 application 门面经模块属性访问 + 测试 patch
)
from services.char_config_resolver import DEFAULT_SKILLS, resolve_char_config  # noqa: F401  # 向后兼容 re-export
from services.database_manager import DatabaseManager
from services.name_resolver import resolve_item_name  # noqa: F401  # 由 application 门面经模块属性访问


def _hub_to_system_id(hub: str) -> int | None:
    """将贸易中心名称映射为太阳系 ID。"""
    return TRADE_HUB_SYSTEM_IDS.get(hub)


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


def get_price(
    type_id: int,
    price_type: str,
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> float | None:
    """
    从 market_prices 获取指定区域的价格。
    price_type: 'buy' → buy_price, 'sell' → sell_price
    hub: 贸易中心名称, 如 'Jita', 'Amarr'；None 时返回任意区域
    _db: 可选注入的 DatabaseManager；None 时使用模块级单例。
    """
    conn_mgr = _db or _default_db()
    _VALID_PRICE_COLS = {"buy": "buy_price", "sell": "sell_price"}
    col = _VALID_PRICE_COLS.get(price_type)
    if col is None:
        return None
    with conn_mgr.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and row[0] is not None:
                return float(row[0])
            # 降级：该区域无数据，尝试其他区域
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                (type_id,),
            )
        else:
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                (type_id,),
            )
        row = c.fetchone()
        return row[0] if row else None


def get_volume(
    type_id: int,
    vol_type: str = "total",
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> int:
    """获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'"""
    conn_mgr = _db or _default_db()
    with conn_mgr.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and (row[0] or row[1]):
                if vol_type == "total":
                    return int(row[0] + row[1])
                return int(row[0] if vol_type == "buy" else row[1])
            # 降级：该区域无数据，尝试其他区域
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        else:
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        row = c.fetchone()
        if not row:
            return 0
        if vol_type == "buy":
            return row[0] or 0
        elif vol_type == "sell":
            return row[1] or 0
        return (row[0] or 0) + (row[1] or 0)


def get_system_cost_index(
    system_id: int | None,
    activity: str = "manufacturing",
    _db: DatabaseManager | None = None,
    hub: str = "Jita",
) -> float:
    """从数据库获取星系的制造成本指数(SCI)。system_id=None 时从 hub 推断。"""
    from core.constants import DEFAULT_SYSTEM_COST_INDEX

    if system_id is None:
        system_id = _hub_to_system_id(hub)
    if system_id is None:
        return DEFAULT_SYSTEM_COST_INDEX
    conn_mgr = _db or _default_db()
    with conn_mgr.connect("ref") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
            (system_id, activity),
        )
        row = c.fetchone()
        return float(row[0]) if row else DEFAULT_SYSTEM_COST_INDEX


def get_adjusted_price(
    type_id: int,
    _db: DatabaseManager | None = None,
) -> float | None:
    """获取 ESI adjusted price（EIV 计算用）。兜底 None → 用 sell_price。"""
    conn_mgr = _db or _default_db()
    with conn_mgr.connect("mkt") as conn:
        try:
            r = conn.execute(
                "SELECT adjusted_price FROM market_prices WHERE type_id = ? AND adjusted_price > 0 LIMIT 1",
                (type_id,),
            ).fetchone()
            return float(r[0]) if r else None
        except Exception:
            # 列不存在（旧数据库）→ 回退 sell_price
            r = conn.execute(
                "SELECT sell_price FROM market_prices WHERE type_id = ? AND sell_price > 0 LIMIT 1",
                (type_id,),
            ).fetchone()
            return float(r[0]) if r else None


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
        mat_cost = per_run.get("breakdown", {}).get("material_cost", 0) or 0
        margin = per_run.get("margin_pct", 0) or 0

        total_mat_cost = mat_cost * total_mult
        total_profit = profit_per_run * total_mult
        total_time_hours = hours_per_run * runs_only
        total_iskph = total_profit / total_time_hours if total_time_hours > 0 else 0
        daily_output = (24.0 / hours_per_run) * parallels if hours_per_run > 0 else 0

        # 保留原始 per_run 字段 + 新增 total_ 字段
        result = dict(per_run)
        result.update(
            {
                "total_material_cost": round(total_mat_cost, 2),
                "total_profit": round(total_profit, 2),
                "total_time_hours": round(total_time_hours, 2),
                "total_isk_per_hour": round(total_iskph, 2),
                "total_daily_output": round(daily_output, 1),
                "total_margin_pct": margin,  # 比值不变
            }
        )
        return result

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
        from services.hangar_industry_config import resolve_hangar_industry_config
        from services.manufacturing_calculator import FACILITY_TAX_NPC

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

        return {
            "material_cost": round(total.get("total_material_cost", 0), 2),
            "profit": round(total.get("total_profit", 0), 2),
            "margin": round(total.get("total_margin_pct", 0), 2),
            "score": per_run.get("score", 0),
            "iskph": round(total.get("total_isk_per_hour", 0), 2),
            "calculated_time": round(total.get("total_time_hours", 0) * 3600),
            "daily_output": round(total.get("total_daily_output", 0), 1),
            # ── 个人利润率输入（新增）──
            "revenue": round(revenue_per_run * total_mult, 2),
            "fees": round(fees_per_run * total_mult, 2),
            "materials": per_run.get("materials", []),  # 每轮量（含 ME 单件豁免）
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
    ) -> dict:
        """计算制造评分。

        纯算法在 domain.scoring，编排（读 DB/缓存）在 services.scoring_facade，
        本方法仅做薄委托，保持签名与默认值不变。
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

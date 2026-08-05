"""
评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

包含:
  - ScoringCache：线程安全、有界 TTL 缓存
  - 模块级便利函数：get_price / get_volume / get_system_cost_index / calc_*_score
  - ScoringService：可注入的评分服务类（同接口 + calc_reaction_score）
"""

from __future__ import annotations

from core.cache import TtlLRUCache
from core.eve_formulas import (
    ADV_INDUSTRY_SKILL_MULT,
    _hub_region_id,
    calc_broker_rate,
    calc_relist_discount,
    calc_sales_tax_rate,
)
from services.blueprint_reader import get_blueprint_materials
from services.char_config_resolver import DEFAULT_SKILLS, resolve_char_config  # noqa: F401  # 向后兼容 re-export
from services.database_manager import DatabaseManager, get_db
from services.manufacturing_calculator import (
    calc_job_cost_fees,
    calc_material_per_run,
    calc_production_time,
)
from services.name_resolver import resolve_item_name

# 贸易中心 → 太阳系 ID 映射（用于 SCI 降级）
_TRADE_HUB_SYSTEM_IDS: dict[str, int] = {
    "Jita": 30000142,
    "Amarr": 30002187,
    "Dodixie": 30002659,
    "Rens": 30002510,
    "Hek": 30002070,
}


def _hub_to_system_id(hub: str) -> int | None:
    """将贸易中心名称映射为太阳系 ID。"""
    return _TRADE_HUB_SYSTEM_IDS.get(hub)


db = get_db()


# ════════════════════════════════════════════════════════════════════
#  评分结果缓存 — 30 分钟 TTL，有界 LRU 淘汰（线程安全）
#  统一使用 core.cache.TtlLRUCache（容器注入与模块级共用同一实现）
# ════════════════════════════════════════════════════════════════════


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


# 模块级缓存函数（委托给默认实例）
_default_cache = TtlLRUCache(max_size=500, ttl_seconds=1800)


def get_cache(key: str) -> dict | None:
    return _default_cache.get(key)


def set_cache(key: str, result: dict):
    _default_cache.set(key, result)


def invalidate_cache():
    _default_cache.invalidate()


# 模块级单例 ScoringService（供模块级便利函数复用，避免每次创建新实例）
_scoring_service_instance: ScoringService | None = None


def _get_scoring_service() -> ScoringService:
    global _scoring_service_instance
    if _scoring_service_instance is None:
        _scoring_service_instance = ScoringService(db, _default_cache)
    return _scoring_service_instance


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
    conn_mgr = _db or db
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
    conn_mgr = _db or db
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
    if system_id is None:
        system_id = _hub_to_system_id(hub)
    if system_id is None:
        return 0.05
    conn_mgr = _db or db
    with conn_mgr.connect("ref") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
            (system_id, activity),
        )
        row = c.fetchone()
        return row[0] if row else 1.0


def get_adjusted_price(
    type_id: int,
    _db: DatabaseManager | None = None,
) -> float | None:
    """获取 ESI adjusted price（EIV 计算用）。兜底 None → 用 sell_price。"""
    conn_mgr = _db or db
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


# 研究成本进程内缓存（(type_id, solar_system_id) → cost|None）— 价格刷新时由 invalidate_cache 一并清空
_research_cost_cache: dict[tuple[int, int | None], float | None] = {}


def _research_cost_cached(_db: DatabaseManager, type_id: int, *, solar_system_id: int | None = None) -> float:
    """按 type_id + 设施星系计算研究成本（拷贝/发明），带进程内缓存；失败返回 0。

    SCI 按设施星系 solar_system_id 查询；None → research_calculator 内部回落默认科研机库星系。
    """
    key = (type_id, solar_system_id)
    if key in _research_cost_cache:
        return _research_cost_cache[key] or 0.0
    try:
        from services.research_calculator import research_cost_for_item

        with _db.connect("bp") as conn:
            cost = research_cost_for_item(conn, type_id, solar_system_id=solar_system_id)
        _research_cost_cache[key] = cost
        return cost or 0.0
    except Exception:
        _research_cost_cache[key] = None
        return 0.0


def _clear_research_cost_cache() -> None:
    """清空研究成本缓存（价格刷新时调用）。"""
    _research_cost_cache.clear()


# ════════════════════════════════════════════════════════════════════
#  精炼价值计算
# ════════════════════════════════════════════════════════════════════


def calc_refining_value(
    type_id: int,
    quantity: int = 1,
    *,
    skills: dict | None = None,
    is_player_facility: bool = False,
    price_hub: str = "Jita",
    yield_override: float | None = None,
    ore_skill: int = 0,
) -> dict:
    """计算物品的精炼产出及总价值

    Args:
        type_id: 矿石/冰矿/残骸 type_id
        quantity: 数量
        skills: 角色技能字典
        is_player_facility: 是否玩家设施
        price_hub: 贸易中心
        yield_override: 指定产率（覆盖计算）
        ore_skill: 矿石专精技能等级

    Returns:
        {
            "yield_rate": float,        # 精炼产率 0~1
            "output": [                  # 产出物列表
                {"type_id": id, "name": str, "qty": float, "price": float, "total": float}
            ],
            "total_value": float,        # 产物总价值
            "input_value": float,        # 原材料市场价
            "profit": float,             # 精炼后增值（可为负）
            "margin_pct": float,         # 利润率 %
        }
    """
    from core.eve_formulas import calc_refining_yield, resolve_item_name

    yield_rate = (
        yield_override
        if yield_override is not None
        else calc_refining_yield(
            skills,
            is_player_facility=is_player_facility,
        )
    )
    # 加入矿石专精
    yield_rate += ore_skill * 0.02
    yield_rate = min(yield_rate, 0.85)

    # 从数据库查询 reprocessing_materials
    with db.connect("ref") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT material_type_id, quantity FROM type_materials WHERE type_id = ?",
            (type_id,),
        )
        materials = cur.fetchall()

    if not materials:
        return {
            "yield_rate": yield_rate,
            "output": [],
            "total_value": 0,
            "input_value": 0,
            "profit": 0,
            "margin_pct": 0,
        }

    output = []
    total_value = 0.0
    with db.connect("ref") as rconn:
        cur = rconn.cursor()
        for mat_id, mat_qty in materials:
            qty = mat_qty * yield_rate * quantity
            price = get_price(mat_id, "sell", price_hub) or 0.0
            total = round(qty * price, 2)
            name = resolve_item_name(cur, mat_id)
            output.append(
                {
                    "type_id": mat_id,
                    "name": name,
                    "qty": round(qty, 2),
                    "price": price,
                    "total": total,
                }
            )
            total_value += total

    input_price = get_price(type_id, "sell", price_hub) or 0.0
    input_value = input_price * quantity
    profit = total_value - input_value
    margin_pct = (profit / input_value * 100) if input_value > 0 else 0.0

    return {
        "yield_rate": round(yield_rate, 4),
        "output": output,
        "total_value": round(total_value, 2),
        "input_value": round(input_value, 2),
        "profit": round(profit, 2),
        "margin_pct": round(margin_pct, 2),
    }


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

    @staticmethod
    def calculate_personal_margin(
        result: dict,
        inv_map: dict[int, tuple[int, float]],
        runs: int = 1,
        parallels: int = 1,
        cost_overrides: dict[int, float] | None = None,
    ) -> float:
        """计算考虑库存成本的个人利润率（%）。

        与市场利润率同口径：仅把材料成本替换为库存成本
        （库存不足部分按材料市场 unit_price 补齐），安装费/经纪人费/销售税与市场列完全一致。
        无库存时返回值与 result 的市场 margin 在 2 位小数内严格相等。

        Args:
            result: calculate_plan_metrics() 的返回 dict
                    （需含 revenue_per_run / fees_per_run / materials / margin）
            inv_map: get_inventory_cost_map() 的返回 {type_id: (总数量, 加权平均成本)}
            runs / parallels: 流程数 / 并行数
            cost_overrides: 可选 {type_id: 固定成本}——拆解母项的子项自制件按其制造价计，
                            不再走库存/市场价。

        Returns:
            个人利润率（%），round 到 2 位小数。异常或无效输入回退 result 的市场 margin。

        精度契约：必须读未取整的 revenue_per_run / fees_per_run，
        禁用已 round 的 revenue / fees，否则"无库存=市场列"的严格相等会被破坏。
        """
        try:
            total_mult = max(runs, 1) * max(parallels, 1)
            fallback = result.get("margin", 0) or 0
            revenue_per_run = result.get("revenue_per_run", 0) or 0
            fees_per_run = result.get("fees_per_run", 0) or 0
            materials = result.get("materials", []) or []

            if not materials or revenue_per_run <= 0:
                return fallback

            total_personal_cost = 0.0
            for mat in materials:
                qty_per_run = mat.get("qty", 0) or 0
                if qty_per_run <= 0:
                    continue
                mid = mat.get("type_id")
                need = qty_per_run * total_mult
                if cost_overrides and mid in cost_overrides:
                    # 子项自制件：成本 = 子项制造价（合计，非库存/市场价）
                    mat_cost = cost_overrides[mid]
                else:
                    unit_price = mat.get("unit_price", 0) or 0
                    stock_qty, stock_cost = inv_map.get(mid, (0, 0))
                    if stock_qty >= need:
                        mat_cost = need * stock_cost
                    elif stock_qty > 0:
                        mat_cost = stock_qty * stock_cost + (need - stock_qty) * unit_price
                    else:
                        mat_cost = need * unit_price
                total_personal_cost += mat_cost

            total_cost = total_personal_cost + fees_per_run * total_mult
            if total_cost <= 0:
                return fallback

            total_revenue = revenue_per_run * total_mult
            margin = (total_revenue - total_cost) / total_cost * 100
            return round(margin, 2)
        except Exception:
            return result.get("margin", 0) or 0

    # ── 拆解母项成本（子项自制件按其制造价计）──

    @staticmethod
    def child_manufacturing_cost(plan: dict, metrics: dict) -> float:
        """一条子项产线的总制造价 = 材料成本 + 制造作业费（安装费）。

        Args:
            plan: 子项计划 dict（runs/parallels 用于把单轮安装费放大到整条产线）。
            metrics: calculate_plan_metrics() 对子项返回的 dict
                     （须含 material_cost 与 breakdown.installation_fee）。

        Returns:
            子项产线制造价合计（材料 + 作业费）。breakdown 缺失时兜底仅材料成本。
        """
        material = metrics.get("material_cost", 0) or 0
        breakdown = metrics.get("breakdown", {}) or {}
        job_per_run = breakdown.get("installation_fee", 0) or 0
        total_mult = max(int(plan.get("runs", 1)), 1) * max(int(plan.get("parallels", 1)), 1)
        return round(material + job_per_run * total_mult, 2)

    @staticmethod
    def adjust_mother_metrics(
        metrics: dict,
        sub_cost_map: dict[int, float],
        total_mult: int,
    ) -> tuple[float, float, float, dict[int, float]]:
        """把拆解母项的自制子项按其制造价计入成本，其余材料仍按市场价。

        Args:
            metrics: calculate_plan_metrics() 对母项返回的 dict
                     （须含 materials/revenue/fees，materials 为每轮量）。
            sub_cost_map: {子项 product_type_id: 子项制造价（整条产线合计，见 child_manufacturing_cost）}。
            total_mult: runs × parallels。

        Returns:
            (调整后 material_cost, 调整后 profit, 调整后 margin, cost_overrides)。
            cost_overrides 供 calculate_personal_margin 的个人利润率计算使用。
            不修改入参 metrics。
        """
        revenue = metrics.get("revenue", 0) or 0
        fees = metrics.get("fees", 0) or 0
        new_material_cost = 0.0
        cost_overrides: dict[int, float] = {}
        for mat in metrics.get("materials", []) or []:
            mid = mat.get("type_id")
            qty_per_run = mat.get("qty", 0) or 0
            if qty_per_run <= 0:
                continue
            if mid in sub_cost_map:
                new_material_cost += sub_cost_map[mid]
                cost_overrides[mid] = sub_cost_map[mid]
            else:
                new_material_cost += qty_per_run * total_mult * (mat.get("unit_price", 0) or 0)
        new_material_cost = round(new_material_cost, 2)
        profit = round(revenue - new_material_cost - fees, 2)
        denom = new_material_cost + fees
        margin = round(profit / denom * 100, 2) if denom > 0 else 0.0
        return new_material_cost, profit, margin, cost_overrides

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

        重构后使用 manufacturing_calculator 中的公式：
        - 材料浪费: calc_material_per_run / calc_material_for_runs
        - 安装费: calc_job_cost_fees（加法结构）
        - 时间: calc_production_time
        """
        # 缓存：同一 type_id × 配置 × ME × 星系 结果复用（TTL 1800s，价格刷新时 invalidate_cache）
        char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
        cache_k = cache_key(
            type_id,
            f"mfg|{mat_source_hub}|{sell_hub}|{bp_me}|{bp_te}|{price_type_mat}|{price_type_prod}|{system_id or ''}"
            f"|{structure_bonus}|{structure_time_mod}|{structure_mat_saving}",
            "hub",
            char_name,
        )
        cached = self._cache.get(cache_k) if self._cache else None
        if cached is not None:
            return dict(cached)

        result = {
            "score": 0.0,
            "profit_per_run": 0.0,
            "margin_pct": 0.0,
            "isk_per_hour": 0.0,
            "cost_per_unit": 0.0,
            "revenue_per_unit": 0.0,
            "hours_per_run": 0.0,
            "status": "",
            "breakdown": {},
        }

        with self._db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()

            c.execute(
                """
                SELECT bp.blueprint_type_id, bp.quantity, ba.time
                FROM blueprint_products bp
                JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                    AND ba.activity = bp.activity
                WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
                LIMIT 1
            """,
                (type_id,),
            )
            bp_row = c.fetchone()
            if not bp_row:
                result["status"] = "no_blueprint"
                return result

            bp_id, prod_qty, base_time = bp_row
            prod_qty = prod_qty or 1

            prod_price = get_price(type_id, price_type_prod, sell_hub, _db=self._db)
            if not prod_price:
                result["status"] = "no_price"
                return result

            # 用 blueprint_reader 获取材料（含 wastefactor）
            mat_rows = get_blueprint_materials(conn, bp_id)
            if not mat_rows:
                result["status"] = "no_materials"
                return result

            # 材料成本计算（使用正确的浪费公式 + ceil 取整）
            total_mat_cost = 0.0
            mat_detail = []
            eiv_materials: list[tuple[int, float]] = []
            for mat_id, mat_qty, wastefactor in mat_rows:
                wastefactor = wastefactor or 10  # 兜底 T1
                mat_price = get_price(mat_id, price_type_mat, mat_source_hub, _db=self._db)
                # EIV 使用 adjusted_price（更稳定），兜底用 mat_price
                adj_price = get_adjusted_price(mat_id, _db=self._db) or mat_price or 0.0
                # 单件材料(基础量=1)不受ME影响——如T1舰船、矿物、组件等
                # 因为 ceil(1×(100-ME)/100)=1，ME 无法将 1 个减到 0 个
                if mat_qty <= 1:
                    per_run_qty = mat_qty
                    is_whole_item = True
                else:
                    per_run_qty = calc_material_per_run(mat_qty, wastefactor, bp_me, structure_mat_saving)
                    is_whole_item = False
                waste_qty = per_run_qty  # 每轮次仅用 per_run_qty（已含 ME 调整）
                if mat_price:
                    total_mat_cost += waste_qty * mat_price
                mat_name = resolve_item_name(conn, mat_id)
                # EIV 基础材料量（ME0 无浪费）× adjusted_price
                base_qty_no_waste = mat_qty
                eiv_materials.append((base_qty_no_waste, adj_price))
                mat_detail.append(
                    {
                        "name": mat_name,
                        "type_id": mat_id,
                        "base_qty": mat_qty,
                        "qty": waste_qty,
                        "wastefactor": wastefactor,
                        "waste_factor": round(per_run_qty / mat_qty, 4) if mat_qty > 0 else 1.0,
                        "unit_price": mat_price or 0.0,
                        "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                        "is_whole_item": is_whole_item,
                    }
                )
            result["materials"] = mat_detail

            skills = char_config.get("skills", {}) if char_config else {}
            market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

            broker_rate = self._calc_broker_rate(skills, market_data)
            relist_discount = self._calc_relist_discount(skills)
            sales_tax_rate = self._calc_sales_tax_rate(skills)

            revenue = prod_price * prod_qty
            total_cost = total_mat_cost
            sci = get_system_cost_index(system_id, "manufacturing", _db=self._db, hub=sell_hub)

            # EIV 计算 & 安装费（加法结构）
            eiv = sum(qty * price for qty, price in eiv_materials)
            # structure_bonus: 传入的 0.0 表示 NPC 无加成 → 乘数 1.0
            # 传入的负值表示折扣（如 -0.1 → 乘数 0.9）
            sb_mult = 1.0 + structure_bonus
            alpha_tax = 0.0025 if is_alpha else 0.0
            fee_detail = calc_job_cost_fees(
                eiv=eiv,
                sci=sci,
                structure_mult=sb_mult,
                facility_tax=facility_tax_pct / 100,
                alpha_tax=alpha_tax,
            )
            system_cost_fee = fee_detail["system_cost"]
            facility_tax_fee = fee_detail["facility_tax"]
            scc_fee = fee_detail["scc"]
            alpha_fee = fee_detail["alpha_tax"]
            installation_fee = fee_detail["total_fee"]
            total_cost += installation_fee

            broker_init = revenue * (broker_rate / 100)
            # 改单差额计费：改单只对「改价差额」部分收一次 broker 费（× 改单折扣）。
            # 无历史挂单价时用成本价近似 —— 假设已按成本挂单、改价到售价只补差额。
            unit_cost = total_cost / prod_qty if prod_qty > 0 else 0.0
            relist_delta = max(0.0, prod_price - unit_cost) * prod_qty
            broker_relist = relist_delta * (broker_rate / 100) * (1 - relist_discount / 100)
            sales_tax = revenue * (sales_tax_rate / 100)
            total_cost += broker_init + broker_relist + sales_tax

            # 未取整原始值：供 calculate_personal_margin 复用，
            # 保证无库存时个人利润率与市场利润率在 2 位小数内严格相等
            result["revenue_per_run"] = revenue
            result["fees_per_run"] = installation_fee + broker_init + broker_relist + sales_tax

            # 研究成本（拷贝/发明）— T1 拷贝、T2/T3 发明，计入总成本（模块级缓存避免重复查）
            research_cost = _research_cost_cached(self._db, type_id, solar_system_id=system_id)
            total_cost += research_cost

            profit = revenue - total_cost

            # 时间计算（使用 calc_production_time）
            ind_lvl = skills.get("工业理论", 5)
            adv_lvl = skills.get("高级工业理论", 5)
            actual_time = calc_production_time(
                base_time=base_time,
                industry_skill=ind_lvl,
                adv_industry_skill=adv_lvl,
                te_level=bp_te,
                structure_time_mod=structure_time_mod,
            )
            hours_per_run = actual_time / 3600
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

            # 费用明细字典（与游戏安装费类目对齐）
            breakdown = {
                "bp_me": bp_me,
                "bp_te": bp_te,
                "isk_per_hour": 0.0,
                "revenue": round(revenue, 2),
                "material_cost": round(total_mat_cost, 2),
                "broker_init": round(broker_init, 2),
                "broker_relist": round(broker_relist, 2),
                "sales_tax": round(sales_tax, 2),
                # 安装费（Job Cost）— 与游戏内显示结构一致
                "eiv": round(eiv, 2),  # 预估物品价值
                "sci": round(sci, 4),  # 星系成本指数
                "system_cost": round(system_cost_fee, 2),  # 项目毛成本（星系成本指数 × EIV）
                "facility_tax": round(facility_tax_fee, 2),  # 设施税
                "scc_surcharge": round(scc_fee, 2),  # SCC 附加费
                "alpha_tax": round(alpha_fee, 2),  # Alpha 税
                "installation_fee": round(installation_fee, 2),  # 项目总费用
                "structure_bonus": round(structure_bonus, 4),
                "structure_time_mod": round(structure_time_mod, 4),
                "structure_mat_saving": round(structure_mat_saving, 4),
                "facility_tax_pct": round(facility_tax_pct, 2),
                "broker_rate": round(broker_rate, 3),
                "sales_tax_rate": round(sales_tax_rate, 3),
                "relist_discount": round(relist_discount, 1),
                "research_cost": round(research_cost, 2),  # 拷贝/发明研究成本
            }

            if profit <= 0:
                result.update(
                    {
                        "margin_pct": round(margin_pct, 2),
                        "profit_per_run": round(profit, 2),
                        "cost_per_unit": round(total_cost / prod_qty, 2),
                        "hours_per_run": round(hours_per_run, 2),
                        "revenue_per_unit": round(prod_price, 2),
                        "breakdown": breakdown,
                    }
                )
                return result

            volume = get_volume(type_id, "total", sell_hub, _db=self._db)
            if volume == 0:
                return result

            profit_score = min(margin_pct * 4, 40)
            volume_factor = min(volume / 5_000_000, 1.0)
            volume_score = volume_factor * 30
            isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
            efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)
            total_score = profit_score + volume_score + efficiency_score

            breakdown.update(
                {
                    "profit_score": round(profit_score, 1),
                    "volume_score": round(volume_score, 1),
                    "efficiency_score": round(efficiency_score, 1),
                    "isk_per_hour": round(isk_per_hour, 2),
                }
            )

            result.update(
                {
                    "score": round(total_score, 1),
                    "profit_per_run": round(profit, 2),
                    "margin_pct": round(margin_pct, 2),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "cost_per_unit": round(total_cost / prod_qty, 2),
                    "revenue_per_unit": round(prod_price, 2),
                    "hours_per_run": round(hours_per_run, 2),
                    "status": "",
                    "breakdown": breakdown,
                }
            )

        # 写入缓存（仅缓存成功结果，失败状态不缓存）
        score_val = result["score"]
        if isinstance(score_val, int | float) and score_val > 0 and self._cache is not None:
            self._cache.set(cache_k, dict(result))
        return result

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
        """计算贸易评分。"""
        char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
        cache_k = cache_key(
            type_id,
            f"trade|{buy_hub}|{sell_hub}|{buy_price_type}|{sell_price_type}|{quantity}",
            "hub",
            char_name,
        )
        cached = self._cache.get(cache_k) if self._cache else None
        if cached is not None:
            return dict(cached)

        result = {
            "score": 0.0,
            "buy_cost": 0.0,
            "sell_revenue": 0.0,
            "gross_profit": 0.0,
            "margin_pct": 0.0,
            "profit_per_m3": 0.0,
            "status": "",
        }

        buy_price = get_price(type_id, buy_price_type, buy_hub, _db=self._db)
        sell_price = get_price(type_id, sell_price_type, sell_hub, _db=self._db)
        if not buy_price or not sell_price:
            result["status"] = "no_price"
            return result

        with self._db.connect("ref") as conn:
            c = conn.cursor()
            c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
            row = c.fetchone()
            volume_m3 = row[0] or 1.0 if row else 1.0

        skills = char_config.get("skills", {}) if char_config else {}
        market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
        market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

        broker_rate = self._calc_broker_rate(skills, market_data_buy)
        relist_discount = self._calc_relist_discount(skills)
        sales_tax_rate = self._calc_sales_tax_rate(skills)

        # 差额计费：初始挂单全额 broker；改单只对「买/卖价差额」部分收一次 broker（× 改单折扣）
        buy_fee_total = broker_rate + broker_rate * (1 - relist_discount / 100)

        sell_rate = self._calc_broker_rate(skills, market_data_sell)
        # 卖出侧：初始挂单全额 broker（按买入成本近似）+ 改单差额 broker + 销售税
        sell_fee_total = (
            (
                broker_rate
                + (sell_price - buy_price) / sell_price * broker_rate * (1 - relist_discount / 100)
                + sales_tax_rate
            )
            if sell_price > 0
            else sell_rate + sell_rate * (1 - relist_discount / 100) + sales_tax_rate
        )

        buy_cost = buy_price * quantity + buy_price * quantity * (buy_fee_total / 100)
        sell_revenue = sell_price * quantity - sell_price * quantity * (sell_fee_total / 100)
        gross_profit = sell_revenue - buy_cost
        margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0

        if gross_profit <= 0:
            result["margin_pct"] = round(margin_pct, 2)
            result["buy_cost"] = round(buy_cost, 2)
            result["sell_revenue"] = round(sell_revenue, 2)
            result["gross_profit"] = round(gross_profit, 2)
            return result

        volume = get_volume(type_id, "total", sell_hub, _db=self._db)
        if volume == 0:
            return result

        margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0
        profit_per_m3 = gross_profit / volume_m3 if volume_m3 > 0 else gross_profit

        margin_score = min(margin_pct * 5, 50)
        volume_factor = min(volume / 5_000_000, 1.0)
        vol_score = volume_factor * 50
        total_score = margin_score + vol_score

        result.update(
            {
                "score": round(total_score, 1),
                "buy_cost": round(buy_cost, 2),
                "sell_revenue": round(sell_revenue, 2),
                "gross_profit": round(gross_profit, 2),
                "margin_pct": round(margin_pct, 2),
                "profit_per_m3": round(profit_per_m3, 2),
            }
        )

        # 写入缓存（仅缓存成功结果）
        score_val = result["score"]
        if isinstance(score_val, int | float) and score_val > 0 and self._cache is not None:
            self._cache.set(cache_k, dict(result))
        return result

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
        """
        计算反应（Reaction）利润评分。

        与 calc_manufacturing_score 的差异:
          - 查 activity='reaction' 的蓝图数据
          - 无 ME/TE 概念：waste_factor=1.0, 无 TE 修正
          - 时间仅受 Advanced Industry 技能影响（-3%/级）
          - 安装费使用反应专用 SCI
        """
        result = {
            "score": 0.0,
            "profit_per_run": 0.0,
            "margin_pct": 0.0,
            "isk_per_hour": 0.0,
            "cost_per_unit": 0.0,
            "revenue_per_unit": 0.0,
            "hours_per_run": 0.0,
            "status": "",
            "breakdown": {},
        }

        with self._db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()

            # 1. 查找反应蓝图
            c.execute(
                """
                SELECT bp.blueprint_type_id, bp.quantity, ba.time
                FROM blueprint_products bp
                JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                    AND ba.activity = bp.activity
                WHERE bp.product_type_id = ? AND bp.activity = 'reaction'
                LIMIT 1
                """,
                (type_id,),
            )
            bp_row = c.fetchone()
            if not bp_row:
                result["status"] = "no_blueprint"
                return result

            bp_id, prod_qty, base_time = bp_row
            prod_qty = prod_qty or 1

            # 2. 成品价格
            prod_price = get_price(type_id, price_type_prod, sell_hub, _db=self._db)
            if not prod_price:
                result["status"] = "no_price"
                return result

            # 3. 查反应材料
            c.execute(
                """
                SELECT bm.material_type_id, bm.quantity
                FROM blueprint_materials bm
                WHERE bm.blueprint_type_id = ? AND bm.activity = 'reaction'
                """,
                (bp_id,),
            )
            mat_rows = c.fetchall()

            if not mat_rows:
                result["status"] = "no_materials"
                return result

            # 4. 计算材料成本（反应无 ME 浪费，waste_factor=1.0）
            waste_factor = 1.0
            total_mat_cost = 0.0
            mat_detail = []
            for mat_id, mat_qty in mat_rows:
                mat_price = get_price(mat_id, price_type_mat, mat_source_hub, _db=self._db)
                waste_qty = mat_qty * waste_factor
                if mat_price:
                    total_mat_cost += waste_qty * mat_price
                mat_name = resolve_item_name(conn, mat_id)
                mat_detail.append(
                    {
                        "name": mat_name,
                        "base_qty": mat_qty,
                        "qty": round(waste_qty, 2),
                        "waste_factor": round(waste_factor, 2),
                        "unit_price": mat_price or 0.0,
                        "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                    }
                )
            result["materials"] = mat_detail

            # 5. 从人物配置读取费率
            skills = char_config.get("skills", {}) if char_config else {}
            market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

            broker_rate = calc_broker_rate(skills, market_data)
            relist_discount = calc_relist_discount(skills)
            sales_tax_rate_val = calc_sales_tax_rate(skills)

            # 6. 安装费
            revenue = prod_price * prod_qty
            total_cost = total_mat_cost
            sci = get_system_cost_index(system_id, "reaction", _db=self._db, hub=mat_source_hub)
            install_base = REACTION_INSTALL_FEE_RATE * revenue
            reaction_install_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
            total_cost += reaction_install_fee
            broker_init = revenue * (broker_rate / 100)
            broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
            sales_tax = revenue * (sales_tax_rate_val / 100)
            total_cost += broker_init + broker_relist + sales_tax

            profit = revenue - total_cost
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

            # 7. 反应时间
            adv_lvl = skills.get("高级工业理论", 5)
            skill_mod = 1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl
            actual_time = base_time * skill_mod
            hours_per_run = actual_time / 3600

            # 8. 负利润时提前返回
            if profit <= 0:
                result["margin_pct"] = round(margin_pct, 2)
                result["profit_per_run"] = round(profit, 2)
                result["cost_per_unit"] = round(total_cost / prod_qty, 2)
                result["hours_per_run"] = round(hours_per_run, 2)
                result["revenue_per_unit"] = round(prod_price, 2)
                return result

            # 9. 评分
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0
            volume = get_volume(type_id, "total", sell_hub, _db=self._db)
            if volume == 0:
                return result

            profit_score = min(margin_pct * 4, 40)  # 10% = 40分
            volume_factor = min(volume / 5_000_000, 1.0)
            volume_score = volume_factor * 30  # 500万 = 30分
            isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
            efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)  # 5000万/h = 30分

            total_score = profit_score + volume_score + efficiency_score

            result.update(
                {
                    "score": round(total_score, 1),
                    "profit_per_run": round(profit, 2),
                    "margin_pct": round(margin_pct, 2),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "cost_per_unit": round(total_cost / prod_qty, 2),
                    "revenue_per_unit": round(prod_price, 2),
                    "hours_per_run": round(hours_per_run, 2),
                    "status": "",
                    "breakdown": {
                        "waste_factor": round(waste_factor, 2),
                        "profit_score": round(profit_score, 1),
                        "volume_score": round(volume_score, 1),
                        "efficiency_score": round(efficiency_score, 1),
                        "isk_per_hour": round(isk_per_hour, 2),
                        "revenue": round(revenue, 2),
                        "material_cost": round(total_mat_cost, 2),
                        "broker_init": round(broker_init, 2),
                        "broker_relist": round(broker_relist, 2),
                        "sales_tax": round(sales_tax, 2),
                        "reaction_install_fee": round(reaction_install_fee, 2),
                        "install_base": round(install_base, 2),
                        "sci": round(sci, 4),
                        "structure_bonus": round(structure_bonus, 4),
                        "facility_tax_pct": round(facility_tax_pct, 2),
                        "broker_rate": round(broker_rate, 3),
                        "sales_tax_rate": round(sales_tax_rate_val, 3),
                        "relist_discount": round(relist_discount, 1),
                    },
                }
            )

        return result


# ════════════════════════════════════════════════════════════════════
#  反应安装费常数（模块级导出供外部使用）
# ════════════════════════════════════════════════════════════════════

REACTION_INSTALL_FEE_RATE = 0.05


# ════════════════════════════════════════════════════════════════════
#  模块级评分便利函数（使用默认 db 单例 + 默认缓存）
#  向后兼容：保持与旧 services.scoring 相同的接口签名
# ════════════════════════════════════════════════════════════════════


def calc_manufacturing_score(
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
    is_alpha: bool = False,
) -> dict:
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_manufacturing_score(
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
        is_alpha=is_alpha,
    )


def calc_trade_score(
    type_id: int,
    buy_hub: str = "Jita",
    sell_hub: str = "Jita",
    buy_price_type: str = "buy",
    sell_price_type: str = "sell",
    char_config: dict | None = None,
    quantity: int = 1,
) -> dict:
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_trade_score(
        type_id=type_id,
        buy_hub=buy_hub,
        sell_hub=sell_hub,
        buy_price_type=buy_price_type,
        sell_price_type=sell_price_type,
        char_config=char_config,
        quantity=quantity,
    )


def calc_reaction_score(
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
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_reaction_score(
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

"""评分编排门面。

职责：开连接 → 取蓝图/材料/名称/价格 → 组装输入 → 调 domain 纯函数 → 写缓存。

数据访问经 `services.scoring_service` 模块级函数（`_ss.get_price` 等）在调用时解析，
以保留测试对这些符号的 patch 语义（`@patch("services.scoring_service.get_price")`）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import services.scoring_service as _ss
from core.constants import TRADE_HUB_IDS
from domain.scoring import BlueprintRecipe, Material
from domain.scoring import calc_manufacturing_score as _pure_calc
from domain.scoring import calc_reaction_score as _pure_reaction
from domain.scoring import calc_trade_score as _pure_trade
from services.repositories.market_repository import MarketRepository


class _DbPriceProvider:
    """PriceProvider 适配 — 委托给 scoring_service 模块级定价函数（可被测试 patch）。

    ``preloaded``：本物品材料的一次性批量预取结果，键为 ``(type_id, "buy"/"sell"/"adjusted")``。
    只装「一次查询就能确定」的键，查不到的一律回落模块级单条函数 —— 跨区域降级、
    无价格、旧库缺列等语义全部保持原样。
    """

    def __init__(self, db, preloaded: dict[tuple[int, str], float | None] | None = None):
        self._db = db
        self._preloaded = preloaded or {}

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        hit = self._preloaded.get((type_id, price_type))
        if hit is not None:
            return hit
        return _ss.get_price(type_id, price_type, hub, _db=self._db)

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
        return _ss.get_volume(type_id, vol_type, hub, _db=self._db)

    def get_system_cost_index(self, system_id: int | None, activity: str = "manufacturing", hub: str = "Jita") -> float:
        return _ss.get_system_cost_index(system_id, activity, _db=self._db, hub=hub)

    def get_adjusted_price(self, type_id: int) -> float | None:
        if (type_id, "adjusted") in self._preloaded:
            # 可能是 None：批量查询已确认该 type 没有可用值，不必再查一次
            value = self._preloaded[(type_id, "adjusted")]
            return float(value) if value is not None else None
        return _ss.get_adjusted_price(type_id, _db=self._db)


def _preload_material_prices(
    db, mat_ids: list[int], price_type: str, hub: str | None
) -> dict[tuple[int, str], float | None]:
    """一次 IN 查询预取材料价格与 adjusted price（EIV）。

    逐材料取价会让批量重算变成每件约 10 次 SQL（实测 4797 件 / 118,149 次 / 30 秒）。
    两条路径的「权威性」不同，必须分别对待：

    - **价格**：只装命中 hub 区域的。查不到的不装 —— 单条查询还有「跨区域降级」，
      这里装 None 会把降级路径掐掉。
    - **EIV（adjusted price）**：只要列存在，**每个 type 都装**（缺失装 None）。
      否则材料普遍 adjusted_price=0 时会「批量查不到 → 回落单条 → 单条也说没有」，
      等于白查一遍（实测这条占了 4.0 次/件）。旧库没有该列时批量返回 None，
      整体回落单条路径，保留旧库的 sell_price 回退。
    """
    ids = [t for t in dict.fromkeys(mat_ids) if t]
    if not ids:
        return {}
    repo = MarketRepository(db)
    out: dict[tuple[int, str], float | None] = {}
    if hub and price_type in ("buy", "sell"):
        rid = TRADE_HUB_IDS.get(hub, TRADE_HUB_IDS["Jita"])
        for tid, price in repo.get_prices_by_region(ids, rid, price_type).items():
            out[(tid, price_type)] = price
    adjusted = repo.get_adjusted_prices(ids)
    if adjusted is not None:
        for tid in ids:
            out[(tid, "adjusted")] = adjusted.get(tid)
    return out


def _char_config_fingerprint(char_config: dict | None) -> str:
    """生成角色配置的稳定摘要，用于缓存 key，避免角色配置变更后命中旧评分。"""
    if not char_config:
        return "default"
    try:
        raw = json.dumps(char_config, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return "unknown"


def calc_manufacturing_score(
    db,
    cache,
    *,
    type_id: int,
    char_config: dict | None,
    mat_source_hub: str,
    sell_hub: str,
    facility_tax_pct: float,
    price_type_mat: str,
    price_type_prod: str,
    bp_me: int,
    bp_te: int,
    system_id: int | None,
    structure_bonus: float,
    structure_time_mod: float,
    structure_mat_saving: float,
    is_alpha: bool,
    mat_price_mult: float = 1.0,
    prod_price_mult: float = 1.0,
    research_costs: dict[int, float | None] | None = None,
) -> dict[str, Any]:
    """制造评分用例：编排 DB 读取 + 领域纯函数 + 缓存。

    ``mat_price_mult`` / ``prod_price_mult``：工具栏「材料/成品倍率」。两者都是本函数的
    入参，**必须进 cache_key** —— 否则改倍率后会命中上一档缓存，复现「数字不动」的陈旧值缺陷。

    ``research_costs``：整批一次算好的 ``{type_id: 研究成本}``（见
    ``research_calculator.research_costs_batch``）。批量调用方传入可省掉每件重跑
    拷贝/发明查询 —— 实测这条占批量耗时 93%。None → 按件现算（单件路径不变）。
    传入值必须用**同一个 solar_system_id** 算出来，否则与逐件口径不一致。
    """
    char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
    # 非正数回落到 1.0（settings.json 可手改，不能信）
    mat_price_mult = mat_price_mult if mat_price_mult and mat_price_mult > 0 else 1.0
    prod_price_mult = prod_price_mult if prod_price_mult and prod_price_mult > 0 else 1.0
    cache_k = _ss.cache_key(
        type_id,
        f"mfg|{mat_source_hub}|{sell_hub}|{bp_me}|{bp_te}|{price_type_mat}|{price_type_prod}|{system_id or ''}"
        f"|{structure_bonus}|{structure_time_mod}|{structure_mat_saving}|{facility_tax_pct}|{int(is_alpha)}"
        f"|{round(mat_price_mult, 4)}|{round(prod_price_mult, 4)}"
        f"|{_char_config_fingerprint(char_config)}",
        "hub",
        char_name,
    )
    cached = cache.get(cache_k) if cache else None
    if cached is not None:
        return dict(cached)

    result: dict[str, Any] = {
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

    with db.connect("ref", "mkt", "bp") as conn:
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

        prod_price = _ss.get_price(type_id, price_type_prod, sell_hub, _db=db)
        if not prod_price:
            result["status"] = "no_price"
            return result
        prod_price *= prod_price_mult  # 成品倍率：与材料倍率对称，作用于成品单价

        # 用 blueprint_reader 获取材料（含 wastefactor）
        mat_rows = _ss.get_blueprint_materials(conn, bp_id)
        if not mat_rows:
            result["status"] = "no_materials"
            return result

        materials = tuple(
            Material(
                type_id=mat_id,
                name=_ss.resolve_item_name(conn, mat_id),
                base_qty=mat_qty,
                wastefactor=wastefactor,
            )
            for mat_id, mat_qty, wastefactor in mat_rows
        )

        # 材料价格一次批量预取：逐材料取价/取 EIV 是批量重算的主要开销（实测每件约 9.6 次 SQL）
        preloaded = _preload_material_prices(
            db, [mat_id for mat_id, _qty, _wf in mat_rows], price_type_mat, mat_source_hub
        )

        recipe = BlueprintRecipe(
            product_type_id=type_id,
            blueprint_type_id=bp_id,
            prod_qty=prod_qty,
            base_time=base_time,
            materials=materials,
        )
        prices = _DbPriceProvider(db, preloaded)
        # 该蓝图制造活动所需技能名 → 供 domain 按角色等级算「每级 -1% 生产时间」
        # （客户端技能文案：机械工程学「每升一级，所有需要机械工程学技能的物品的生产时间减少 1%」）
        bp_required_skills = tuple(
            row[0]
            for row in conn.execute(
                "SELECT COALESCE(i.zh_name, i.en_name, CAST(bs.skill_type_id AS TEXT)) "
                "FROM blueprint_skills bs LEFT JOIN item i ON i.type_id = bs.skill_type_id "
                "WHERE bs.blueprint_type_id = ? AND bs.activity = 'manufacturing'",
                (bp_id,),
            ).fetchall()
        )
        research_cost = (
            (research_costs.get(type_id) or 0.0)
            if research_costs is not None
            else _ss._research_cost_cached(db, type_id, solar_system_id=system_id)
        )

        result = _pure_calc(
            recipe=recipe,
            prod_price=prod_price,
            prices=prices,
            research_cost=research_cost,
            char_config=char_config,
            mat_source_hub=mat_source_hub,
            sell_hub=sell_hub,
            price_type_mat=price_type_mat,
            bp_me=bp_me,
            bp_te=bp_te,
            system_id=system_id,
            structure_bonus=structure_bonus,
            structure_time_mod=structure_time_mod,
            structure_mat_saving=structure_mat_saving,
            facility_tax_pct=facility_tax_pct,
            is_alpha=is_alpha,
            mat_price_mult=mat_price_mult,
            bp_required_skills=bp_required_skills,
        )

    # 写入缓存（仅缓存成功结果，失败状态不缓存）
    score_val = result["score"]
    if isinstance(score_val, int | float) and score_val > 0 and cache is not None:
        cache.set(cache_k, dict(result))
    return result


def calc_trade_score(
    db,
    cache,
    *,
    type_id: int,
    buy_hub: str,
    sell_hub: str,
    buy_price_type: str,
    sell_price_type: str,
    char_config: dict | None,
    quantity: int,
) -> dict[str, Any]:
    """贸易评分用例：编排 DB 读取 + 领域纯函数 + 缓存。"""
    char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
    cache_k = _ss.cache_key(
        type_id,
        f"trade|{buy_hub}|{sell_hub}|{buy_price_type}|{sell_price_type}|{quantity}"
        f"|{_char_config_fingerprint(char_config)}",
        "hub",
        char_name,
    )
    cached = cache.get(cache_k) if cache else None
    if cached is not None:
        return dict(cached)

    result: dict[str, Any] = {
        "score": 0.0,
        "buy_cost": 0.0,
        "sell_revenue": 0.0,
        "gross_profit": 0.0,
        "margin_pct": 0.0,
        "profit_per_m3": 0.0,
        "status": "",
    }

    buy_price = _ss.get_price(type_id, buy_price_type, buy_hub, _db=db)
    sell_price = _ss.get_price(type_id, sell_price_type, sell_hub, _db=db)
    if not buy_price or not sell_price:
        result["status"] = "no_price"
        return result

    with db.connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        volume_m3 = row[0] or 1.0 if row else 1.0

    result = _pure_trade(
        type_id=type_id,
        buy_price=buy_price,
        sell_price=sell_price,
        volume_m3=volume_m3,
        prices=_DbPriceProvider(db),
        char_config=char_config,
        buy_hub=buy_hub,
        sell_hub=sell_hub,
        quantity=quantity,
    )

    # 写入缓存（仅缓存成功结果）
    score_val = result["score"]
    if isinstance(score_val, int | float) and score_val > 0 and cache is not None:
        cache.set(cache_k, dict(result))
    return result


def calc_reaction_score(
    db,
    *,
    type_id: int,
    char_config: dict | None,
    mat_source_hub: str,
    sell_hub: str,
    facility_tax_pct: float,
    price_type_mat: str,
    price_type_prod: str,
    system_id: int | None,
    structure_bonus: float,
) -> dict[str, Any]:
    """反应评分用例：编排 DB 读取 + 领域纯函数（反应无缓存）。"""
    result: dict[str, Any] = {
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

    with db.connect("ref", "mkt", "bp") as conn:
        c = conn.cursor()

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

        prod_price = _ss.get_price(type_id, price_type_prod, sell_hub, _db=db)
        if not prod_price:
            result["status"] = "no_price"
            return result

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

        materials = tuple((mat_id, _ss.resolve_item_name(conn, mat_id), mat_qty) for mat_id, mat_qty in mat_rows)

        result = _pure_reaction(
            product_type_id=type_id,
            prod_qty=prod_qty,
            base_time=base_time,
            prod_price=prod_price,
            materials=materials,
            prices=_DbPriceProvider(db),
            char_config=char_config,
            mat_source_hub=mat_source_hub,
            sell_hub=sell_hub,
            price_type_mat=price_type_mat,
            system_id=system_id,
            structure_bonus=structure_bonus,
            facility_tax_pct=facility_tax_pct,
        )

    return result

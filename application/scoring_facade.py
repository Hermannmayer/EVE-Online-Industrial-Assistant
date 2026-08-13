"""制造评分编排门面。

职责：开连接 → 取蓝图/材料/名称/价格 → 组装 BlueprintRecipe → 调 domain 纯函数 → 写缓存。

数据访问经 `services.scoring_service` 模块级函数（`_ss.get_price` 等）在调用时解析，
以保留测试对这些符号的 patch 语义（`@patch("services.scoring_service.get_price")`）。
"""

from __future__ import annotations

from typing import Any

import services.scoring_service as _ss
from domain.scoring import BlueprintRecipe, Material
from domain.scoring import calc_manufacturing_score as _pure_calc


class _DbPriceProvider:
    """PriceProvider 适配 — 委托给 scoring_service 模块级定价函数（可被测试 patch）。"""

    def __init__(self, db):
        self._db = db

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        return _ss.get_price(type_id, price_type, hub, _db=self._db)

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
        return _ss.get_volume(type_id, vol_type, hub, _db=self._db)

    def get_system_cost_index(self, system_id: int | None, activity: str = "manufacturing", hub: str = "Jita") -> float:
        return _ss.get_system_cost_index(system_id, activity, _db=self._db, hub=hub)

    def get_adjusted_price(self, type_id: int) -> float | None:
        return _ss.get_adjusted_price(type_id, _db=self._db)


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
) -> dict[str, Any]:
    """制造评分用例：编排 DB 读取 + 领域纯函数 + 缓存。"""
    char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
    cache_k = _ss.cache_key(
        type_id,
        f"mfg|{mat_source_hub}|{sell_hub}|{bp_me}|{bp_te}|{price_type_mat}|{price_type_prod}|{system_id or ''}"
        f"|{structure_bonus}|{structure_time_mod}|{structure_mat_saving}|{facility_tax_pct}|{int(is_alpha)}",
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
        recipe = BlueprintRecipe(
            product_type_id=type_id,
            blueprint_type_id=bp_id,
            prod_qty=prod_qty,
            base_time=base_time,
            materials=materials,
        )
        prices = _DbPriceProvider(db)
        research_cost = _ss._research_cost_cached(db, type_id, solar_system_id=system_id)

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
        )

    # 写入缓存（仅缓存成功结果，失败状态不缓存）
    score_val = result["score"]
    if isinstance(score_val, int | float) and score_val > 0 and cache is not None:
        cache.set(cache_k, dict(result))
    return result

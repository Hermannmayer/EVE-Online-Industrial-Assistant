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
from domain.scoring import BlueprintRecipe, Material
from domain.scoring import calc_manufacturing_score as _pure_calc
from domain.scoring import calc_reaction_score as _pure_reaction
from domain.scoring import calc_trade_score as _pure_trade


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
) -> dict[str, Any]:
    """制造评分用例：编排 DB 读取 + 领域纯函数 + 缓存。"""
    char_name = (char_config.get("name") or char_config.get("char_name") or "default") if char_config else "default"
    cache_k = _ss.cache_key(
        type_id,
        f"mfg|{mat_source_hub}|{sell_hub}|{bp_me}|{bp_te}|{price_type_mat}|{price_type_prod}|{system_id or ''}"
        f"|{structure_bonus}|{structure_time_mod}|{structure_mat_saving}|{facility_tax_pct}|{int(is_alpha)}"
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

"""待采购计算服务 — 从生产计划/库存/价格计算采购清单。"""

from __future__ import annotations

import json

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from services.manufacturing_calculator import calc_material_for_runs
from services.terminology import term


def _resolve_item_name(mid: int, zh_name: str | None, en_name: str | None) -> str:
    """统一物品名解析：item 表 → terminology.json → str(id)"""
    if zh_name:
        return zh_name
    if en_name:
        return en_name
    override = term.item_override(mid)
    if override:
        return override
    return str(mid)


def calculate_procurement(
    active_plans: list[dict],
    *,
    hangar_id: int,
    hub: str,
    price_type: str,
) -> tuple[list[dict], float, float]:
    """计算待采购清单。

    Returns:
        (rows, total_cost, total_volume)
    """
    region_id = TRADE_HUB_IDS.get(hub, 10000002)
    material_map: dict[int, dict] = {}
    sub_prod_ids = {
        p["product_type_id"]
        for p in active_plans
        if p.get("product_type_id") and int(p.get("child_level") or p.get("sub_level") or 0) > 0
    }

    with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
        c = conn.cursor()
        for plan in active_plans:
            if not plan.get("materials_ready", 0):
                continue
            pid = plan["product_type_id"]
            total_runs = plan["runs"] * plan["parallels"]
            me = plan["me_level"] or 0

            c.execute(
                "SELECT mg.meta_group_id FROM bp.blueprint_products bp "
                "LEFT JOIN item i ON i.type_id = bp.product_type_id "
                "LEFT JOIN meta_group mg ON mg.meta_group_id = i.meta_group_id "
                "WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing' LIMIT 1",
                (pid,),
            )
            mg_row = c.fetchone()
            mg_id = mg_row[0] if mg_row else None
            if mg_id == 2:
                wf = 2  # T2
            elif mg_id == 4:
                wf = 15  # 势力
            else:
                wf = 10  # T1/兜底

            c.execute(
                """SELECT bm.material_type_id, bm.quantity
                FROM bp.blueprint_products bp
                JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                    AND bm.activity = bp.activity
                WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'""",
                (pid,),
            )
            for mid, qty in c.fetchall():
                if mid in sub_prod_ids:
                    continue
                need = calc_material_for_runs(qty, wf, me, int(total_runs))
                if mid in material_map:
                    material_map[mid]["need"] += need
                else:
                    material_map[mid] = {"need": need}

        # 合并强制启动计划的材料缺口
        for plan in active_plans:
            raw = plan.get("material_short") or ""
            if not raw:
                continue
            try:
                short = json.loads(raw)
            except Exception:
                continue
            for mid_str, missing in short.items():
                try:
                    mid = int(mid_str)
                except ValueError:
                    continue
                if mid in material_map:
                    material_map[mid]["need"] += int(missing)
                else:
                    material_map[mid] = {"need": int(missing)}

        inv_map: dict[int, float] = {}
        c.execute("SELECT type_id, quantity FROM inventory_items WHERE hangar_id = ?", (hangar_id,))
        for tid, qty in c.fetchall():
            inv_map[tid] = qty

        rows: list[dict] = []
        total_cost = 0.0
        total_volume = 0.0
        for mid, info in material_map.items():
            need = info["need"]
            owned = inv_map.get(mid, 0)
            to_buy = max(0, need - owned)

            c.execute("SELECT zh_name, en_name, volume FROM ref.item WHERE type_id = ?", (mid,))
            r = c.fetchone()
            zh_name = r[0] if r else None
            en_name = r[1] if r else None
            name = _resolve_item_name(mid, zh_name, en_name)
            volume = r[2] if r and r[2] else 0.01

            col = f"{price_type}_price"
            c.execute(
                f"SELECT {col} FROM mkt.market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (mid, region_id),
            )
            pr = c.fetchone()
            price = pr[0] if pr and pr[0] else 0.0

            subtotal = to_buy * price
            total_cost += subtotal
            total_volume += to_buy * volume

            rows.append(
                {
                    "type_id": mid,
                    "name": name,
                    "zh_name": zh_name,
                    "en_name": en_name,
                    "need": need,
                    "owned": owned,
                    "to_buy": to_buy,
                    "price": price,
                    "total": subtotal,
                    "volume": to_buy * volume,
                }
            )

    rows.sort(key=lambda x: x["total"], reverse=True)
    return rows, total_cost, total_volume

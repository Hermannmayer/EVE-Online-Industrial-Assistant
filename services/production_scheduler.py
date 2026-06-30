"""
生产排程优化 — 基于材料需求和生产计划的排程

功能:
  - analyze_production_plan: 分析单个生产计划的材料需求和成本
  - get_all_plans_summary:   获取所有生产计划概览
  - suggest_production_order: 建议生产排序
  - optimize_material_purchase: 优化材料采购（有限预算）
"""

from __future__ import annotations

import sqlite3

from services.database_manager import get_db

db = get_db()


# ── 内部辅助 ──


def _get_plan(conn: sqlite3.Connection, plan_id: int) -> dict | None:
    """从 user.db 读取单条 production_plans 记录"""
    row = conn.execute("SELECT * FROM production_plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(row) if row else None


def _get_item_name(conn: sqlite3.Connection, type_id: int) -> str:
    """从 ref.item 获取物品名称"""
    row = conn.execute(
        "SELECT zh_name, en_name FROM ref.item WHERE type_id = ?",
        (type_id,),
    ).fetchone()
    if row:
        return row[0] or row[1] or str(type_id)
    return str(type_id)


def _get_blueprint_for_product(conn: sqlite3.Connection, product_type_id: int) -> tuple[int | None, int]:
    """根据 product_type_id 找到 blueprint_type_id 和默认产量"""
    row = conn.execute(
        """SELECT bp.blueprint_type_id, bp.quantity
           FROM bp.blueprint_products bp
           WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
           LIMIT 1""",
        (product_type_id,),
    ).fetchone()
    if row:
        return row[0], row[1] or 1
    return None, 1


def _get_materials(conn: sqlite3.Connection, blueprint_type_id: int) -> list[tuple[int, int]]:
    """获取蓝图的 (material_type_id, base_quantity) 列表"""
    rows = conn.execute(
        """SELECT material_type_id, quantity
           FROM bp.blueprint_materials
           WHERE blueprint_type_id = ? AND activity = 'manufacturing'""",
        (blueprint_type_id,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _get_price(conn: sqlite3.Connection, type_id: int, hub: str = "Jita") -> float:
    """获取物品在指定 Hub 的卖价"""
    region_map = {
        "Jita": 10000002,
        "Amarr": 10000043,
        "Dodixie": 10000032,
        "Rens": 10000030,
        "Hek": 10000028,
    }
    region_id = region_map.get(hub, 10000002)
    row = conn.execute(
        """SELECT sell_price FROM mkt.market_prices
           WHERE type_id = ? AND region_id = ? LIMIT 1""",
        (type_id, region_id),
    ).fetchone()
    return row[0] if row and row[0] else 0.0


def _get_inventory_qty(conn: sqlite3.Connection, type_id: int) -> float:
    """获取用户库存中该 type_id 的总数量"""
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM inventory_items WHERE type_id = ?",
        (type_id,),
    ).fetchone()
    return float(row[0]) if row else 0.0


# ════════════════════════════════════════════════════
#  核心 API
# ════════════════════════════════════════════════════


def analyze_production_plan(
    plan_id: int,
    char_config: dict | None = None,
    price_hub: str = "Jita",
) -> dict:
    """分析单个生产计划的材料需求和成本。

    Args:
        plan_id: production_plans.id
        char_config: 人物技能配置（可选，当前未用于简化计算）
        price_hub: 价格查询的贸易中心

    Returns:
        包含材料明细、缺少材料、总成本等信息的字典。
        若找不到计划，返回 {"status": "not_found"}。
    """
    with db.connect("user", "ref", "mkt", "bp") as conn:
        plan = _get_plan(conn, plan_id)
        if not plan:
            return {"status": "not_found", "plan_id": plan_id}

        product_type_id = plan["product_type_id"]
        product_name = plan.get("product_name") or _get_item_name(conn, product_type_id)
        runs = plan.get("runs", 1) or 1
        parallels = plan.get("parallels", 1) or 1
        me_level = plan.get("me_level", 0) or 0

        # 找蓝图
        bp_id, prod_qty_per_run = _get_blueprint_for_product(conn, product_type_id)
        if not bp_id:
            return {
                "status": "no_blueprint",
                "plan_id": plan_id,
                "product_name": product_name,
                "quantity": runs * parallels,
            }

        # 查材料
        raw_mats = _get_materials(conn, bp_id)
        if not raw_mats:
            return {
                "status": "no_materials",
                "plan_id": plan_id,
                "product_name": product_name,
                "quantity": runs * parallels,
            }

        # ME 浪费因子: ME 0 → 1.1, ME 10 → 1.0
        from core.eve_formulas import ME_WASTE_BASE

        waste_factor = 1 + ME_WASTE_BASE * (1 - me_level / 10)

        total_product_qty = runs * parallels * (prod_qty_per_run or 1)
        total_mat_cost = 0.0
        missing_materials: list[dict] = []
        material_count = len(raw_mats)
        has_all = True

        for mat_id, base_qty in raw_mats:
            needed = base_qty * waste_factor * runs * parallels
            available = _get_inventory_qty(conn, mat_id)
            price = _get_price(conn, mat_id, price_hub)
            subtotal = needed * price
            total_mat_cost += subtotal
            deficit = max(0.0, needed - available)
            mat_name = _get_item_name(conn, mat_id)
            if deficit > 0:
                has_all = False
                missing_materials.append(
                    {
                        "type_id": mat_id,
                        "name": mat_name,
                        "needed": round(needed, 2),
                        "available": round(available, 2),
                        "deficit": round(deficit, 2),
                        "cost": round(deficit * price, 2),
                    }
                )

        # 按缺料成本降序
        missing_materials.sort(key=lambda m: m["cost"], reverse=True)

        return {
            "plan_id": plan_id,
            "product_type_id": product_type_id,
            "product_name": product_name,
            "quantity": total_product_qty,
            "material_count": material_count,
            "has_all_materials": has_all,
            "missing_materials": missing_materials,
            "total_material_cost": round(total_mat_cost, 2),
            "status": plan.get("status", "pending"),
        }


def get_all_plans_summary(
    char_config: dict | None = None,
    price_hub: str = "Jita",
) -> list[dict]:
    """获取所有生产计划的概览列表，按依赖关系排序。

    每条包含: plan_id, product_name, quantity, status, profit,
              material_cost, has_all_materials, missing_count。

    用于 UI 显示计划列表。
    """
    with db.connect("user", "ref", "mkt", "bp") as conn:
        rows = conn.execute("SELECT id FROM production_plans ORDER BY created_at DESC").fetchall()

    summaries: list[dict] = []
    for (pid,) in rows:
        analysis = analyze_production_plan(pid, char_config, price_hub)
        if analysis.get("status") == "not_found":
            continue
        summaries.append(
            {
                "plan_id": analysis["plan_id"],
                "product_name": analysis.get("product_name", ""),
                "quantity": analysis.get("quantity", 0),
                "status": analysis.get("status", "pending"),
                "material_cost": analysis.get("total_material_cost", 0),
                "has_all_materials": analysis.get("has_all_materials", False),
                "missing_count": len(analysis.get("missing_materials", [])),
                "material_count": analysis.get("material_count", 0),
            }
        )

    # 排序: 有原料的在前，缺料少的在前
    summaries.sort(key=lambda s: (not s["has_all_materials"], s["missing_count"]))
    return summaries


def suggest_production_order(
    char_config: dict | None = None,
    price_hub: str = "Jita",
) -> list[dict]:
    """对所有 pending 状态的生产计划，按依赖关系排序建议生产顺序。

    排序逻辑:
      1. 没有前置依赖的排前面（造原料的先造）
      2. 已有全部材料的优先
      3. 按利润率倒序（利润高的优先）
      4. 按缺料数量正序（快完成的先做）

    返回: [{"plan_id", "product_name", "rank", "reason", ...}, ...]
    """
    with db.connect("user", "ref", "mkt", "bp") as conn:
        rows = conn.execute("SELECT id FROM production_plans WHERE status = 'pending'").fetchall()

    if not rows:
        return []

    # 检查每个计划的产物是否是另一个计划的原料（有前置依赖）
    def _is_intermediate(pid: int) -> bool:
        """判断该计划的产物是否被其他 pending 计划作为原料使用"""
        with db.connect("user", "bp") as conn2:
            p = _get_plan(conn2, pid)
            if not p:
                return False
            ptid = p["product_type_id"]
            # 检查 ptid 是否出现在其他 pending 计划的蓝图材料中
            row = conn2.execute(
                """SELECT 1
                   FROM production_plans pp
                   JOIN bp.blueprint_products bp2
                     ON bp2.product_type_id = pp.product_type_id
                      AND bp2.activity = 'manufacturing'
                   JOIN bp.blueprint_materials bm
                     ON bm.blueprint_type_id = bp2.blueprint_type_id
                      AND bm.activity = 'manufacturing'
                   WHERE pp.status = 'pending'
                     AND bm.material_type_id = ?
                     AND pp.id != ?
                   LIMIT 1""",
                (ptid, pid),
            ).fetchone()
            return row is not None

    items: list[dict] = []
    for (pid,) in rows:
        analysis = analyze_production_plan(pid, char_config, price_hub)
        if analysis.get("status") == "not_found":
            continue
        is_dep = _is_intermediate(pid)
        items.append(
            {
                "plan_id": pid,
                "product_name": analysis.get("product_name", ""),
                "quantity": analysis.get("quantity", 0),
                "material_cost": analysis.get("total_material_cost", 0),
                "has_all_materials": analysis.get("has_all_materials", False),
                "missing_count": len(analysis.get("missing_materials", [])),
                "is_intermediate": is_dep,
                "status": analysis.get("status", "pending"),
                # 用 profit 字段辅助排序（从 production_plans 读取）
            }
        )

    # 从 user.db 补充 profit/score 字段用于排序
    with db.connect("user") as conn3:
        for it in items:
            row = conn3.execute(
                "SELECT profit, score FROM production_plans WHERE id = ?",
                (it["plan_id"],),
            ).fetchone()
            if row:
                it["profit"] = row[0] or 0
                it["score"] = row[1] or 0
            else:
                it["profit"] = 0
                it["score"] = 0

    # 排序
    def _sort_key(it: dict) -> tuple:
        return (
            not it["is_intermediate"],  # 中间产物优先（True=1 > False=0）
            not it["has_all_materials"],  # 有材料优先
            it["missing_count"],  # 缺料少优先
            -(it["profit"] or 0),  # 利润高优先（负号反转）
        )

    items.sort(key=_sort_key)

    # 附加排序理由
    result: list[dict] = []
    for rank, it in enumerate(items, 1):
        reasons: list[str] = []
        if it["is_intermediate"]:
            reasons.append("产物是其他计划的原料，应优先制造")
        if it["has_all_materials"]:
            reasons.append("材料已齐全，可立即开工")
        else:
            reasons.append(f"缺少 {it['missing_count']} 种材料")
        if it["profit"] > 0:
            reasons.append(f"利润 {it['profit']:,.0f} ISK")

        result.append(
            {
                **it,
                "rank": rank,
                "reason": "; ".join(reasons),
            }
        )

    return result


def optimize_material_purchase(
    plan_ids: list[int],
    price_hub: str = "Jita",
    budget: float | None = None,
) -> dict:
    """在有限预算下优化材料采购，优先购买关键材料。

    Args:
        plan_ids: 要考虑的生产计划 ID 列表
        price_hub: 价格查询的贸易中心
        budget: 预算上限（None = 不限）

    Returns:
        {
            "purchase_list": [{"type_id", "name", "qty", "cost", "priority"}, ...],
            "total_cost": float,
            "budget_remaining": float | None,
        }
    """
    # 汇总所有计划的缺料需求
    material_demand: dict[int, dict] = {}  # type_id → {name, deficit, cost, needed, plans}

    for pid in plan_ids:
        analysis = analyze_production_plan(pid, price_hub=price_hub)
        if analysis.get("status") in ("not_found", "no_blueprint", "no_materials"):
            continue
        for m in analysis.get("missing_materials", []):
            tid = m["type_id"]
            if tid not in material_demand:
                material_demand[tid] = {
                    "type_id": tid,
                    "name": m["name"],
                    "deficit": 0.0,
                    "total_cost": 0.0,
                    "plans": [],
                }
            material_demand[tid]["deficit"] += m["deficit"]
            material_demand[tid]["total_cost"] += m["cost"]
            if pid not in material_demand[tid]["plans"]:
                material_demand[tid]["plans"].append(pid)

    if not material_demand:
        return {
            "purchase_list": [],
            "total_cost": 0,
            "budget_remaining": budget,
        }

    # 按单位成本/影响排序: 先买便宜的（覆盖更多计划）
    # 优先级: 影响计划数多的 > 总成本高的
    for item in material_demand.values():
        item["priority_score"] = len(item["plans"]) * 1000 + item["total_cost"]

    items = sorted(
        material_demand.values(),
        key=lambda x: x["priority_score"],
        reverse=True,
    )

    purchase_list: list[dict] = []
    total_cost = 0.0
    remaining = budget

    for item in items:
        unit_price = item["total_cost"] / item["deficit"] if item["deficit"] > 0 else 0
        qty = item["deficit"]

        # 预算限制
        if remaining is not None:
            if remaining <= 0:
                break
            max_affordable = remaining / unit_price if unit_price > 0 else 0
            qty = min(qty, max_affordable)

        cost = qty * unit_price
        total_cost += cost
        if remaining is not None:
            remaining -= cost

        priority = "critical" if len(item["plans"]) >= 3 else "high" if len(item["plans"]) >= 2 else "normal"

        purchase_list.append(
            {
                "type_id": item["type_id"],
                "name": item["name"],
                "qty": round(qty, 2),
                "cost": round(cost, 2),
                "priority": priority,
                "plan_count": len(item["plans"]),
            }
        )

    return {
        "purchase_list": purchase_list,
        "total_cost": round(total_cost, 2),
        "budget_remaining": round(remaining, 2) if remaining is not None else None,
    }

"""生产计划递归拆解 — 把母项拆成子项产线（sub_level 逐级 +1）。

只拆 activity='manufacturing'（组件）；反应物按外购叶子，不拆；
无深度上限（递归到叶子）；按材料机库库存减流程；
子项 ME/TE 读库存蓝图最优等级，无蓝图 → 0/0 且 has_blueprint=False。

连接约定：ref 主库含蓝图表（未限定查询解析到 ref），user 附随含 user_blueprints（限定 user.）。
"""

from __future__ import annotations

import math
from sqlite3 import Connection

from core.container import get_container
from services import inventory_manager
from services.bom_expander import _find_blueprint_for_product, _get_materials
from services.manufacturing_calculator import calc_material_for_runs


def best_inventory_blueprint(conn: Connection, blueprint_type_id: int) -> dict | None:
    """从 user_blueprints 挑 ME 最优的库存蓝图 → {me_level, te_level}；无则 None。

    BPO 优先 → ME 高者优先 → TE 高者优先。
    """
    row = conn.execute(
        "SELECT me_level, te_level FROM user.user_blueprints WHERE blueprint_type_id=? "
        "ORDER BY is_bpo DESC, me_level DESC, te_level DESC LIMIT 1",
        (blueprint_type_id,),
    ).fetchone()
    if not row:
        return None
    return {"me_level": int(row[0]), "te_level": int(row[1])}


def decompose_plan(plan: dict, *, mat_hangar_id: int | None = None) -> list[dict]:
    """递归拆解母项 → 子项产线行列表（不含母项自身）。

    返回 [{product_type_id, blueprint_type_id, sub_level, runs, parallels:1,
           me_level, te_level, has_blueprint}]。
    """
    stock = inventory_manager.get_hangar_stock(mat_hangar_id) if mat_hangar_id else {}
    parent_me = int(plan.get("me_level") or 0)
    root_runs = max(int(plan.get("runs") or 1), 1) * max(int(plan.get("parallels") or 1), 1)

    with get_container().db.connect("ref", "user") as conn:
        bp = _find_blueprint_for_product(conn, plan["product_type_id"], "manufacturing")
        if not bp:
            return []
        bp_id, _output_qty, _ = bp
        lines: list[dict] = []
        for mat_id, mat_base in _get_materials(conn, bp_id, "manufacturing"):
            child_qty = calc_material_for_runs(mat_base, 10, parent_me, root_runs)
            cl, _ = _decompose(conn, mat_id, child_qty, depth=1, stock=stock, seen=set())
            lines.extend(cl)
        return lines


def parent_needs(conn: Connection, group_plans: list[dict]) -> dict[int, int]:
    """组内全部母项（sub_level=0）对每个直接组件的总需求 {type_id: need}。

    conn: ref 主库（含蓝图表）。
    """
    needs: dict[int, int] = {}
    parents = [p for p in group_plans if int(p.get("sub_level") or 0) == 0]
    for p in parents:
        root_runs = max(int(p.get("runs") or 1), 1) * max(int(p.get("parallels") or 1), 1)
        parent_me = int(p.get("me_level") or 0)
        bp = _find_blueprint_for_product(conn, p["product_type_id"], "manufacturing")
        if not bp:
            continue
        for mat_id, mat_base in _get_materials(conn, bp[0], "manufacturing"):
            qty = calc_material_for_runs(mat_base, 10, parent_me, root_runs)
            needs[mat_id] = needs.get(mat_id, 0) + qty
    return needs


def _decompose(
    conn: Connection,
    type_id: int,
    needed_qty: float,
    depth: int,
    stock: dict[int, int],
    seen: set[int],
) -> tuple[list[dict], int]:
    """递归展开一层。返回 (子项产线行, 本层可被库存覆盖的产出量)。"""
    bp = _find_blueprint_for_product(conn, type_id, "manufacturing")
    if not bp:
        return [], 0  # 叶子（外购原料），无产线
    bp_id, output_qty, _ = bp
    output_qty = output_qty or 1
    runs = math.ceil(needed_qty / output_qty)
    onhand = int(stock.get(type_id, 0))
    covered = min(runs, onhand // max(output_qty, 1))  # 库存能覆盖的轮次
    make_runs = max(0, runs - covered)
    if make_runs <= 0 or type_id in seen:
        return [], covered * output_qty  # 全库存覆盖 或 循环防护

    seen.add(type_id)
    try:
        ibp = best_inventory_blueprint(conn, bp_id)
        me = ibp["me_level"] if ibp else 0
        lines: list[dict] = [
            {
                "product_type_id": type_id,
                "blueprint_type_id": bp_id,
                "sub_level": depth,
                "runs": make_runs,
                "parallels": 1,
                "me_level": me,
                "te_level": ibp["te_level"] if ibp else 0,
                "has_blueprint": ibp is not None,
            }
        ]
        for mat_id, mat_base in _get_materials(conn, bp_id, "manufacturing"):
            child_qty = calc_material_for_runs(mat_base, 10, me, make_runs)
            cl, _ = _decompose(conn, mat_id, child_qty, depth + 1, stock, seen)
            lines.extend(cl)
        return lines, covered * output_qty
    finally:
        seen.discard(type_id)

"""生产计划递归拆解 — 把母项拆成子项产线（sub_level 逐级 +1）。

只拆 activity='manufacturing'（组件）；反应物按外购叶子，不拆；
无深度上限（递归到叶子）；按材料机库库存减流程；
子项 ME/TE 读库存蓝图最优等级，无蓝图 → 0/0 且 has_blueprint=False。

连接约定：ref 主库（物品/星系表），bp 附随含蓝图表（未限定查询经附随解析到 bp），
user 附随含 user_blueprints（限定 user.）。
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

    每个子项的 runs 按母项对它的材料总需求（demand）1X 生成：
    runs = ceil(demand / 单轮产出)，parallels=1，总产出 ≥ demand（最小超产）。

    返回 [{product_type_id, blueprint_type_id, sub_level, demand, runs, parallels:1,
           me_level, te_level, has_blueprint}]。
    """
    stock = inventory_manager.get_hangar_stock(mat_hangar_id) if mat_hangar_id else {}
    parent_me = int(plan.get("me_level") or 0)
    root_runs = max(int(plan.get("runs") or 1), 1) * max(int(plan.get("parallels") or 1), 1)

    with get_container().db.connect("ref", "user", "bp") as conn:
        bp = _find_blueprint_for_product(conn, plan["product_type_id"], "manufacturing")
        if not bp:
            return []
        bp_id, _output_qty, _ = bp
        lines: list[dict] = []
        for mat_id, mat_base in _get_materials(conn, bp_id, "manufacturing"):
            child_qty = calc_material_for_runs(mat_base, 10, parent_me, root_runs)
            cl, _ = _decompose(conn, mat_id, child_qty, depth=1, stock=stock, seen=set(), mat_hangar_id=mat_hangar_id)
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


def is_leaf_plan(plan: dict, all_plans: list[dict]) -> bool:
    """该计划是否为叶子产线（组内无更深子项）。

    母项拆解后母项的直接材料 = 子项（自制件），不应再计入待采购；
    只有叶子产线（无子项的普通计划、或拆解组内最深子项）的原材料才需采购。
    """
    gid = plan.get("group_id") or plan.get("group_number")
    if not gid:
        return True
    lvl = int(plan.get("child_level") or plan.get("sub_level") or 0)
    return not any(
        (p.get("group_id") or p.get("group_number")) == gid
        and int(p.get("child_level") or p.get("sub_level") or 0) > lvl
        for p in all_plans
    )


def collect_cascade_delete_ids(plans: list[dict], selected_ids: set[int]) -> set[int]:
    """删除指定计划时级联删除同组更深子项（含传递层级）。

    plans: 全量计划；selected_ids: 用户选中删除的计划 id。
    规则：计划 P 被删 → 同 group 内 sub_level 比 P 深的子项一并删除（母项 sub_level=0 删全部子项）。
    迭代直至稳定，处理嵌套拆解（删 1 级 → 连带删 2 级…）。
    """

    def _gid(p: dict):
        return p.get("group_id") or p.get("group_number")

    def _lvl(p: dict) -> int:
        return int(p.get("child_level") or p.get("sub_level") or 0)

    ids = set(selected_ids)
    changed = True
    while changed:
        changed = False
        for p in plans:
            if not p.get("id") or p["id"] in ids:
                continue
            gid = _gid(p)
            if not gid:
                continue
            for sp in plans:
                if not sp.get("id") or sp["id"] not in ids:
                    continue
                if _gid(sp) == gid and _lvl(sp) < _lvl(p):
                    ids.add(p["id"])
                    changed = True
                    break
    return ids


def collect_group_members(all_plans: list[dict], selected: list[dict]) -> tuple[list[dict], list[dict]]:
    """跨选中行聚合相关组的母项与子项（按 plan id 去重）→ (parents, children)。

    组号取选中行的 group_id（UI 层已映射自 DB group_number）；遍历全量计划把同组行
    按 child_level==0 分入母项/其余子项，再把选中行中的游离母项并入 parents
    （覆盖"选了游离母项但组号未落库"的情形）。
    """
    group_ids = {p["group_id"] for p in selected if p.get("group_id")}
    parents: list[dict] = []
    children: list[dict] = []
    seen_parent: set = set()
    seen_child: set = set()

    def _key(p: dict) -> int:
        pid = p.get("id")
        return int(pid) if pid is not None else id(p)

    for p in all_plans:
        if not p.get("group_id") or p["group_id"] not in group_ids:
            continue
        k = _key(p)
        if int(p.get("child_level") or 0) == 0:
            if k not in seen_parent:
                seen_parent.add(k)
                parents.append(p)
        elif k not in seen_child:
            seen_child.add(k)
            children.append(p)
    # 选中行中的游离母项并入（组号可能未落库/未在 all_plans 命中）
    for p in selected:
        if int(p.get("child_level") or 0) == 0:
            k = _key(p)
            if k not in seen_parent:
                seen_parent.add(k)
                parents.append(p)
    return parents, children


def _decompose(
    conn: Connection,
    type_id: int,
    needed_qty: float,
    depth: int,
    stock: dict[int, int],
    seen: set[int],
    mat_hangar_id: int | None = None,
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
                "demand": needed_qty,
                "runs": make_runs,
                "parallels": 1,
                "me_level": me,
                "te_level": ibp["te_level"] if ibp else 0,
                "has_blueprint": ibp is not None,
                "deposit_hangar_id": mat_hangar_id,
            }
        ]
        for mat_id, mat_base in _get_materials(conn, bp_id, "manufacturing"):
            child_qty = calc_material_for_runs(mat_base, 10, me, make_runs)
            cl, _ = _decompose(conn, mat_id, child_qty, depth + 1, stock, seen, mat_hangar_id=mat_hangar_id)
            lines.extend(cl)
        return lines, covered * output_qty
    finally:
        seen.discard(type_id)

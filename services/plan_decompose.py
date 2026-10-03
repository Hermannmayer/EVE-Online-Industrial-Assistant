"""生产计划递归拆解 — 把母项拆成子项产线（sub_level 逐级 +1）。

只拆 activity='manufacturing'（组件）；反应物按外购叶子，不拆；
无深度上限（递归到叶子）；按材料机库库存减流程；
子项 ME/TE 读库存蓝图最优等级，无蓝图 → 0/0 且 has_blueprint=False。

连接约定：ref 主库（物品/星系表），bp 附随含蓝图表（未限定查询经附随解析到 bp），
user 附随含 user_blueprints / user.production_plans（限定 user.）。
"""

from __future__ import annotations

from sqlite3 import Connection

from core.container import get_container
from domain.formulas import calc_material_for_runs
from services import inventory_manager
from services.bom_expander import _find_blueprint_for_product, _get_materials


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


def _existing_parallels(conn: Connection) -> dict[int, int]:
    """全库既有子项产线的并行数 {product_type_id: parallels} —— 口径同落库侧。

    `plan_rebuild.rebuild_children` 的 `existing_parallels` 取自它对全库 `sub_level>0` 行的
    归并（`children_by_tid`：同 product_type_id 只留一行，「部分启动」拆出的
    「在产行 + pending 余量行」优先留**在产**那条）。预览必须用同一条规则取并行数，否则
    同一行会给出「预览 12 轮 × 1 线」而「落库 3 轮 × 5 线」（实测母项 311 的 41484）。
    **改这条归并规则必须同步改 `plan_rebuild.rebuild_children`。**
    """
    locked = {"in_progress", "running"}
    kept: dict[int, tuple[int, bool]] = {}
    for r in conn.execute(
        "SELECT product_type_id, parallels, status FROM user.production_plans WHERE sub_level > 0 ORDER BY id"
    ).fetchall():
        tid = int(r["product_type_id"] or 0)
        cur = (int(r["parallels"] or 1), (r["status"] or "").lower() in locked)
        prev = kept.get(tid)
        if prev is None or (cur[1] and not prev[1]):
            kept[tid] = cur
    return {tid: p for tid, (p, _locked) in kept.items()}


def decompose_plan(plan: dict, *, mat_hangar_id: int | None = None) -> list[dict]:
    """递归拆解母项 → 子项产线行列表（不含母项自身）。

    **直接复用落库那条路径**（`services.plan_rebuild.compute_child_forest` + `_finalize_runs`）：
    对话框预览和确认后写进表里的必须是同一组 runs/parallels，两处各维护一套折算公式就必然
    出现「预览说 1360、落库是 2040」的剪刀差（旧实现：ceil 且 parallels 恒为 1、自己再扣一次
    库存、库存覆盖到 0 就整行不建）。这里只传**这一个母项**，所以需求传播退化成单母项展开；
    库存按该母项的制造机库取快照（键 = 母项 id，与 `_finalize_runs` 的 `first_mother` 同源）；
    `existing_parallels` 取全库既有子项行的并行数（见 `_existing_parallels`）—— 用户设过并行的
    行落库时保留并行、runs 按并行摊（实测 41484：5 线 → 3 轮），预览不跟着取就会又是两套数字。

    返回按 (sub_level, product_type_id) 稳定排序的
    [{product_type_id, blueprint_type_id, sub_level, demand, runs, parallels,
      me_level, te_level, has_blueprint}]；母项无蓝图（拆不出任何子项）时返回 []。

    ⚠️ 已知残差（本函数只拆一个母项，落库按全库活跃母项传播）：被**别的活跃母项**共享的
    组件，需求只算了本母项那一份，而 `rebuild_children` 会累加所有引用者（实测 11482：
    预览 1 轮 / 落库 2 轮）。要消掉它得把全库活跃母项都传进来 —— 那会让预览显示的是别的
    母项的需求，与「这条母项的拆解预览」不符，故不做。
    """
    # 函数内导入：`services.plan_rebuild` 反向依赖本模块的 `best_inventory_blueprint`，
    # 模块级导入会成环。
    from services.plan_rebuild import compute_child_forest

    stock = inventory_manager.get_hangar_stock(mat_hangar_id) if mat_hangar_id else {}
    stocks = {int(plan.get("id") or 0): stock}

    with get_container().db.connect("ref", "user", "bp") as conn:
        nodes = compute_child_forest(conn, [plan], stocks, _existing_parallels(conn))

    return [
        {
            "product_type_id": int(n["product_type_id"]),
            "blueprint_type_id": int(n["blueprint_type_id"]),
            "sub_level": int(n["sub_level"]),
            "demand": int(n["demand"]),
            "runs": int(n["runs"]),
            "parallels": int(n["parallels"]),
            "me_level": int(n["me_level"]),
            "te_level": int(n["te_level"]),
            "has_blueprint": bool(n["has_blueprint"]),
        }
        for n in sorted(nodes.values(), key=lambda n: (int(n["sub_level"]), int(n["product_type_id"])))
    ]


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


def collect_removed_child_ids(rows: list[dict], removed_type_ids: set[int]) -> set[int]:
    """母项拆解删除集：被删组件类型的合并子项行 + 其同组子孙（沿 component_parent_type_id）。

    子项按 product_type_id 全局合并：命中类型的所有 child 行作种子（含跨组共享行）；
    同组内沿 component_parent_type_id 传递删除子孙。不按 sub_level 比较——避免兄弟组件
    因层级差被误连带删除。仅处理 sub_level>0 的子项行，不含母项。
    """
    removed = {int(t) for t in removed_type_ids if t}
    if not removed:
        return set()
    children = [r for r in rows if int(r.get("sub_level") or 0) > 0]
    children_of: dict[tuple[int, int], list[dict]] = {}  # (group, parent_type) -> [child rows]
    ids: set[int] = set()
    frontier: list[dict] = []
    for r in children:
        g = int(r.get("group_number") or 0)
        t = int(r.get("product_type_id") or 0)
        p = r.get("component_parent_type_id")
        if p:
            children_of.setdefault((g, int(p)), []).append(r)
        if t in removed:
            ids.add(int(r["id"]))
            frontier.append(r)
    while frontier:
        r = frontier.pop()
        g = int(r.get("group_number") or 0)
        t = int(r.get("product_type_id") or 0)
        for child in children_of.get((g, t), []):
            cid = int(child["id"])
            if cid not in ids:
                ids.add(cid)
                frontier.append(child)
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

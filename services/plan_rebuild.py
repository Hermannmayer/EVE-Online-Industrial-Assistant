"""生产计划子项全量重放 — 把母项拆解从「静态快照」升级为「引用式 + 幂等重放」。

设计：
- 子项需求改为引用式：每个子项行记录被哪些母项引用（source_mother_ids），
  需求（demand）= 所有引用母项按各自当前 runs×parallels×ME 折算的用量之和。
- rebuild_children() 全量重放：读所有活跃母项 → 沿 BOM 全局传播需求 →
  与 DB 现有子项 diff 后单事务落库。天然幂等（输入不变则算集不变，diff 为空），
  自动支持：编辑母项后子项联动、共享组件跨母项合并为一行、删除母项后需求收缩。
- 不依赖 group_number 的唯一性；共享节点挂在首个引用母项的组下（阶段3升级为独立共享区）。
"""

from __future__ import annotations

import math

from core.container import get_container
from core.logger import log
from services import inventory_manager
from services.bom_expander import _find_blueprint_for_product, _get_materials
from services.manufacturing_calculator import calc_material_for_runs
from services.plan_decompose import best_inventory_blueprint

# 迭代收敛上限：跨层共享的组件需求在 2-3 轮内稳定，留足余量。
_MAX_ROUNDS = 10

# 母项参与重放的排除状态
_DONE_STATUSES = ("completed", "done")
_LOCKED_RUNS_STATUSES = ("in_progress", "running")  # 已投产的子项 runs 不再改动


def _is_active(row: dict) -> bool:
    return (row.get("status") or "").lower() not in _DONE_STATUSES


def _is_locked(row: dict) -> bool:
    return (row.get("status") or "").lower() in _LOCKED_RUNS_STATUSES


def _mother_key(row: dict) -> int:
    return int(row.get("id") or 0)


def _sub_level(row: dict) -> int:
    return int(row.get("sub_level") or 0)


def _group_of(row: dict) -> int:
    return int(row.get("group_number") or 0)


def _parse_sources(row: dict) -> set[int]:
    raw = (row.get("source_mother_ids") or "").strip()
    if not raw:
        return set()
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def _collect_mothers(all_rows: list[dict]) -> list[dict]:
    """识别母项：sub_level=0 且（旧式 group>0 或被子项 source 引用/自身带 source 的拆解母项）。"""
    referenced: set[int] = set()
    for r in all_rows:
        if _sub_level(r) > 0:
            referenced |= _parse_sources(r)
    mothers: list[dict] = []
    for r in all_rows:
        if _sub_level(r) != 0:
            continue
        if _group_of(r) > 0 or _mother_key(r) in referenced:
            mothers.append(r)
    return mothers


def _accumulate(
    conn,
    nodes: dict[int, dict],
    first_mother: dict,
    type_id: int,
    qty: int,
    level: int,
    parent_type_id: int,
    existing_parallels: dict[int, int],
) -> None:
    """把 qty 记到 `type_id` 的需求上，并补全节点元数据。**这里不算 runs**。

    runs 由 `compute_child_forest` 在「本轮需求收齐之后、展开下级之前」统一定稿
    （`_finalize_runs`）—— 算早了就是拿半份需求去除并行数，见那边关于共享中间件的说明。
    """
    if qty <= 0:
        return
    bp = _find_blueprint_for_product(conn, type_id, "manufacturing")
    if not bp:
        return
    bp_id, output_qty, _ = bp
    node = nodes.setdefault(
        type_id,
        {
            "product_type_id": type_id,
            "blueprint_type_id": bp_id,
            "output_qty": output_qty or 1,
            "demand": 0,
            "runs": 0,
            "parallels": int(existing_parallels.get(type_id, 1) or 1),  # 保留用户既有并行
            "me_level": 0,
            "te_level": 0,
            "has_blueprint": False,
            "sub_level": 99,
            "sources": set(),
            "parents": set(),
            "first_mother": first_mother,
        },
    )
    if _sub_level(first_mother) == 0:  # 仅母项来源计入 source 引用
        node["sources"].add(int(first_mother.get("id") or 0))
    node["parents"].add(parent_type_id)
    if level < node["sub_level"]:
        node["sub_level"] = level
    node["demand"] += qty

    ibp = best_inventory_blueprint(conn, bp_id)
    node["me_level"] = ibp["me_level"] if ibp else 0
    node["te_level"] = ibp["te_level"] if ibp else 0
    node["has_blueprint"] = ibp is not None
    node["blueprint_type_id"] = bp_id


def _finalize_runs(node: dict, stocks: dict[int, dict[int, int]]) -> None:
    """把本轮收齐的 demand 折算成 runs（含「首个引用母项机库」的库存覆盖）。"""
    output_qty = max(int(node.get("output_qty") or 1), 1)
    # 库存覆盖：取首个引用母项的机库库存 na 数量 → 可抵消的轮次
    stock = stocks.get(int((node.get("first_mother") or {}).get("id") or 0), {})
    covered = int(stock.get(int(node.get("product_type_id") or 0), 0)) // output_qty
    parallels = max(int(node.get("parallels") or 1), 1)
    node["runs"] = max(0, math.ceil(int(node["demand"]) / (parallels * output_qty)) - covered)


def compute_child_forest(
    conn, active_mothers: list[dict], stocks: dict[int, dict[int, int]], existing_parallels: dict[int, int]
) -> dict[int, dict]:
    """全局需求传播 → {type_id: node}。

    共享组件跨母项/跨层级需求自动累加为一行；existing_parallels 保留用户既有并行产线设定。

    迭代形态：**每轮先把需求累齐，再定稿 runs，最后才拿 runs 去展开下级；每个节点每轮只展开一次。**
    这是这套传播的命门，两个坑都出在违反它的时候：

    - **别在累需求的过程中折算 runs**。曾经的写法是每个母项各展开一遍，节点一收到需求就
      立刻算 runs 并用它展开下级 —— 共享中间件于是被展开两次：第一次按第一个母项的**部分**
      需求算出的 runs，第二次按收齐后的 runs。下级的 demand 直接翻倍（实测 60 被算成 80）。
    - **别用短路写递归**。曾经的 `changed = changed or _propagate(...)` 在本节点 runs 有变化时
      根本不往下走 —— 而「正在变」恰恰是最该往下走的时候。多母项共享中间件时每轮都在变，
      于是 level≥2 永远进不了 `nodes`；更糟的是 `prune` 按「type 不在 nodes 里」判孤儿，
      会把**已经存在**的孙项行当孤儿删掉（先单母项拆解出孙项、再加第二个母项、重算子项 → 孙项消失）。

    每轮从母项出发重置 demand；迭代到所有节点的 runs 都不再变（或达 `_MAX_ROUNDS`）为止，
    跨层共享需要 2-3 轮。BOM 是严格 DAG（材料总是更低层级），故按 `sub_level` 由浅到深展开
    每轮每个节点恰好一次就够，不需要额外的环检测。
    """
    nodes: dict[int, dict] = {}

    for _round in range(_MAX_ROUNDS):
        # 上轮定稿的 runs 既作展开基准也作收敛判据
        prev_runs = {tid: int(n["runs"]) for tid, n in nodes.items()}
        for n in nodes.values():
            n["demand"] = 0

        # ① 母项 → level 1：只累需求，不展开（展开要等这一层收齐）
        for m in active_mothers:
            root_runs = max(int(m.get("runs") or 1), 1) * max(int(m.get("parallels") or 1), 1)
            bp = _find_blueprint_for_product(conn, m["product_type_id"], "manufacturing")
            if not bp:
                continue
            parent_me = int(m.get("me_level") or 0)
            for mat_id, mat_base in _get_materials(conn, bp[0], "manufacturing"):
                _accumulate(
                    conn,
                    nodes,
                    m,
                    mat_id,
                    calc_material_for_runs(mat_base, 10, parent_me, root_runs),
                    level=1,
                    parent_type_id=m["product_type_id"],
                    existing_parallels=existing_parallels,
                )

        # ② 由浅到深展开：走到某个节点时它的需求已收齐 → 定稿 runs → 展开下级。
        #    `sorted` 先把键取成快照：本轮中途新建的节点下一轮再展开（需求已记上，不会丢）。
        changed = False
        for tid in sorted(nodes, key=lambda t: (nodes[t]["sub_level"], t)):
            node = nodes[tid]
            _finalize_runs(node, stocks)
            changed |= node["runs"] != prev_runs.get(tid, 0)
            if node["runs"] <= 0:
                continue
            for mat_id, mat_base in _get_materials(conn, int(node["blueprint_type_id"]), "manufacturing"):
                _accumulate(
                    conn,
                    nodes,
                    node["first_mother"],
                    mat_id,
                    calc_material_for_runs(mat_base, 10, int(node["me_level"]), int(node["runs"])),
                    level=int(node["sub_level"]) + 1,
                    parent_type_id=tid,
                    existing_parallels=existing_parallels,
                )

        if not changed:
            break

    # 收尾：没赶上快照的节点（本轮新建的）也定稿一次，别让它们带着 runs=0 出去。
    # `_finalize_runs` 幂等，对已定稿的节点是空操作。
    for node in nodes.values():
        _finalize_runs(node, stocks)
    return nodes


def rebuild_children(*, create: bool = False, prune: bool = False) -> dict:
    """按母项当前需求同步子项（增量，默认不创建/不删除——避免误删子项被自动加回）。

    create: True 时按需生成缺失的子项产线（右键「母项拆解」用；普通编辑联动不创建，
           以免用户手动删掉的子产线被自动重建）。
    prune:  True 时删除需求归零/不再被引用的旧子项（删母项收缩用；普通编辑联动不动手删，
            避免意外砍掉用户在用的子产线）。

    返回 {"created": n, "updated": n, "deleted": n}。
    create/prune 均为 False 时仅更新已存在子项的现有需求（幂等）。
    """
    db = get_container().db
    repo = get_container().plan_repo
    with db.connect("user") as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM production_plans").fetchall()]

    # 子项层级绑定联动：新建→自动配蓝图，删除→先释放绑定避免孤儿残留。
    from services.plan_execution import ensure_plan_auto_bind, release_blueprint

    mothers = _collect_mothers(rows)
    active_mothers = [m for m in mothers if _is_active(m) and _mother_key(m)]

    stocks: dict[int, dict[int, int]] = {}
    for m in active_mothers:
        hid = m.get("mat_hangar_id")
        if hid:
            stocks[int(_mother_key(m))] = inventory_manager.get_hangar_stock(hid)

    # 现有子项：按 product_type_id 归并（同名共享组件若有重复旧行只保留第一个，其余删除）
    children_by_tid: dict[int, dict] = {}
    dup_rows: list[int] = []
    for r in rows:
        if _sub_level(r) <= 0:
            continue
        tid = int(r.get("product_type_id") or 0)
        if tid in children_by_tid:
            dup_rows.append(int(r["id"]))
        else:
            children_by_tid[tid] = r

    nodes: dict[int, dict] = {}
    if active_mothers:
        existing_parallels = {tid: int(r.get("parallels") or 1) for tid, r in children_by_tid.items()}
        with db.connect("ref", "user", "bp") as conn:
            nodes = compute_child_forest(conn, active_mothers, stocks, existing_parallels)

    created = updated = 0
    for tid, node in nodes.items():
        need = max(int(node["sub_level"]), 1)
        row = children_by_tid.get(tid)
        sources_str = ",".join(str(s) for s in sorted(node["sources"]) if s)
        parent_tid = min(node["parents"]) if node["parents"] else None
        first_mother = node["first_mother"]
        gnum = _group_of(first_mother) or 0
        mat_hangar = first_mother.get("mat_hangar_id")
        solar_system_id = _inherited_solar_system(first_mother)
        name = _resolve_name(tid)

        if row is None:
            # 仅「拆解」模式创建缺失子项；普通编辑联动不创建（防已删子产线被自动加回）
            if not create:
                continue
            new_pid = repo.insert_child_plan(
                product_type_id=tid,
                product_name=name,
                blueprint_type_id=node["blueprint_type_id"],
                runs=node["runs"],
                parallels=node["parallels"],
                me_level=node["me_level"],
                te_level=node["te_level"],
                group_number=gnum,
                sub_level=need,
                mat_hangar_id=mat_hangar,
                solar_system_id=solar_system_id,
                deposit_hangar_id=mat_hangar,  # 子项输出机库默认=母项制造机库（可手动改）
                source_mother_ids=sources_str,
                component_parent_type_id=parent_tid,
                demand=node["demand"],
            )
            created += 1
            try:
                ensure_plan_auto_bind(new_pid)
            except Exception:
                log.warning("新建子项 %s 自动绑定失败", new_pid, exc_info=True)
            continue

        # 已存在：投产/生产中子项保护 runs（已投产产线不砍）；已完成行整行冻结（历史记录不改写）
        if (row.get("status") or "").lower() in _DONE_STATUSES:
            continue
        fields: dict = {
            "source_mother_ids": sources_str,
            "component_parent_type_id": parent_tid,
            "demand": node["demand"],
            "group_number": gnum or row.get("group_number") or 0,
            "sub_level": need,
        }
        if not _is_locked(row):
            fields.update(
                runs=node["runs"],
                me_level=node["me_level"],
                te_level=node["te_level"],
                materials_ready=1,
            )
            # 存量回填：未设置输出机库（NULL）且母项有制造机库 → 默认=母项制造机库。
            # 跳过锁定行（开工中产线输出机库不静默改向）；非空已设置值（手动/下线）不覆盖。
            if mat_hangar and not row.get("deposit_hangar_id"):
                fields["deposit_hangar_id"] = mat_hangar
        changed_fields = _field_diff(row, fields)
        if changed_fields:
            repo.update(int(row["id"]), **changed_fields)
            updated += 1

    # 清理：仅「prune」模式删除不再被引用的旧子项
    to_delete: list[int] = []
    if prune:
        for tid, row in children_by_tid.items():
            if tid in nodes:
                continue
            if _is_locked(row):
                repo.update(int(row["id"]), source_mother_ids="", demand=0)
                continue
            if (row.get("status") or "").lower() in _DONE_STATUSES:
                continue
            to_delete.append(int(row["id"]))
        to_delete.extend(dup_rows)
    deleted = len(to_delete)
    if to_delete:
        # 先释放子项蓝图绑定再删行：delete_many 不清理 plan_blueprint_bindings，
        # 否则残留孤儿绑定行且蓝图仍被占用，等 create=True 重放按新 id 重建后表现为「绑定丢失」。
        for pid in to_delete:
            try:
                release_blueprint(pid)
            except Exception:
                log.warning("释放子项 %s 蓝图绑定失败", pid, exc_info=True)
        repo.delete_many(to_delete)

    if created or updated or deleted:
        log.info(
            "rebuild_children(create=%s, prune=%s): created=%d updated=%d deleted=%d",
            create,
            prune,
            created,
            updated,
            deleted,
        )
    return {"created": created, "updated": updated, "deleted": deleted}


def _resolve_name(type_id: int) -> str:
    from services.industry_dialog_queries import get_item_name

    return get_item_name(get_container().db, type_id)


def _field_diff(row: dict, fields: dict) -> dict:
    """返回 fields 中与本行当前值不同的子集（幂等：值未变则跳过，计 0）。"""
    changed = {}
    for k, v in fields.items():
        cur = row.get(k)
        if isinstance(v, int):
            cur = int(cur or 0) if cur is not None else 0
        elif isinstance(v, str):
            cur = cur if isinstance(cur, str) else (str(cur) if cur is not None else "")
        if cur != v:
            changed[k] = v
    return changed


def _inherited_solar_system(mother: dict) -> int | None:
    return mother.get("solar_system_id")

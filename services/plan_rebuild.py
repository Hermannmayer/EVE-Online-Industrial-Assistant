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
from domain.formulas import calc_material_for_runs
from services import inventory_manager
from services.bom_expander import _find_blueprint_for_product, _get_materials
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


def _in_scope(sources: set[int], group_number: int, scope: set[int] | None, scope_groups: set[int]) -> bool:
    """这一行是否落在本次写入作用域内（`rebuild_children(mother_ids=...)`）。

    scope=None → 全库重放，全部在域内（旧行为）。行有来源记录时看**母项引用**交集；
    没有来源记录的老行按组号兜底 —— 与 `plan_execution.remove_completed_children`
    判「无归属」的口径一致（来源不明的行不跨组误伤）。
    """
    if scope is None:
        return True
    if sources:
        return bool(sources & scope)
    return group_number in scope_groups


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
    （`_finalize_runs`）—— 算早了就是拿半份需求去折算 runs，见那边关于共享中间件的说明。
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


def plan_net_runs(demand: int, output_per_run: int, available: int, parallels: int) -> tuple[int, int, int]:
    """净需求 → `(并行数, 每条线轮数, 净需求线·轮数)`。**排产口径的唯一真源**。

    从 `_finalize_runs` 原样抽出，`_finalize_runs` 与两个并行对话框（「子项调整（并行配置）」
    /「子项大规模产线并行」）共用它 —— 那两处原先按**毛需求**算，会把已经排好的
    `4×3=12` 改回 `5×4=20`（多造 8 个）。

    `available` 是**这个成品自己**在母项材料机库里的库存（调用方按各自口径取；见
    `_finalize_runs` 第 1 条）。口径六条（细节与实测错法见 `_finalize_runs` docstring）：

    1. 毛需求换算成「线·轮」：`total_runs = ceil(demand / output_per_run)`；
    2. 库存**按 `output_per_run` 整批取整**、并夹取到 `total_runs`：
       `covered = min(available // output_per_run, total_runs)`；
    3. 净需求 `remaining = total_runs - covered`；
    4. `remaining <= 0`（库存全顶住）→ 并行数原样，轮数 1（有需求就开一轮）；
    5. `parallels == 1` → 不寻优，轮数 = `remaining`；
    6. 否则在 `p = 1..parallels` 里寻优：容忍度 = 一轮整批产量 `parallels × output_per_run`（件），
       容忍度内先取**轮数最少**（工期短），同轮数比超出件数，最后取并行数大的（绝不超过用户既有并行数）。
    7. `demand <= 0` → 轮数 0、并行数原样返回（不对无需求的行做任何寻优）。

    第三项 `remaining` 供「子项大规模产线并行」当需求权重（它只分配并行数，要的是净线·轮数）。
    """
    demand = int(demand or 0)
    if demand <= 0:
        return int(parallels), 0, 0
    per_run = max(int(output_per_run or 1), 1)
    lines = max(int(parallels or 1), 1)
    total_runs = math.ceil(demand / per_run)
    covered_lines = min(int(available or 0) // per_run, total_runs)
    remaining_lines = total_runs - covered_lines

    if remaining_lines <= 0:
        return lines, 1, 0
    if lines == 1:
        return 1, remaining_lines, remaining_lines

    limit = lines * per_run  # 「多几个」的容忍度 = 一轮的整批产出（件）
    cands: list[tuple[int, int, int]] = []  # (超出件数, 轮数, -并行数)
    for p in range(1, lines + 1):
        r = math.ceil(remaining_lines / p)
        cands.append((p * r * per_run - remaining_lines * per_run, r, -p))
    within = [c for c in cands if c[0] <= limit]
    if within:  # 容忍度内取轮数最少（净需求 13 / 5 线 → 5×3=15，而不是 1×13）
        best = min(within, key=lambda c: (c[1], c[0], c[2]))
    else:  # 保险分支（数学上不可达，见 `_finalize_runs` docstring）：退回「超出件数最少」
        best = min(cands, key=lambda c: (c[0], c[1], c[2]))
    return -best[2], best[1], remaining_lines


def _finalize_runs(node: dict, stocks: dict[int, dict[int, int]]) -> None:
    """把本轮收齐的 demand 折算成 runs（**每条产线的流程数**）+ 顺带定并行数，净口径不多造。

    口径六条缺一不可，下面每条错法都实测过：

    1. **扣的是「首个引用母项机库」里这个成品自己的库存**（`first_mother.mat_hangar_id`，按母项 id
       取的快照 `stocks`），不是原材料库存 —— 原材料库存由下游 `plan_aggregator.aggregate_procurement`
       / `plan_execution.check_materials` 扣一次。
    2. **库存按 `per_run` 整批取整**：`available // per_run` 表示这堆库存能顶掉几个「线·轮」。
       直接拿 `available` 当轮数是量纲混用（上一轮就是这么错的：6 件库存被当成 6 轮）。
    3. **先扣再摊并行数**。`runs` 的语义是「每条产线的流程数」（`services/char_capacity.py:3`），
       整批产出 = `runs × parallels × per_run`。所以毛需求先表达成「线·轮」数
       `total_runs = ceil(demand / per_run)`，减去库存顶掉的线·轮得到净需求 `remaining_lines`，
       **再**拿净需求去定并行数与每条线的轮数。

       ⚠️ 三种写法都是错的，别再退回去：
       - `ceil(demand/(parallels*per_run)) - covered`（先除再扣）→ 扣的量和被减的量纲不一致，
         实测 18 需 / 6 有 / 3 线 会算出 `3×0`，把其实缺的 12 个当成不用生产；
       - `total_runs - covered_lines` 直接当 `runs`（不摊 parallels）→ parallels > 1 时整批产出
         被放大 parallels 倍，实测同例会排 12 轮 → 3×12=36 个，比「净需求 12」多造 24 个；
       - 沿用既有 `parallels` 不寻优 → 实测同例 `5×3 = 15`，仍比净需求 12 多造 3 个。
    4. `covered_lines` 夹取 `min(..., total_runs)`：库存大于需求时算不出负的 covered 反向多排。
    5. `demand > 0` 时 `runs` 至少 1（有需求就得开工，库存再够也排一轮）；
       `demand <= 0` 直接 0 —— 凭空排一轮产出和「3×0」是同一类错。

    **并行数寻优（`remaining_lines > 0` 就做 —— 不看 `covered_lines` 是否 > 0；只有 `parallels > 1` 才循环）**：
    触发条件只看净需求：没有库存的下子项同样会把 `4×5` 多出来的 2 个留着（用户报的正是它），
    必须一起修。在「不超过用户既有 `parallels`」的范围内试 `p = 1..parallels`，`r = ceil(remaining_lines / p)`：

    - **「多几个」的容忍度 = 一轮的整批产量 `parallels × per_run`（件）**：先排除超出容忍度的候选
      （数学上永远有候选落在里面：`p*r - remaining_lines < p ≤ parallels`，所以这是保险分支）；
    - 容忍度内的候选里取**每条线轮数最少**（`r` 小 = 工期短），同轮数才比超出件数，
      最后才比并行数（`-p` 小 = 并行数大的优先：尽量用上用户已有的线，但绝不超过它）。

    实测（`per_run=1`）：
    - `net=12, parallels=5` → `P=4, runs=3`（`4×3=12` 零多余；`P=5` 是 `5×3=15` 多 3，被同轮数下的件数次键淘汰）
    - `net=13, parallels=5` → `P=5, runs=3`（`5×3=15`，多 2 ≤ 一轮整批 5 件）—— **不是** `P=1, runs=13`：
      后者虽零多余，却把 13 轮压在一条线上、工期 13 倍，与用户「零多余 **+** 少轮次」的诉求相反；
      反过来也不越过用户既有并行数去多占线
    - `net=12, parallels=3` → `P=3, runs=4`（`3×4=12`）；`net=1360, parallels=1` → `1×1360`（单线不走循环）
    - `net<=0`（库存全顶住）→ **保留用户既有 `parallels`**，只把 `runs` 钉成 1

    **为什么这次不会重复计库存**：`runs` 在这里已经吃掉了成品库存，于是下游看到的 `demand` 与
    排产出的量都是**净需求**（342：2040 需 − 680 有 → 排 `1×1360`，采购表里那 680 件不再出现在 need 里）。
    下游不会再扣同一份库存：`aggregate_procurement` 只对 `blueprint_materials` 里的**原材料**扣库存，
    而子项成品的 type_id 早就被 `self_made_type_ids` 排除在待采购之外 —— 同一份库存只扣一次。

    算法本体在 `plan_net_runs`（纯函数，两个并行对话框共用同一口径）；这里只负责取 `stocks` 口径的
    库存快照并把结果写回节点。
    """
    demand = int(node.get("demand") or 0)
    if demand <= 0:
        node["runs"] = 0
        return
    per_run = max(int(node.get("output_qty") or 1), 1)  # 每条线每轮的产出
    parallels = max(int(node.get("parallels") or 1), 1)
    stock = stocks.get(int((node.get("first_mother") or {}).get("id") or 0), {})
    available = int(stock.get(int(node.get("product_type_id") or 0), 0))
    node["parallels"], node["runs"], _net_lines = plan_net_runs(demand, per_run, available, parallels)


def compute_child_forest(
    conn, active_mothers: list[dict], stocks: dict[int, dict[int, int]], existing_parallels: dict[int, int]
) -> dict[int, dict]:
    """全局需求传播 → {type_id: node}。

    共享组件跨母项/跨层级需求自动累加为一行；`existing_parallels` 是用户既有并行产线数，
    作为 `_finalize_runs` 里并行数寻优的**上界**（用户不设就按 1 条线排）。
    `stocks` 是按母项 id 索引的「该母项制造机库」库存快照，用于把成品库存折进 runs
    （净口径、并行数寻优与「为什么不重复计」见 `_finalize_runs`）。

    迭代形态：**每轮先把需求累齐，再定稿 runs，最后才拿 runs 去展开下级；每个节点每轮只展开一次。**
    这是这套传播的命门，两个坑都出在违反它的时候：

    - **别在累需求的过程中折算 runs**。曾经的写法是每个母项各展开一遍，节点一收到需求就
      立刻算 runs 并用它展开下级 —— 共享中间件于是被展开两次：第一次按第一个母项的**部分**
      需求算出的 runs，第二次按收齐后的 runs。下级的 demand 直接翻倍（实测 60 被算成 80）。
    - **别用短路写递归**。曾经的 `changed = changed or _propagate(...)` 在本节点 runs 有变化时
      根本不往下走 —— 而「正在变」恰恰是最该往下走的时候。多母项共享中间件时每轮都在变，
      于是 level≥2 永远进不了 `nodes`；更糟的是 `prune` 按「type 不在 nodes 里」判孤儿，
      会把**已经存在**的孙项行当孤儿删掉（先单母项拆解出孙项、再加第二个母项、再拆解一次 → 孙项消失）。

    每轮从母项出发重置 demand；迭代到所有节点的 runs 都不再变（或达 `_MAX_ROUNDS`）为止，
    跨层共享需要 2-3 轮。BOM 是严格 DAG（材料总是更低层级），故按 `sub_level` 由浅到深展开
    每轮每个节点恰好一次就够，不需要额外的环检测。
    """
    nodes: dict[int, dict] = {}

    for _round in range(_MAX_ROUNDS):
        # 上轮定稿的 (runs, parallels) 既作展开基准也作收敛判据。
        # `parallels` 必须一起比：`_finalize_runs` 会做并行数寻优，可能出现「runs 没变、parallels
        # 变了」的一轮 —— 只比 runs 就会提前收敛，库里留下 runs 按旧并行数摊出来的值。
        prev = {tid: (int(n["runs"]), int(n["parallels"])) for tid, n in nodes.items()}
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
            changed |= (int(node["runs"]), int(node["parallels"])) != prev.get(tid, (0, 0))
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


def rebuild_children(*, create: bool = False, prune: bool = False, mother_ids: set[int] | None = None) -> dict:
    """按母项当前需求同步子项（增量，默认不创建/不删除——避免误删子项被自动加回）。

    create: True 时按需生成缺失的子项产线（右键「母项拆解」用；普通编辑联动不创建，
           以免用户手动删掉的子产线被自动重建）。
    prune:  True 时删除需求归零/不再被引用的旧子项（删母项收缩用；普通编辑联动不动手删，
            避免意外砍掉用户在用的子产线）。
    mother_ids: 限定**写入**范围的母项 id（右键「母项拆解」那条对话框传它：只许动它选中
           的母项）。传了以后只有**这些母项引用得到**的子项行会被创建/更新/清理，别的组
           没被引用的行一行都不动。
           ⚠️ 但**共享件例外**：作用域判定看的是 `source_mother_ids` 与作用域的交集
           （`_in_scope`），所以被作用域外母项也引用的共享行**会被一并改写**
           （runs/demand/source_mother_ids 都要含所有引用者，只按本组算会把别的组的需求削掉）。
           「别的组一行都不动」只对**不共享**的行成立。
           这正是用户报的「拆解一条母项，全库计划都被自动拆解」的修复点：以前不带作用域时，
           全库缺失的中间件都会被补建。
           需求传播仍按**全库**活跃母项算：共享件的 demand 必须是所有引用者之和，只按本组
           算会把共享行算小、把别的组的产线需求削掉。默认 None = 全库重放（编辑母项后的
           自动联动、删行收缩等）。

    返回 {"created": n, "updated": n, "deleted": n}。
    create/prune 均为 False 时仅更新已存在子项的现有需求（幂等）。
    """
    db = get_container().db
    repo = get_container().plan_repo
    scope = {int(i) for i in mother_ids if i} if mother_ids is not None else None
    with db.connect("user") as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM production_plans").fetchall()]

    # 子项层级绑定联动：新建→自动配蓝图，删除→先释放绑定避免孤儿残留。
    from services.plan_execution import ensure_plan_auto_bind, release_blueprint

    mothers = _collect_mothers(rows)
    active_mothers = [m for m in mothers if _is_active(m) and _mother_key(m)]

    #: 作用域内母项的组号：老行（v12 之前）没有 `source_mother_ids`，按组号兜底判归属
    scope_groups = {_group_of(m) for m in mothers if scope is not None and _mother_key(m) in scope}

    # 每个活跃母项各自制造机库的库存快照：子项 runs 折算要扣「自己产出的成品」库存，
    # 按母项 id 索引 —— 共享子项按「首个引用母项」的机库扣一次（与 node["first_mother"] 同源）。
    stocks: dict[int, dict[int, int]] = {}
    for m in active_mothers:
        hid = m.get("mat_hangar_id")
        if hid:
            stocks[int(_mother_key(m))] = inventory_manager.get_hangar_stock(hid)

    # 现有子项：按 product_type_id 归并（同名共享组件若有重复旧行只保留第一个，其余删除）
    children_by_tid: dict[int, dict] = {}
    dup_rows: list[dict] = []
    for r in rows:
        if _sub_level(r) <= 0:
            continue
        tid = int(r.get("product_type_id") or 0)
        prev = children_by_tid.get(tid)
        if prev is None:
            children_by_tid[tid] = r
            continue
        # 同 tid 的重复旧行：**优先保留已投产的那条**。「部分启动」会把一行拆成
        # 「投产行 + pending 余量行」（`plan_repository.insert_split_remainder`），
        # 按 `SELECT *` 的 rowid 先到先得的话，留下的可能是余量行、而在产那行被当重复删掉。
        drop, keep = (prev, r) if (_is_locked(r) and not _is_locked(prev)) else (r, prev)
        children_by_tid[tid] = keep
        # ⚠️ 要丢掉的这行如果**在产 / 已完工**，就留着别删：删掉在产行之后，下一次
        # `create=True` 会按需求补建一条 `pending` 行 —— 而那条新行对着**已经扣减过的
        # 库存**必然显示「材料不足」（用户报的「新子线把在跑的产线搞坏了」就是这个表象）。
        # 与 `plan_table._cascade_children`、`_remove_planning_discarded` 同一口径。
        if not _is_locked(drop) and (drop.get("status") or "").lower() not in _DONE_STATUSES:
            dup_rows.append(drop)

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
            # 作用域外的母项（本次对话框没碰的组）不补建子项 —— 否则「拆解 A」会把
            # 别组（含在产组）的产线一并拆出来，用户在表里看到的就是「全库都被拆解了」
            if not _in_scope(node["sources"], gnum, scope, scope_groups):
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
        # 作用域外（别的母项引用、本次对话框没碰的组）已有行不重写
        if not _in_scope(node["sources"], _group_of(row), scope, scope_groups):
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
                # `parallels` 必须和 `runs` 一起落库：`runs` 是按**寻优后的**并行数摊出来的，
                # 只写 runs 不写 parallels → 库里留下「runs 按 4 条线算、parallels 还是 5」，
                # 下游 `runs × parallels` 又变回 5×3=15（多造 3 个）。净需求全被库存顶住时
                # node["parallels"] 就是既有值，`_field_diff` 不会写它。
                # 覆盖用户手设的并行数（实测 41484：5 → 4）是**用户拍板的口径**——「自动把并行数
                # 降到最优」，不是 bug：不覆盖就仍按 5 条线×3 轮多造 3 个。
                parallels=node["parallels"],
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
            # 作用域外的行不清理：本次对话框只收拾自己那条母项引用的子项
            if not _in_scope(_parse_sources(row), _group_of(row), scope, scope_groups):
                continue
            if _is_locked(row):
                repo.update(int(row["id"]), source_mother_ids="", demand=0)
                continue
            if (row.get("status") or "").lower() in _DONE_STATUSES:
                continue
            to_delete.append(int(row["id"]))
        to_delete.extend(
            int(r["id"]) for r in dup_rows if _in_scope(_parse_sources(r), _group_of(r), scope, scope_groups)
        )
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

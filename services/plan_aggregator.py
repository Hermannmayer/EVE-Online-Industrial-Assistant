"""
计划聚合查询 — 为工业制造三张汇总表提供统一数据层

将 blueprint_dialog / materials_dialog / output_dialog 公用的
蓝图库存、材料库存、产出溢出计算提取到这里。

用法:
    from services.plan_aggregator import (
        expand_blueprint_requirements,
        check_user_blueprints,
        check_inventory,
        calculate_output_with_overflow,
    )

    with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
        plans = ...  # list[dict]
        bps = expand_blueprint_requirements(conn, plans)
        bp_inv = check_user_blueprints(conn, set(bps.keys()))
"""

from __future__ import annotations

import math
from typing import Any

from domain.bom import walk_bom
from services.blueprint_reader import SqliteBlueprintReader
from services.manufacturing_calculator import calc_material_for_runs
from services.name_resolver import resolve_item_name

# ════════════════════════════════════════════════════════════════
#  内部辅助
# ════════════════════════════════════════════════════════════════


def _resolve_name(conn, type_id: int) -> str:
    """委托给 name_resolver（有 terminology 覆盖兜底）"""
    return resolve_item_name(conn, type_id)


def _resolve_bp_name(conn, bp_type_id: int) -> str:
    """查出蓝图名称（优先从 item 表）"""
    # 有些蓝图在 item 表有独立条目，若无则用对应的产物名
    name = _resolve_name(conn, bp_type_id)
    # 如果查到的是 type_id 本身（无中文名），尝试用蓝图产物名
    if name == str(bp_type_id):
        prod = conn.execute(
            "SELECT product_type_id FROM blueprint_products "
            "WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (bp_type_id,),
        ).fetchone()
        if prod:
            name = _resolve_name(conn, prod[0])
    return name


def _get_per_run_output(conn, bp_type_id: int) -> int:
    """获取蓝图每次制造的产出数量"""
    row = conn.execute(
        "SELECT quantity FROM blueprint_products WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
        (bp_type_id,),
    ).fetchone()
    return row[0] if row and row[0] else 1


# ════════════════════════════════════════════════════════════════
#  1. 蓝图需求展开
# ════════════════════════════════════════════════════════════════


def expand_blueprint_requirements(
    conn,
    plans: list[dict],
    *,
    me_level: int = 0,
) -> dict[int, dict[str, Any]]:
    """收集每个生产计划顶层产物的蓝图需求（不递归展开 BOM 子项）。

    用户的生产模式是每项计划只制造自己的成品，
    子项材料直接购买成品，不会自己造子项的蓝图。
    所以只需查每个 plan.product_type_id 对应的制造蓝图即可。

    Args:
        conn: 已 ATTACH user/ref/bp/mkt 的数据库连接
        plans: 计划列表，每项需含 product_type_id, runs, parallels
        me_level: 默认材料等级（各计划不同时从 plan 中取）

    Returns:
        {blueprint_type_id: {"name": str, "needed_runs": int}}
    """
    needed: dict[int, dict[str, Any]] = {}

    for plan in plans:
        pid = plan.get("product_type_id")
        if not pid:
            continue
        runs = plan.get("runs", 1) or 1
        parallels = plan.get("parallels", 1) or 1
        total_qty = runs * parallels

        # 直接查该产品的制造蓝图（不递归材料）
        bp_row = conn.execute(
            "SELECT blueprint_type_id FROM blueprint_products "
            "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (pid,),
        ).fetchone()
        if not bp_row:
            continue  # 该产品无制造蓝图（不应发生，创建计划时已校验）

        bp_tid = bp_row[0]
        per_run = _get_per_run_output(conn, bp_tid)
        if per_run < 1:
            per_run = 1
        activations = math.ceil(total_qty / per_run)

        if bp_tid in needed:
            needed[bp_tid]["needed_runs"] += activations
        else:
            name = _resolve_bp_name(conn, bp_tid)
            needed[bp_tid] = {
                "name": name,
                "needed_runs": activations,
            }

    return needed


# ════════════════════════════════════════════════════════════════
#  3. 用户蓝图库存查询
# ════════════════════════════════════════════════════════════════


def check_user_blueprints(
    conn,
    bp_type_ids: set[int],
) -> dict[int, dict[str, Any]]:
    """查询用户蓝图库存，返回每个 blueprint_type_id 的拥有情况。

    BPO (is_bpo=1) 视为无限流程数，available_runs 设为极大值。

    Args:
        conn: 已 ATTACH user/ref/bp/mkt 的数据库连接
        bp_type_ids: 要查询的蓝图 type_id 集合

    Returns:
        {blueprint_type_id: {
            "count": int,       # BPO 数量（可用作指标）
            "total_runs": int,  # 总可用流程数（BPO=999999）
            "is_bpo": bool,
            "best_me": int,
            "best_te": int,
            "available_runs": float,  # BPO 视为 INF
        }}
    """
    if not bp_type_ids:
        return {}

    placeholders = ",".join("?" for _ in bp_type_ids)
    rows = conn.execute(
        f"""
        SELECT blueprint_type_id,
               SUM(quantity),
               MAX(CASE WHEN is_bpo = 1 THEN 1 ELSE 0 END),
               MAX(me_level),
               MAX(te_level),
               SUM(CASE WHEN is_bpo = 0 THEN quantity * runs ELSE 0 END),
               SUM(CASE WHEN is_bpo = 1 THEN quantity ELSE 0 END)
        FROM user_blueprints
        WHERE blueprint_type_id IN ({placeholders})
        GROUP BY blueprint_type_id
        """,
        tuple(bp_type_ids),
    ).fetchall()

    result: dict[int, dict[str, Any]] = {}
    for (
        bp_tid,
        total_count,
        has_bpo,
        best_me,
        best_te,
        bpc_runs_total,
        bpo_count,
    ) in rows:
        has_bpo_flag = bool(has_bpo)
        bpo_count = bpo_count or 0
        bpc_runs_total = bpc_runs_total or 0

        # BPO 视为无限流程
        if has_bpo_flag:
            available = float("inf")
        else:
            available = float(bpc_runs_total)

        result[bp_tid] = {
            "count": total_count or 0,
            "total_runs": bpc_runs_total,
            "is_bpo": has_bpo_flag,
            "best_me": best_me or 0,
            "best_te": best_te or 0,
            "bpo_count": bpo_count,
            "available_runs": available,
        }

    # 未拥有的也填入默认值
    for bp_tid in bp_type_ids:
        if bp_tid not in result:
            result[bp_tid] = {
                "count": 0,
                "total_runs": 0,
                "is_bpo": False,
                "best_me": 0,
                "best_te": 0,
                "bpo_count": 0,
                "available_runs": 0.0,
            }

    return result


# ════════════════════════════════════════════════════════════════
#  4. 库存查询
# ════════════════════════════════════════════════════════════════


def check_inventory(
    conn,
    type_ids: set[int],
) -> dict[int, int]:
    """查询用户库存（所有机库合计），返回 {type_id: total_quantity}"""
    if not type_ids:
        return {}

    placeholders = ",".join("?" for _ in type_ids)
    rows = conn.execute(
        f"""
        SELECT type_id, SUM(quantity)
        FROM inventory_items
        WHERE type_id IN ({placeholders})
        GROUP BY type_id
        """,
        tuple(type_ids),
    ).fetchall()

    return {r[0]: r[1] or 0 for r in rows}


# ════════════════════════════════════════════════════════════════
#  5. 市场价格批量查询
# ════════════════════════════════════════════════════════════════


def get_market_prices(
    conn,
    type_ids: set[int],
    region_id: int = 10000002,
) -> dict[int, dict[str, float]]:
    """批量查询市场价，返回 {type_id: {"sell": float, "buy": float, "avg": float}}"""
    if not type_ids:
        return {}

    placeholders = ",".join("?" for _ in type_ids)
    rows = conn.execute(
        f"""
        SELECT type_id, sell_price, buy_price
        FROM market_prices
        WHERE type_id IN ({placeholders}) AND region_id = ?
        """,
        tuple(type_ids) + (region_id,),
    ).fetchall()

    result: dict[int, dict[str, float]] = {}
    for tid, sell, buy in rows:
        result[tid] = {
            "sell": sell or 0.0,
            "buy": buy or 0.0,
        }
    return result


# ════════════════════════════════════════════════════════════════
#  6. 产出 + 溢出计算
# ════════════════════════════════════════════════════════════════


def get_batch_adjustment(
    per_run_output: int,
    needed_qty: int,
) -> tuple[int, int, int]:
    """计算批次调整 — 当蓝图产出为批量时，可能需要向上取整。

    Args:
        per_run_output: 每次 run 的产出数
        needed_qty: 实际需要的数量

    Returns:
        (actual_runs, actual_output, overflow)
        - actual_runs: 实际需要的制造次数
        - actual_output: 实际制造出的总数量
        - overflow: actual_output - needed_qty
    """
    if per_run_output <= 0:
        per_run_output = 1
    runs = math.ceil(needed_qty / per_run_output)
    output = runs * per_run_output
    overflow = output - needed_qty
    return runs, output, overflow


def calculate_output_with_overflow(
    conn,
    plans: list[dict],
    *,
    me_level: int = 0,
    max_depth: int = 4,
    region_id: int = 10000002,
) -> list[dict[str, Any]]:
    """计算所有计划的产出数据，含中间产品的 batch 溢出信息。

    Args:
        conn: 已 ATTACH user/ref/bp/mkt 的数据库连接
        plans: 计划列表（需含 product_type_id, runs, parallels, material_cost 等）
        me_level: 默认材料等级
        max_depth: 递归深度上限

    Returns:
        每个计划一项，含产出值、利润、溢出明细
    """
    # 批量查市场价格
    all_type_ids: set[int] = set()
    for plan in plans:
        all_type_ids.add(plan.get("product_type_id", 0))
    prices = get_market_prices(conn, all_type_ids, region_id)

    results: list[dict[str, Any]] = []

    for plan in plans:
        pid = plan.get("product_type_id")
        assert pid is not None, "product_type_id required"
        runs = plan.get("runs", 1) or 1
        parallels = plan.get("parallels", 1) or 1
        me = plan.get("me_level", me_level) or me_level
        total_qty = runs * parallels
        mat_cost = plan.get("material_cost", 0) or 0
        profit = plan.get("profit", 0) or 0
        name = plan.get("product_name", _resolve_name(conn, pid) if pid else "?")

        # 计划层面
        plan_price = prices.get(pid, {}).get("sell", 0.0)
        plan_value = plan_price * total_qty
        status = plan.get("status", "pending")

        # 递归 BOM 查找中间产品溢出（全局 seen：共享中间产品只计一次）
        overflow_details: list[dict] = []
        reader = SqliteBlueprintReader(conn)
        for step in walk_bom(reader, pid, total_qty, me_level=me, max_depth=max_depth, seen_mode="global"):
            if step.blueprint is None:
                continue  # 叶子（无蓝图 / 环 / 深度封顶）→ 无溢出
            per_run_out = step.blueprint[1]
            overflow = step.runs * per_run_out - step.qty
            if overflow > 0:
                overflow_details.append(
                    {
                        "type_id": step.type_id,
                        "name": _resolve_name(conn, step.type_id),
                        "needed": step.qty,
                        "per_run": per_run_out,
                        "runs": step.runs,
                        "produced": step.runs * per_run_out,
                        "overflow": overflow,
                    }
                )
        overflow_text = _format_overflow(overflow_details)

        results.append(
            {
                "plan_name": name,
                "product_type_id": pid,
                "total_qty": total_qty,
                "plan_value": plan_value,
                "material_cost": mat_cost,
                "profit": profit,
                "margin_pct": plan.get("margin", 0) or 0,
                "sell_price": plan_price,
                "status": status,
                "overflow_details": overflow_details,
                "overflow_text": overflow_text,
                "has_overflow": len(overflow_details) > 0,
            }
        )

    return results


def _format_overflow(details: list[dict]) -> str:
    """格式化溢出信息为短文本"""
    if not details:
        return "—"
    parts = []
    for d in details[:3]:  # 最多显示 3 条
        parts.append(f"{d['name']}溢出{d['overflow']}个")
    if len(details) > 3:
        parts.append(f"…等{len(details)}项")
    return ", ".join(parts)


# ════════════════════════════════════════════════════════════════
#  7. 备料采购聚合（新加入产线自动勾选 → 待采购金额/体积）
# ════════════════════════════════════════════════════════════════


def _pick_price(price_map: dict[str, float], price_type: str) -> float:
    """按价格类型取价；缺省回退另一个来源，均无数据返回 0.0"""
    if price_type == "buy":
        val = price_map.get("buy", 0.0) or 0.0
        return val if val else price_map.get("sell", 0.0) or 0.0
    val = price_map.get("sell", 0.0) or 0.0
    return val if val else price_map.get("buy", 0.0) or 0.0


def aggregate_procurement(
    conn,
    plans: list[dict],
    *,
    hangar_id: int | None = None,
    default_hangar_id: int | None = None,
    region_id: int = 10000002,
    price_type: str = "sell",
) -> tuple[list[dict], float, float]:
    """聚合「备料中」计划的待采购材料并扣库存 → (rows, total_cost, total_volume)。

    Args:
        conn: 已 ATTACH user/ref/bp/mkt 的数据库连接
        plans: 计划列表（需含 product_type_id / runs / parallels / me_level）
        hangar_id: 非 None 时全部需求统一扣该机库库存（采购弹窗模式）；
                   None 时按各计划 mat_hangar_id 分组各自扣减（统计条模式），
                   计划无 mat_hangar_id 用 default_hangar_id 兜底
        default_hangar_id: 统计条模式下无 mat_hangar_id 计划的后备机库
        region_id: 市场价 region_id
        price_type: "sell" / "buy"

    Returns:
        (rows, total_cost, total_volume)
        rows: [{type_id, name, need, owned, to_buy, price, total, volume}]
    """
    # 1. 每个计划取直接材料；由子项产线自制的组件排除（其原材料由子线计划计入）。
    #    未拆解的组件 / 子线被删后 → 回到待采购。
    sub_prod_ids = {
        p.get("product_type_id")
        for p in plans
        if p.get("product_type_id") and int(p.get("child_level") or p.get("sub_level") or 0) > 0
    }
    group_need: dict[int | None, dict[int, float]] = {}
    names: dict[int, str] = {}
    volumes: dict[int, float] = {}
    for plan in plans:
        pid = plan.get("product_type_id")
        if not pid:
            continue
        total_runs = max(int(plan.get("runs") or 1), 1) * max(int(plan.get("parallels") or 1), 1)
        me = int(plan.get("me_level") or 0)
        bp = conn.execute(
            "SELECT blueprint_type_id FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (pid,),
        ).fetchone()
        if not bp:
            continue
        mats = conn.execute(
            "SELECT material_type_id, quantity, COALESCE(wastefactor,10) FROM blueprint_materials "
            "WHERE blueprint_type_id=? AND activity='manufacturing'",
            (bp[0],),
        ).fetchall()
        gid = hangar_id if hangar_id is not None else (plan.get("mat_hangar_id") or default_hangar_id)
        bucket = group_need.setdefault(gid, {})
        for mid, qty, wf in mats:
            if mid in sub_prod_ids:
                continue  # 自制组件：由子项产线覆盖，买其原材料（子线计划已计入）
            need = calc_material_for_runs(qty, wf, me, total_runs)
            bucket[mid] = bucket.get(mid, 0.0) + float(need)
            if mid not in names:
                names[mid] = _resolve_name(conn, mid)
            if mid not in volumes:
                v = conn.execute("SELECT volume FROM item WHERE type_id=?", (mid,)).fetchone()
                volumes[mid] = float(v[0]) if v and v[0] else 0.0

    # 2. 每个出现过的机库各查一次库存（同机库跨计划合并后统一扣减）
    inv_by_hangar: dict[int | None, dict[int, float]] = {}
    for gid in group_need:
        if gid is None:
            continue
        rows = conn.execute(
            "SELECT type_id, SUM(quantity) FROM inventory_items WHERE hangar_id = ? GROUP BY type_id",
            (gid,),
        ).fetchall()
        inv_by_hangar[gid] = {r[0]: r[1] or 0 for r in rows}

    # 3. 跨计划合并 need / owned / to_buy
    need_map: dict[int, float] = {}
    owned_map: dict[int, float] = {}
    to_buy_map: dict[int, float] = {}
    for gid, bucket in group_need.items():
        inv = inv_by_hangar.get(gid, {})
        for tid, need_amt in bucket.items():
            owned = inv.get(tid, 0)
            to_buy = max(0, need_amt - owned)
            need_map[tid] = need_map.get(tid, 0.0) + need_amt
            owned_map[tid] = owned_map.get(tid, 0.0) + owned
            to_buy_map[tid] = to_buy_map.get(tid, 0.0) + to_buy

    # 4. 批量市场价
    prices = get_market_prices(conn, set(to_buy_map), region_id=region_id)

    # 5. 组装 rows + 汇总
    rows_out: list[dict] = []
    total_cost = 0.0
    total_volume = 0.0
    for tid in sorted(to_buy_map):
        to_buy = to_buy_map[tid]
        price = _pick_price(prices.get(tid, {}), price_type)
        subtotal = to_buy * price
        vol = to_buy * volumes.get(tid, 0.0)
        rows_out.append(
            {
                "type_id": tid,
                "name": names.get(tid, str(tid)),
                "need": need_map[tid],
                "owned": owned_map[tid],
                "to_buy": to_buy,
                "price": price,
                "total": subtotal,
                "volume": vol,
            }
        )
        total_cost += subtotal
        total_volume += vol
    return rows_out, total_cost, total_volume


def collect_direct_materials(conn, plans: list[dict]) -> dict[int, dict]:
    """聚合各计划的直接材料（recipe 一层，非递归），排除由子项产线自制的组件。

    母项拆解后：有子线的组件改为买其原材料（子线计划已计入），未拆解的组件直接采购；
    子线被删后组件回到待采购。返回格式对齐 expand_material_requirements：
    {type_id: {"name", "total_qty", "volume"}}
    """
    sub_prod_ids = {
        p.get("product_type_id")
        for p in plans
        if p.get("product_type_id") and int(p.get("child_level") or p.get("sub_level") or 0) > 0
    }
    result: dict[int, dict] = {}
    for plan in plans:
        pid = plan.get("product_type_id")
        if not pid:
            continue
        total_runs = max(int(plan.get("runs") or 1), 1) * max(int(plan.get("parallels") or 1), 1)
        me = int(plan.get("me_level") or 0)
        bp = conn.execute(
            "SELECT blueprint_type_id FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (pid,),
        ).fetchone()
        if not bp:
            continue
        mats = conn.execute(
            "SELECT material_type_id, quantity, COALESCE(wastefactor,10) FROM blueprint_materials "
            "WHERE blueprint_type_id=? AND activity='manufacturing'",
            (bp[0],),
        ).fetchall()
        for mid, qty, wf in mats:
            if mid in sub_prod_ids:
                continue  # 自制组件：由子项产线覆盖，买其原材料（子线计划已计入）
            need = calc_material_for_runs(qty, wf, me, total_runs)
            if mid in result:
                result[mid]["total_qty"] += need
            else:
                v = conn.execute("SELECT volume FROM item WHERE type_id=?", (mid,)).fetchone()
                result[mid] = {
                    "name": _resolve_name(conn, mid),
                    "total_qty": float(need),
                    "volume": float(v[0]) if v and v[0] else 0.0,
                }
    return result

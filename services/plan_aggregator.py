"""
计划聚合查询 — 为工业制造三张汇总表提供统一数据层

将 blueprint_dialog / materials_dialog / output_dialog 公用的
BOM 展开、蓝图库存、材料库存、产出溢出计算提取到这里，
避免三个对话框各自重复实现 _expand 递归。

用法:
    from services.plan_aggregator import (
        expand_blueprint_requirements,
        expand_material_requirements,
        check_user_blueprints,
        check_inventory,
        calculate_output_with_overflow,
    )

    with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
        plans = ...  # list[dict]
        bps = expand_blueprint_requirements(conn, plans)
        mats = expand_material_requirements(conn, plans)
        bp_inv = check_user_blueprints(conn, set(bps.keys()))
"""

from __future__ import annotations

import math
from typing import Any

from services.manufacturing_calculator import calc_material_for_runs
from services.name_resolver import resolve_item_name

# 默认 T1 wastefactor（兜底）
_DEFAULT_WASTE = 10


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
        "SELECT quantity FROM blueprint_products "
        "WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
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
#  2. 材料需求展开（叶子节点）
# ════════════════════════════════════════════════════════════════


def expand_material_requirements(
    conn,
    plans: list[dict],
    *,
    me_level: int = 0,
    max_depth: int = 5,
) -> dict[int, dict[str, Any]]:
    """展开 BOM 到叶子节点，返回所有原材料需求汇总。

    Args:
        conn: 已 ATTACH user/ref/bp/mkt 的数据库连接
        plans: 计划列表
        me_level: 默认材料等级
        max_depth: 递归深度上限

    Returns:
        {type_id: {"name": str, "total_qty": float, "volume": float}}
    """
    materials: dict[int, dict[str, Any]] = {}
    seen: set[int] = set()

    def _expand(product_type_id: int, qty: int, me: int):
        """递归展开 BOM，叶子节点加入 materials"""
        if product_type_id in seen:
            # 已处理过，累加需求
            if product_type_id in materials:
                materials[product_type_id]["total_qty"] += qty
            # 继续递归其材料（即使已见过，也要把材料需求加上）
            bp_row = conn.execute(
                "SELECT blueprint_type_id FROM blueprint_products "
                "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                (product_type_id,),
            ).fetchone()
            if bp_row:
                mats = conn.execute(
                    "SELECT material_type_id, quantity "
                    "FROM blueprint_materials WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
                    (bp_row[0],),
                ).fetchall()
                for mat_id, mat_qty in mats:
                    mat_total = calc_material_for_runs(mat_qty, _DEFAULT_WASTE, me, math.ceil(qty / 1))
                    _expand(mat_id, mat_total, me)
            return
        seen.add(product_type_id)

        # 找蓝图
        bp_row = conn.execute(
            "SELECT blueprint_type_id FROM blueprint_products "
            "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (product_type_id,),
        ).fetchone()
        if not bp_row:
            # 原材料 — 记录
            name = _resolve_name(conn, product_type_id)
            vol_row = conn.execute(
                "SELECT volume FROM item WHERE type_id = ?", (product_type_id,)
            ).fetchone()
            vol = vol_row[0] if vol_row else 0.0
            if product_type_id in materials:
                materials[product_type_id]["total_qty"] += qty
            else:
                materials[product_type_id] = {
                    "name": name,
                    "total_qty": float(qty),
                    "volume": vol,
                }
            return

        bp_tid = bp_row[0]
        per_run = _get_per_run_output(conn, bp_tid)
        if per_run < 1:
            per_run = 1
        runs_needed = math.ceil(qty / per_run)

        mats = conn.execute(
            "SELECT material_type_id, quantity "
            "FROM blueprint_materials WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
            (bp_tid,),
        ).fetchall()
        for mat_id, mat_qty in mats:
            mat_total = calc_material_for_runs(mat_qty, _DEFAULT_WASTE, me, runs_needed)
            # 由 _expand 内部统一记录，避免重复（父循环记录一次 + _expand 再记一次 → 翻倍）
            _expand(mat_id, mat_total, me)

    for plan in plans:
        pid = plan.get("product_type_id")
        runs = plan.get("runs", 1) or 1
        parallels = plan.get("parallels", 1) or 1
        me = plan.get("me_level", me_level) or me_level
        total_qty = runs * parallels
        _expand(pid, total_qty, me)

    return materials


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

        # 递归 BOM 查找中间产品溢出
        overflow_details: list[dict] = []
        seen_over: set[int] = set()

        def _find_overflow(
            pid: int,
            qty: int,
            me_lvl: int,
            max_d: int,
            seen: set[int],
            out: list[dict],
            depth: int = 0,
        ):
            if pid in seen or depth > max_d:
                return
            seen.add(pid)

            bp_row = conn.execute(
                "SELECT blueprint_type_id, bp.quantity FROM blueprint_products bp "
                "WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing' LIMIT 1",
                (pid,),
            ).fetchone()
            if not bp_row:
                return
            bp_tid, per_run_out = bp_row
            if not per_run_out or per_run_out < 1:
                per_run_out = 1

            runs_needed = math.ceil(qty / per_run_out)
            actual_output = runs_needed * per_run_out
            overflow = actual_output - qty

            if overflow > 0:
                mid_name = _resolve_name(conn, pid)
                out.append({
                    "type_id": pid,
                    "name": mid_name,
                    "needed": qty,
                    "per_run": per_run_out,
                    "runs": runs_needed,
                    "produced": actual_output,
                    "overflow": overflow,
                })

            mats = conn.execute(
                "SELECT material_type_id, quantity "
                "FROM blueprint_materials WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
                (bp_tid,),
            ).fetchall()
            for mid, mqty in mats:
                mat_total = calc_material_for_runs(mqty, _DEFAULT_WASTE, me_lvl, runs_needed)
                _find_overflow(mid, mat_total, me_lvl, max_d, seen, out, depth + 1)

        _find_overflow(pid, total_qty, me, max_depth, seen_over, overflow_details)
        overflow_text = _format_overflow(overflow_details)

        results.append({
            "plan_name": name,
            "product_type_id": pid,
            "total_qty": total_qty,
            "plan_value": plan_value,
            "material_cost": mat_cost,
            "profit": profit,
            "margin_pct": plan.get("margin", 0) * 100 if plan.get("margin") else 0,
            "sell_price": plan_price,
            "status": status,
            "overflow_details": overflow_details,
            "overflow_text": overflow_text,
            "has_overflow": len(overflow_details) > 0,
        })

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

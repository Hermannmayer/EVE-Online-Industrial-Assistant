"""
计划指标计算 — 个人利润率 / 拆解母项成本调整（纯函数，无 DB/Qt 依赖）。

从 scoring_service.ScoringService 中抽出的纯算法：这些函数只做数值计算，
输入全部显式传入（result dict + 库存成本映射 + 流程数），不触碰数据库/容器，
便于脱离 SQLite/Qt 单测。ScoringService 保留 thin delegate 向后兼容。
"""

from __future__ import annotations


def calculate_personal_margin(
    result: dict,
    inv_map: dict[int, tuple[int, float]],
    runs: int = 1,
    parallels: int = 1,
    cost_overrides: dict[int, float] | None = None,
) -> float:
    """计算考虑库存成本的个人利润率（%）。

    与市场利润率同口径：仅把材料成本替换为库存成本
    （库存不足部分按材料市场 unit_price 补齐），安装费/经纪人费/销售税与市场列完全一致。
    无库存时返回值与 result 的市场 margin 在 2 位小数内严格相等。

    Args:
        result: calculate_plan_metrics() 的返回 dict
                （需含 revenue_per_run / fees_per_run / materials / margin）
        inv_map: get_inventory_cost_map() 的返回 {type_id: (总数量, 加权平均成本)}
        runs / parallels: 流程数 / 并行数
        cost_overrides: 可选 {type_id: 固定成本}——拆解母项的子项自制件按其制造价计，
                        不再走库存/市场价。

    Returns:
        个人利润率（%），round 到 2 位小数。异常或无效输入回退 result 的市场 margin。

    精度契约：必须读未取整的 revenue_per_run / fees_per_run，
    禁用已 round 的 revenue / fees，否则"无库存=市场列"的严格相等会被破坏。
    """
    try:
        total_mult = max(runs, 1) * max(parallels, 1)
        fallback = result.get("margin", 0) or 0
        revenue_per_run = result.get("revenue_per_run", 0) or 0
        fees_per_run = result.get("fees_per_run", 0) or 0
        materials = result.get("materials", []) or []

        if not materials or revenue_per_run <= 0:
            return fallback

        total_personal_cost = 0.0
        for mat in materials:
            qty_per_run = mat.get("qty", 0) or 0
            if qty_per_run <= 0:
                continue
            mid = mat.get("type_id")
            need = qty_per_run * total_mult
            if cost_overrides and mid in cost_overrides:
                # 子项自制件：成本 = 子项制造价（合计，非库存/市场价）
                mat_cost = cost_overrides[mid]
            else:
                unit_price = mat.get("unit_price", 0) or 0
                stock_qty, stock_cost = inv_map.get(mid, (0, 0))
                if stock_qty >= need:
                    mat_cost = need * stock_cost
                elif stock_qty > 0:
                    mat_cost = stock_qty * stock_cost + (need - stock_qty) * unit_price
                else:
                    mat_cost = need * unit_price
            total_personal_cost += mat_cost

        total_cost = total_personal_cost + fees_per_run * total_mult
        if total_cost <= 0:
            return fallback

        total_revenue = revenue_per_run * total_mult
        margin = (total_revenue - total_cost) / total_cost * 100
        return round(margin, 2)
    except Exception:
        return result.get("margin", 0) or 0


def child_manufacturing_cost(plan: dict, metrics: dict) -> float:
    """一条子项产线的总制造价 = 材料成本 + 制造作业费（安装费）。

    Args:
        plan: 子项计划 dict（runs/parallels 用于把单轮安装费放大到整条产线）。
        metrics: calculate_plan_metrics() 对子项返回的 dict
                 （须含 material_cost 与 breakdown.installation_fee）。

    Returns:
        子项产线制造价合计（材料 + 作业费）。breakdown 缺失时兜底仅材料成本。
    """
    material = metrics.get("material_cost", 0) or 0
    breakdown = metrics.get("breakdown", {}) or {}
    job_per_run = breakdown.get("installation_fee", 0) or 0
    total_mult = max(int(plan.get("runs", 1)), 1) * max(int(plan.get("parallels", 1)), 1)
    return round(material + job_per_run * total_mult, 2)


def adjust_mother_metrics(
    metrics: dict,
    sub_cost_map: dict[int, float],
    total_mult: int,
) -> tuple[float, float, float, dict[int, float]]:
    """把拆解母项的自制子项按其制造价计入成本，其余材料仍按市场价。

    Args:
        metrics: calculate_plan_metrics() 对母项返回的 dict
                 （须含 materials/revenue/fees，materials 为每轮量）。
        sub_cost_map: {子项 product_type_id: 子项制造价（整条产线合计，见 child_manufacturing_cost）}。
        total_mult: runs × parallels。

    Returns:
        (调整后 material_cost, 调整后 profit, 调整后 margin, cost_overrides)。
        cost_overrides 供 calculate_personal_margin 的个人利润率计算使用。
        不修改入参 metrics。
    """
    revenue = metrics.get("revenue", 0) or 0
    fees = metrics.get("fees", 0) or 0
    new_material_cost = 0.0
    cost_overrides: dict[int, float] = {}
    for mat in metrics.get("materials", []) or []:
        mid = mat.get("type_id")
        qty_per_run = mat.get("qty", 0) or 0
        if qty_per_run <= 0:
            continue
        if mid in sub_cost_map:
            new_material_cost += sub_cost_map[mid]
            cost_overrides[mid] = sub_cost_map[mid]
        else:
            new_material_cost += qty_per_run * total_mult * (mat.get("unit_price", 0) or 0)
    new_material_cost = round(new_material_cost, 2)
    profit = round(revenue - new_material_cost - fees, 2)
    denom = new_material_cost + fees
    margin = round(profit / denom * 100, 2) if denom > 0 else 0.0
    return new_material_cost, profit, margin, cost_overrides

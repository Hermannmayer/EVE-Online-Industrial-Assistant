"""
计划指标计算 — 个人利润率 / 拆解母项成本调整 / 科研作业成本（纯函数，无 DB/Qt 依赖）。

从 scoring_service.ScoringService 中抽出的纯算法：这些函数只做数值计算，
输入全部显式传入（result dict + 库存成本映射 + 流程数），不触碰数据库/容器，
便于脱离 SQLite/Qt 单测。ScoringService 保留 thin delegate 向后兼容。

科研作业成本（拷贝/发明/研究）与制造共用 `domain.formulas` 的 EIV / 安装费 /
材料量公式，区别只在「作业次数」的口径：制造按 runs×parallels，科研按作业次数。
"""

from __future__ import annotations

from domain.formulas import calc_eiv, calc_job_cost_fees, calc_material_for_runs
from domain.research import (
    Decryptor,
    invention_attempts,
    invention_output_runs,
    invention_probability,
)

# 安装费税费兜底（与 services.manufacturing_calculator 的 NPC 口径一致）
DEFAULT_FACILITY_TAX = 0.0025
DEFAULT_SCC_SURCHARGE = 0.04


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


def mother_subitem_cost_map(
    base_results: dict[int, tuple[dict, dict]],
    mother: dict,
) -> dict[int, float]:
    """母项同组更深子项的自制成本映射 {子项 product_type_id: 制造价合计}。

    子项制造价 = child_manufacturing_cost（材料 + 作业费×runs×parallels）。
    供批量重算 / 单条编辑复用：母项材料表中命中子项的行由市场价换成制造价。
    非母项（无 group）或同组无更深子项时返回空 dict。
    """
    gid = mother.get("group_id") or mother.get("group_number")
    if not gid:
        return {}
    lvl = int(mother.get("child_level") or mother.get("sub_level") or 0)
    subs = [
        (p, r)
        for _pid, (p, r) in base_results.items()
        if (p.get("group_id") or p.get("group_number")) == gid
        and int(p.get("child_level") or p.get("sub_level") or 0) > lvl
    ]
    if not subs:
        return {}
    return {int(p["product_type_id"]): child_manufacturing_cost(p, r) for p, r in subs if p.get("product_type_id")}


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


# ═══════════════════════════════════════════════════════════
#  科研作业成本（拷贝 / 发明 / 研究）
#
#  与制造的区别：材料不受 ME 减免（拷贝/发明/研究都不吃 ME），作业次数由活动决定。
#  输入全部显式传入（材料清单 + 单价 + SCI + 技能等级），无 DB/Qt 依赖。
# ═══════════════════════════════════════════════════════════


def job_batch_materials(
    materials: list[tuple[int, int]],
    job_count: int,
    *,
    me_level: int = 0,
) -> list[tuple[int, int]]:
    """一次科研作业批次的材料总量 [(type_id, qty)]。

    materials: [(material_type_id, 蓝图基础量)]（来自 blueprint_materials）
    job_count: 作业次数（发明=尝试次数，拷贝=总授权流程数，研究=目标级数）
    me_level: 科研活动恒为 0（不吃材料效率），参数保留供扩展
    """
    n = max(1, int(job_count))
    return [(int(mid), int(calc_material_for_runs(qty, 10, me_level, n))) for mid, qty in materials]


def material_cost_of(
    mats: list[tuple[int, int]],
    prices: dict[int, float],
    extra: list[tuple[int, float]] | None = None,
) -> float:
    """材料总价 = Σ(基础量 × 单价) + extra([(type_id, qty), ...] 小数量的附加项)。

    extra 用于解码器（每次作业消耗 1 个，数量为作业次数而非整数材料）。
    """
    total: float = 0.0
    for mid, qty in mats:
        total += float(prices.get(mid, 0.0)) * float(qty)
    for mid, extra_qty in extra or []:
        total += float(prices.get(mid, 0.0)) * float(extra_qty)
    return total


def _installation_fee(
    eiv_materials: list[tuple[int, int]],
    prices: dict[int, float],
    sci: float,
    *,
    structure_mult: float = 1.0,
    facility_tax: float = DEFAULT_FACILITY_TAX,
    alpha_tax: float = 0.0,
    scc: float = DEFAULT_SCC_SURCHARGE,
) -> float:
    """按 EIV（材料基础量 × adjusted_price）算安装费。

    EIV 用**基础量**（不含 ME），与游戏安装费口径一致。
    """
    eiv = calc_eiv([(qty, float(prices.get(mid, 0.0))) for mid, qty in eiv_materials])
    fees = calc_job_cost_fees(eiv, sci, structure_mult, facility_tax, scc, alpha_tax)
    return float(fees["total_fee"])


def invention_plan_cost(
    *,
    base_probability: float,
    materials: list[tuple[int, int]],
    prices: dict[int, float],
    sci: float,
    science_skill_1: int = 0,
    science_skill_2: int = 0,
    encryption_skill: int = 0,
    decryptor: Decryptor | None = None,
    base_runs: int = 10,
    output_runs_needed: int = 1,
    input_bpc_cost_per_run: float = 0.0,
    success_rate_override: float | None = None,
    actual_output_runs: int | None = None,
    structure_mult: float = 1.0,
    facility_tax: float = DEFAULT_FACILITY_TAX,
    alpha_tax: float = 0.0,
) -> dict:
    """发明作业成本（期望值口径）。

    每次「尝试」消耗: 数据核心材料 + 解码器(可选) + 输入 T1 BPC 的 1 个授权流程。
    成功时产出 T2 BPC: 流程数 = base_runs + 解码器修正。

    参数:
        base_probability: SDE 基础成功率
        materials: 数据核心材料 [(type_id, 基础量)]（一次尝试的量）
        prices: {type_id: 单价}（adjusted_price 优先，缺失用 sell_price）
        sci: 设施星系该活动的成本指数
        decryptor: 解码器（None = 不使用）
        base_runs: 产出 BPC 的基础流程数（SDE 实测 = min(T1 拷贝上限, T2 制造上限)）
        output_runs_needed: 需要的 T2 BPC 总流程数
        input_bpc_cost_per_run: 输入 T1 BPC 的每流程成本（0 = 未配置，不计入）
        success_rate_override: 用户手填的预期成功率（None = 按技能算）
        actual_output_runs: 完成后手填的**实际**产出流程（None = 未回填，用期望值）

    返回:
        {success_rate, runs_per_bpc, attempts, material_cost, fee, input_bpc_cost,
         total_cost, output_runs, expected_runs, bpc_unit_cost, is_actual, materials}
    """
    rate = (
        float(success_rate_override)
        if success_rate_override is not None
        else invention_probability(
            base_probability,
            science_skill_1,
            science_skill_2,
            encryption_skill,
            prob_mult=decryptor.prob_mult if decryptor else 1.0,
        )
    )
    rate = min(1.0, max(0.0, rate))
    runs_per_bpc = invention_output_runs(base_runs, decryptor)

    attempts = invention_attempts(output_runs_needed, rate, runs_per_bpc)
    # 每次尝试的数据核心；解码器每次消耗 1 个（成败都扣）
    per_attempt_mats = job_batch_materials(materials, 1)
    # 尝试次数为 0（成功率为 0 或产出为 0）→ 无作业、无消耗
    batch_mats = job_batch_materials(materials, attempts) if attempts > 0 else []
    if decryptor and attempts > 0:
        batch_mats = batch_mats + [(decryptor.type_id, attempts)]

    total_material_cost = material_cost_of(batch_mats, prices)
    total_fee = _installation_fee(
        batch_mats,
        prices,
        sci,
        structure_mult=structure_mult,
        facility_tax=facility_tax,
        alpha_tax=alpha_tax,
    )
    input_bpc_cost = float(input_bpc_cost_per_run) * attempts
    total_cost = total_material_cost + total_fee + input_bpc_cost

    # 期望产出（未回填时使用）
    expected_runs = attempts * runs_per_bpc
    # 实际口径：用户回填后 output_runs 取实际值（0 = 失败）
    is_actual = actual_output_runs is not None
    output_runs = int(actual_output_runs) if actual_output_runs is not None else expected_runs
    bpc_unit_cost = total_cost / output_runs if output_runs > 0 else 0.0

    return {
        "success_rate": round(rate, 6),
        "runs_per_bpc": runs_per_bpc,
        "attempts": attempts,
        "material_cost": round(total_material_cost, 2),
        "fee": round(total_fee, 2),
        "input_bpc_cost": round(input_bpc_cost, 2),
        "total_cost": round(total_cost, 2),
        "output_runs": output_runs,
        "expected_runs": expected_runs,
        "bpc_unit_cost": round(bpc_unit_cost, 2),
        "is_actual": is_actual,
        "materials": per_attempt_mats,  # 每尝试一次的量（供采购/展示）
    }


def copying_plan_cost(
    *,
    materials: list[tuple[int, int]],
    prices: dict[int, float],
    sci: float,
    total_copy_runs: int,
    copies: int = 1,
    structure_mult: float = 1.0,
    facility_tax: float = DEFAULT_FACILITY_TAX,
    alpha_tax: float = 0.0,
) -> dict:
    """拷贝作业成本。材料与时长按**总授权流程数**计，无概率项。

    返回 {material_cost, fee, total_cost, per_copy_cost, copies, runs_per_copy}。
    """
    n = max(1, int(total_copy_runs))
    copies = max(1, int(copies))
    batch = job_batch_materials(materials, n)
    mat = material_cost_of(batch, prices)
    fee = _installation_fee(
        batch, prices, sci, structure_mult=structure_mult, facility_tax=facility_tax, alpha_tax=alpha_tax
    )
    total = mat + fee
    return {
        "material_cost": round(mat, 2),
        "fee": round(fee, 2),
        "total_cost": round(total, 2),
        "total_copy_runs": n,
        "copies": copies,
        "runs_per_copy": max(1, n // copies),
        "per_copy_cost": round(total / copies, 2),
        "materials": batch,
    }


def research_plan_cost(
    *,
    materials: list[tuple[int, int]],
    prices: dict[int, float],
    sci: float,
    target_level: int = 1,
    structure_mult: float = 1.0,
    facility_tax: float = DEFAULT_FACILITY_TAX,
    alpha_tax: float = 0.0,
) -> dict:
    """ME/TE 研究作业成本。

    ⚠️ 材料按「每个等级固定量」线性外推（SDE 的 research_* 材料是单级量，
    实际游戏里各级材料/时长递增）。目标是给出量级正确的估算，不追求精确。
    """
    n = max(1, int(target_level))
    batch = job_batch_materials(materials, n)
    mat = material_cost_of(batch, prices)
    fee = _installation_fee(
        batch, prices, sci, structure_mult=structure_mult, facility_tax=facility_tax, alpha_tax=alpha_tax
    )
    return {
        "material_cost": round(mat, 2),
        "fee": round(fee, 2),
        "total_cost": round(mat + fee, 2),
        "target_level": n,
        "materials": batch,
    }

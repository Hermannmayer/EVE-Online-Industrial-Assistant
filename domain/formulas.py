"""
制造计算器 — 所有制造相关公式的唯一存放地。

纯函数，无状态，无 DB 依赖，可直接用 pytest 测试。

公式来源:
    - 客户端 SDE 技能描述（第一方文案，`data/typeIDs.yaml`）：技能系数以它为准
    - EVE University Wiki: https://wiki.eveuniversity.org/Manufacturing
    - fuzzwork industry.py（生产环境参考实现）
    - Viridian 税改后公式
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any

# 浮点精度补偿：避免 1.1 * 100 = 110.00000000000001 → ceil 到 111
_FP_EPSILON = 1e-10

# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════

DEFAULT_WASTEFACTOR = 10  # T1 兜底
WASTEFACTOR_BY_CATEGORY: dict[str, int] = {
    "T1": 10,
    "T2": 2,
    "T3_rig": 5,
    "capital": 12,
    "faction": 15,
}

SCC_SURCHARGE = 0.04  # 固定 4%，Viridian 引入
FACILITY_TAX_NPC = 0.0025  # NPC 空间站设施税率 0.25%
ALPHA_TAX = 0.0025  # Alpha 克隆额外税（Omega=0）

STRUCTURE_TIME_RAITARU = 0.85  # 小型工程站 -15%
STRUCTURE_TIME_ATHANOR = 0.80  # 中型 -20%
STRUCTURE_TIME_TATARA = 0.75  # 大型 -25%
STRUCTURE_TIME_SOTIYO = 0.70  # 超大型 -30%

STRUCTURE_MAT_SAVING = 1.0  # 工程站材料减免乘数（默认无，Upwell 结构 0.99 = -1%）

INDUSTRY_SKILL_MULT = 0.04  # 工业理论 (3380) 每级 -4% 时间
ADV_INDUSTRY_SKILL_MULT = 0.03  # 高级工业理论 (3388) 每级 -3% 时间
TE_MULT_PER_LEVEL = 0.01  # TE 每级 -1% 时间（TE 存 0-20 的百分比，故等价于游戏里每级 2%×10 级）
# 科研/反应系数取自客户端 SDE 技能描述（第一方文案）：
#   3403 研究概论「每升一级，蓝图时间效率研究的速度提升 5%」
#   3409 冶金学「每升一级，材料效率研究的速度提升 5%」
#   3402 科学原理「每升一级，蓝图复制的速度提升 5%」
#   45746 反应理论「每升一级，反应时间减少 4%」
RESEARCH_SKILL_MULT = 0.05
METALLURGY_SKILL_MULT = 0.05
SCIENCE_SKILL_MULT = 0.05  # 科学原理（仅复制）
REACTIONS_SKILL_MULT = 0.04  # 反应理论（仅反应）
# 蓝图所需技能：11452 机械工程学「每升一级，所有需要机械工程学技能的物品的生产时间减少 1%」
BP_SKILL_TIME_MULT = 0.01


# ═══════════════════════════════════════════════════════════
#  材料浪费
# ═══════════════════════════════════════════════════════════


def _waste_mult(wastefactor: int, me_level: int) -> float:
    """保留兼容，新公式已不使用 wastefactor。"""
    if me_level < 0:
        me_level = 0
    return 1.0 + (wastefactor / 100.0) / (1.0 + me_level)


def calc_waste_factor(wastefactor: int, me_level: int) -> float:
    """计算材料减成倍率（相对 SDE quantity）。

    线性公式: (100 - me_level) / 100
    ME 0 → 1.0（100%），ME 10 → 0.9（90%），每级减 1%。
    """
    if me_level < 0:
        me_level = 0
    return (100.0 - me_level) / 100.0


def calc_material_per_run(
    db_qty: int,
    wastefactor: int = 10,
    me_level: int = 0,
    structure_mat_saving: float = 1.0,
) -> int:
    """计算每轮次制造所需材料数量。

    线性公式: ceil(db_qty × (100 - ME) / 100 × 结构减免)
    ME 每级减 1%，最高 10 级（ME 10 = 基础量的 90%）。
    wastefactor 参数保留仅做兼容，不再参与计算。
    """
    if me_level < 0:
        me_level = 0
    me_level = min(me_level, 10)
    result = db_qty * (100.0 - me_level) / 100.0 * structure_mat_saving
    return math.ceil(result - _FP_EPSILON)


#: 单件材料（每轮基础量 ≤ 1）豁免材料效率。
#: 官方口径（CCP《Material Efficiency Research》）：「Whole and single items, as in
#: "1 unit needed per production run", will not be affected by this calculation.
#: … building 10 Paladins will always require 10 Apocalypse, independent of any
#: Material Efficiency bonus.」——即按 `基础量 × 作业数` 计，不减 ME。
_SINGLE_UNIT_EXEMPT = True


def calc_material_for_runs(
    db_qty: int,
    wastefactor: int = 10,
    me_level: int = 0,
    runs: int = 1,
    structure_mat_saving: float = 1.0,
) -> int:
    """计算多轮次制造所需材料总量。

    材料效率适用于整个项目总量（不逐轮次取整）:
    ceil(db_qty × runs × (100 - ME) / 100 × 结构减免)

    单件材料（基础量 ≤ 1）按 `基础量 × 作业数` 计，不减 ME（见 `_SINGLE_UNIT_EXEMPT`）。

    **本函数是「一批要多少料」的单一定义处**：豁免以前只写在 `material_total_for_runs` 里，
    而 BOM 展开、计划分解、采购聚合、`domain/bom.py` 都直接调本函数 —— 同一个蓝图会因为
    走不同代码路径而要出不同的料（`calc_material_for_runs(1, 10, 10, 10)` 曾算出 9，
    官方口径是 10，差的就是 T2 组件那类单件料）。
    """
    if db_qty <= 0:
        return 0
    n = max(1, runs)
    if db_qty <= 1 and _SINGLE_UNIT_EXEMPT:
        return db_qty * n
    me_level = min(max(me_level, 0), 10)
    total = db_qty * n * (100.0 - me_level) / 100.0 * structure_mat_saving
    return math.ceil(total - _FP_EPSILON)


def material_total_for_runs(
    material: Mapping[str, Any] | Any,
    total_runs: int,
    *,
    me_level: int = 0,
    structure_mat_saving: float = 1.0,
) -> int:
    """单条材料明细 → 整批（`total_runs` 次作业）需求量（明细形态的薄封装）。

    `services/scoring_service.py` 的两处缩放、`services/plan_execution.material_requirements`
    与 `ui_qml/bridge/cost_breakdown_bridge._build_material_rows` 走它；
    取整与豁免口径的单一定义处在 `calc_material_for_runs`（本函数只做字段提取）。

    口径（EVE）：对**整批**取一次整 —— `ceil(基础量 × 作业数 × (100-ME)/100 × 结构减免)`。
    逐轮取整后再乘作业数（`ceil(基础量 × …) × 作业数`）会**系统性地多要货**：
    基础量 22、ME10、2510 次作业时，逐轮口径要 50,200，整批口径只要 49,698。

    `material` 可以是 dict（取 `base_qty` / `wastefactor`）或带同名属性的对象。
    """
    base = int(_field(material, "base_qty") or 0)
    if base <= 0:
        return 0
    return calc_material_for_runs(
        base,
        int(_field(material, "wastefactor") or DEFAULT_WASTEFACTOR),
        me_level,
        runs=max(1, int(total_runs)),
        structure_mat_saving=structure_mat_saving,
    )


def _field(material: Mapping[str, Any] | Any, key: str) -> Any:
    """dict / 对象两吃 —— 材料明细在评分链路里两种形态都有。"""
    if isinstance(material, Mapping):
        return material.get(key)
    return getattr(material, key, None)


# ═══════════════════════════════════════════════════════════
#  安装费（Job Cost）
# ═══════════════════════════════════════════════════════════


def calc_eiv(
    materials: list[tuple[int, float]],
) -> float:
    """计算 Estimated Item Value (EIV)。

    公式: Σ(material_quantity × adjusted_price)，ME0 无浪费状态

    参数:
        materials: [(material_qty, adjusted_price), ...]
                   material_qty = 蓝图基础数量（不含浪费）
                   adjusted_price = ESI adjusted price（或兜底 sell_price）

    返回:
        EIV 总和
    """
    return sum(qty * price for qty, price in materials)


def calc_job_cost_fees(
    eiv: float,
    sci: float,
    structure_mult: float = 1.0,
    facility_tax: float = FACILITY_TAX_NPC,
    scc: float = SCC_SURCHARGE,
    alpha_tax: float = 0.0,
) -> dict[str, float]:
    """计算制造安装费（加法结构）。

    公式: job_cost = EIV × (SCI × SB + FT + SCC + AT)

    参数:
        eiv: Estimated Item Value（所有材料 adjusted_price × 基础数量）
        sci: 系统成本指数（System Cost Index）
        structure_mult: 设施加成系数（NPC ≈1.1, Upwell <1=折扣）
        facility_tax: 设施税率（NPC 0.25% = 0.0025）
        scc: SCC surcharge（固定 4% = 0.04，Viridian 引入）
        alpha_tax: Alpha 账号额外税（0.25% = 0.0025, Omega=0）

    返回:
        {
            "system_cost": float,    # SCI × SB 部分
            "facility_tax": float,   # FT 部分
            "scc": float,            # SCC 部分（固定 4%）
            "alpha_tax": float,      # Alpha 税（如有）
            "total_fee": float,      # 安装费总和
        }
    """
    system_cost = eiv * sci * structure_mult
    facility = eiv * facility_tax
    surcharge = eiv * scc
    alpha = eiv * alpha_tax if alpha_tax > 0 else 0.0

    return {
        "system_cost": round(system_cost, 2),
        "facility_tax": round(facility, 2),
        "scc": round(surcharge, 2),
        "alpha_tax": round(alpha, 2),
        "total_fee": round(system_cost + facility + surcharge + alpha, 2),
    }


# ═══════════════════════════════════════════════════════════
#  生产时间
# ═══════════════════════════════════════════════════════════


def calc_production_time(
    base_time: int,
    industry_skill: int = 5,
    adv_industry_skill: int = 5,
    te_level: int = 0,
    structure_time_mod: float = 1.0,
    required_skill_levels: Sequence[int] | None = None,
) -> float:
    """计算实际制造时间（秒）。

    公式:
        bp_mod = Π(1 - 0.01 × 蓝图所需技能等级)      ← 客户端文案：机械工程学等每级 -1%
        skill_mod = (1 - 0.04 × industry) × (1 - 0.03 × adv_industry)
        actual_time = base_time × skill_mod × bp_mod × (1 - 0.01 × TE) × structure_time_mod

    参数:
        base_time: 蓝图基础制造时间（秒）
        industry_skill: 工业理论等级（0-5）
        adv_industry_skill: 高级工业理论等级（0-5）
        te_level: TE 研究等级（0-20）
        structure_time_mod: 工程站时间减免（NPC=1.0, Raitaru=0.85 等）
        required_skill_levels: 该蓝图**制造活动所需技能**的角色等级列表（如机械工程学 L5）。
            SDE 技能描述原文：「每升一级，所有需要机械工程学技能的物品的生产时间减少 1%」。
            None/空 → 不计该项（保持旧调用方行为）。

    返回:
        实际时间（秒）
    """
    skill_mod = (1.0 - INDUSTRY_SKILL_MULT * max(0, industry_skill)) * (
        1.0 - ADV_INDUSTRY_SKILL_MULT * max(0, adv_industry_skill)
    )
    bp_mod = 1.0
    for lvl in required_skill_levels or ():
        bp_mod *= 1.0 - BP_SKILL_TIME_MULT * min(max(0, int(lvl)), 5)
    te_mod = 1.0 - TE_MULT_PER_LEVEL * max(0, te_level)
    return base_time * skill_mod * bp_mod * te_mod * structure_time_mod

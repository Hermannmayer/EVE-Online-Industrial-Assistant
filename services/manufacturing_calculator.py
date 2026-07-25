"""
制造计算器 — 所有制造相关公式的唯一存放地。

纯函数，无状态，无 DB 依赖，可直接用 pytest 测试。

公式来源:
    - EVE University Wiki: https://wiki.eveuniversity.org/Manufacturing
    - fuzzwork industry.py（生产环境参考实现）
    - Viridian 税改后公式
"""

import math

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

SCC_SURCHARGE = 0.04        # 固定 4%，Viridian 引入
FACILITY_TAX_NPC = 0.0025   # NPC 空间站设施税率 0.25%
ALPHA_TAX = 0.0025          # Alpha 克隆额外税（Omega=0）

STRUCTURE_TIME_RAITARU = 0.85    # 小型工程站 -15%
STRUCTURE_TIME_ATHANOR = 0.80    # 中型 -20%
STRUCTURE_TIME_TATARA = 0.75     # 大型 -25%
STRUCTURE_TIME_SOTIYO = 0.70     # 超大型 -30%

STRUCTURE_MAT_SAVING = 1.0        # 工程站材料减免乘数（默认无，Upwell 结构 0.99 = -1%）

INDUSTRY_SKILL_MULT = 0.04       # 工业理论 (3380) 每级 -4% 时间
ADV_INDUSTRY_SKILL_MULT = 0.03   # 高级工业理论 (3388) 每级 -3% 时间
TE_MULT_PER_LEVEL = 0.01         # TE 每级 -1% 时间


# ═══════════════════════════════════════════════════════════
#  材料浪费
# ═══════════════════════════════════════════════════════════


def calc_waste_factor(wastefactor: int, me_level: int) -> float:
    """计算材料浪费倍率。

    公式: 1 + (wasteFactor/100) / (1 + ME)

    参数:
        wastefactor: SDE wasteFactor（T1=10, T2=2, T3=5, 旗舰=12）
        me_level: 材料效率研究等级

    返回:
        浪费倍率（永远 > 1.0，永远不会到 0）
    """
    if me_level < 0:
        me_level = 0
    return 1.0 + (wastefactor / 100.0) / (1.0 + me_level)


def calc_material_per_run(
    base_qty: int,
    wastefactor: int,
    me_level: int,
    structure_mat_saving: float = 1.0,
) -> int:
    """计算每轮次制造所需材料数量（含浪费 + 向上取整）。

    公式: ceil(base_qty × waste_factor × structure_mat_saving)

    参数:
        base_qty: 蓝图材料基础数量
        wastefactor: SDE wasteFactor
        me_level: ME 等级
        structure_mat_saving: 工程站材料减免乘数（默认 1.0，Upwell 结构 0.99）

    返回:
        每轮次需要的材料数量（整数）
    """
    waste_factor = calc_waste_factor(wastefactor, me_level)
    return math.ceil(base_qty * waste_factor * structure_mat_saving - _FP_EPSILON)


def calc_material_for_runs(
    base_qty: int,
    wastefactor: int,
    me_level: int,
    runs: int,
    structure_mat_saving: float = 1.0,
) -> int:
    """计算多轮次制造所需材料总量 = per_run × runs。

    参数与 calc_material_per_run 相同。
    """
    per_run = calc_material_per_run(base_qty, wastefactor, me_level, structure_mat_saving)
    return per_run * max(1, runs)


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
) -> float:
    """计算实际制造时间（秒）。

    公式:
        skill_mod = (1 - 0.04 × industry) × (1 - 0.03 × adv_industry)
        actual_time = base_time × skill_mod × (1 - 0.01 × TE) × structure_time_mod

    参数:
        base_time: 蓝图基础制造时间（秒）
        industry_skill: 工业理论等级（0-5）
        adv_industry_skill: 高级工业理论等级（0-5）
        te_level: TE 研究等级（0-20）
        structure_time_mod: 工程站时间减免（NPC=1.0, Raitaru=0.85 等）

    返回:
        实际时间（秒）
    """
    skill_mod = (1.0 - INDUSTRY_SKILL_MULT * max(0, industry_skill)) * (
        1.0 - ADV_INDUSTRY_SKILL_MULT * max(0, adv_industry_skill)
    )
    te_mod = 1.0 - TE_MULT_PER_LEVEL * max(0, te_level)
    return base_time * skill_mod * te_mod * structure_time_mod

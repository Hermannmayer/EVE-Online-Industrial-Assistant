"""科研公式 — 拷贝(copying) / 发明(invention) / ME-TE 研究的纯算法。

纯函数、无状态、无 DB/Qt 依赖，可直接 pytest。数据（基础成功率、材料、时长、
产出上限）由 services 层查出来后按参数传入。

公式来源（详见 docs/eve_wiki_knowledge_base.md「拷贝」「发明」「解码器」节）:
    - EVE University Wiki: https://wiki.eveuniversity.org/Invention
    - CCP 支持中心: 拷贝 / 发明 / 解码器
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════
#  活动常量（与 blueprint.db 的 blueprint_activities.activity 取值一致）
# ═══════════════════════════════════════════════════════════

ACTIVITY_COPYING = "copying"
ACTIVITY_INVENTION = "invention"
ACTIVITY_RESEARCH_ME = "researching_material_efficiency"
ACTIVITY_RESEARCH_TE = "researching_time_efficiency"

# blueprint_materials / blueprint_activities 的列名口径不同：研究活动在材料表里是
# research_material / research_time（无 -ing 后缀），查表时必须用这一套。
MATERIAL_ACTIVITY = {
    ACTIVITY_RESEARCH_ME: "research_material",
    ACTIVITY_RESEARCH_TE: "research_time",
}

# 科研活动集合（拷贝/发明/研究）——用于「这条计划是不是科研作业」的判定。
SCIENCE_ACTIVITIES = frozenset({ACTIVITY_COPYING, ACTIVITY_INVENTION, ACTIVITY_RESEARCH_ME, ACTIVITY_RESEARCH_TE})

# 科学技能 id（reference.db.item.group_id=270 里的技能，用于成功率公式取等级）。
SKILL_RESEARCH = 3403  # Research 研究概论
SKILL_METALLURGY = 3409  # Metallurgy 冶金学

# 发明成功率公式的两个分母（EVE University Wiki: 每级科学技能 +1/30，
# 每级加密技术原理 +1/40）
SCIENCE_SKILL_DIVISOR = 30.0
ENCRYPTION_SKILL_DIVISOR = 40.0

# 发明产出 BPC 的默认 ME/TE（无解码器时）
BASE_INVENTION_ME = 2
BASE_INVENTION_TE = 4


@dataclass(frozen=True)
class Decryptor:
    """解码器修正值。

    ⚠️ 硬编码：reference.db.item_dogma 里这 8 个 type_id 的 dogma_attrs 实测为空 `{}`，
    SDE 没有可查的属性，只能按官方支持中心公布的表格固化。
    来源: docs/eve_wiki_knowledge_base.md「解码器」节（与 EVE University 表一致）。
    """

    type_id: int
    name: str
    prob_mult: float  # 概率倍率（×基础成功率）
    runs_mod: int  # 产出 BPC 流程数修正
    me_mod: int  # 产出 BPC 的 ME 修正
    te_mod: int  # 产出 BPC 的 TE 修正


DECRYPTORS: dict[int, Decryptor] = {
    34201: Decryptor(34201, "加速装置解码器", 1.20, 1, 2, 10),
    34202: Decryptor(34202, "获取装置解码器", 1.80, 4, -1, 4),
    34203: Decryptor(34203, "放大装置解码器", 0.60, 9, -2, 2),
    34204: Decryptor(34204, "等价装置解码器", 1.50, 3, 1, -2),
    34205: Decryptor(34205, "处理装置解码器", 1.10, 0, 3, 6),
    34206: Decryptor(34206, "对称装置解码器", 1.00, 2, 1, 8),
    34207: Decryptor(34207, "优化的获取装置解码器", 1.90, 2, 1, -2),
    34208: Decryptor(34208, "优化的放大装置解码器", 1.10, 7, 2, 0),
}


def get_decryptor(type_id: int | None) -> Decryptor | None:
    """按 type_id 取解码器；None/未知 → None（表示不使用解码器）。"""
    if not type_id:
        return None
    return DECRYPTORS.get(int(type_id))


# ═══════════════════════════════════════════════════════════
#  发明成功率
# ═══════════════════════════════════════════════════════════


def invention_probability(
    base_probability: float,
    science_skill_1: int = 0,
    science_skill_2: int = 0,
    encryption_skill: int = 0,
    *,
    prob_mult: float = 1.0,
) -> float:
    """发明成功率（0~1）。

    公式:
        chance = base × (1 + (science1 + science2)/30 + encryption/40) × decryptor_mult

    参数:
        base_probability: SDE 基础成功率（blueprint_products.probability，0~1］
        science_skill_1/2: 该发明要求的两个科学技能等级（0~5）
        encryption_skill: 加密技术原理等级（0~5）
        prob_mult: 解码器概率倍率（无解码器 = 1.0）

    返回:
        成功率，钳制到 [0, 1]。
    """
    base = float(base_probability or 0)
    if base <= 0:
        return 0.0
    skill_bonus = (max(0, science_skill_1) + max(0, science_skill_2)) / SCIENCE_SKILL_DIVISOR
    skill_bonus += max(0, encryption_skill) / ENCRYPTION_SKILL_DIVISOR
    chance = base * (1.0 + skill_bonus) * max(0.0, prob_mult)
    return min(1.0, max(0.0, chance))


def invention_output_runs(base_runs: int, decryptor: Decryptor | None = None) -> int:
    """一次成功发明产出的 T2 BPC 流程数 = 基础流程 + 解码器流程修正（下限 1）。"""
    mod = decryptor.runs_mod if decryptor else 0
    return max(1, int(base_runs) + mod)


def invention_output_me_te(decryptor: Decryptor | None = None) -> tuple[int, int]:
    """一次成功发明产出的 T2 BPC 的 (ME%, TE%)。

    无解码器 → (2, 4)；有解码器按其修正叠加，各自下限 0。
    """
    if decryptor is None:
        return (BASE_INVENTION_ME, BASE_INVENTION_TE)
    return (max(0, BASE_INVENTION_ME + decryptor.me_mod), max(0, BASE_INVENTION_TE + decryptor.te_mod))


def invention_attempts(runs_needed: int, success_rate: float, runs_per_bpc: int) -> int:
    """达成 runs_needed 流程所需的最少发明尝试次数。

    每次成功产出 runs_per_bpc 流程：attempts = ceil(runs_needed / (success_rate × runs_per_bpc))。
    成功率或产出为 0 → 返回 0（表示无法估算，调用方需显式处理）。

    注意必须用 math.ceil 而非 `-(-a // b)` 的技巧：后者只对整数除法成立，
    这里分母是浮点（如 0.34×10=3.4），整数取整技巧会给出偏大的结果。
    """
    per_attempt = max(0.0, float(success_rate)) * max(0, int(runs_per_bpc))
    if per_attempt <= 0:
        return 0
    need = max(0, int(runs_needed))
    if need <= 0:
        return 0
    return math.ceil(need / per_attempt)


# ═══════════════════════════════════════════════════════════
#  拷贝
# ═══════════════════════════════════════════════════════════


def copy_job_runs(copies: int, runs_per_copy: int, max_production_limit: int) -> int:
    """拷贝项目的总授权流程数（= 项目时长与材料量的计算基数）。

    总流程 = 份数 × 每份流程；每份流程钳制到 [1, max_production_limit]。
    """
    cap = max(1, int(max_production_limit))
    per_copy = min(max(1, int(runs_per_copy)), cap)
    return max(1, int(copies)) * per_copy


# ═══════════════════════════════════════════════════════════
#  科学作业时长
# ═══════════════════════════════════════════════════════════

# 科学作业（拷贝/发明/研究）的时间减免技能。
# 制造走 industry/formulas.calc_production_time（工业理论 4% + 高级工业理论 3%）；
# 科学作业走 research_skill_mult / metallurgy_skill_mult，两者互不叠加。
RESEARCH_TIME_SKILL = "研究概论"  # Research: 每级 -2%
METALLURGY_TIME_SKILL = "冶金学"  # Metallurgy: 每级 -1%（仅研究活动）


def science_job_time(
    base_time: float,
    *,
    activity: str,
    research_skill: int = 0,
    metallurgy_skill: int = 0,
    te_level: int = 0,
    structure_time_mod: float = 1.0,
) -> float:
    """科学作业实际时长（秒）。

    公式（与 calc_production_time 同形，仅换减免技能）:
        time = base_time × (1 − 0.02×研究概论) × (1 − 0.01×冶金学) × (1 − 0.01×TE) × 结构系数

    冶金学只对材料/时间效率研究生效（拷贝/发明不适用），其余活动该项忽略。

    注意: base_time 对 research_material/research_time 是**首级**时长；等级越高越长
    （收益递减）。本函数不做逐级累加，调用方需知这是首级近似。
    """
    from domain.formulas import METALLURGY_SKILL_MULT, RESEARCH_SKILL_MULT, TE_MULT_PER_LEVEL

    mult = 1.0 - RESEARCH_SKILL_MULT * max(0, int(research_skill))
    if activity in (ACTIVITY_RESEARCH_ME, ACTIVITY_RESEARCH_TE):
        mult *= 1.0 - METALLURGY_SKILL_MULT * max(0, int(metallurgy_skill))
    mult *= 1.0 - TE_MULT_PER_LEVEL * max(0, int(te_level))
    return max(0.0, float(base_time)) * max(0.0, mult) * max(0.0, structure_time_mod)

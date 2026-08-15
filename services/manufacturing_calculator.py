"""
制造计算器 — 所有制造相关公式的唯一存放地。

本模块为向后兼容 shim：纯公式实现已下沉到 `domain.formulas`。
新代码请优先从 `domain.formulas` 导入；旧路径继续可用。
"""

from domain.formulas import (  # noqa: F401
    ADV_INDUSTRY_SKILL_MULT,
    ALPHA_TAX,
    DEFAULT_WASTEFACTOR,
    FACILITY_TAX_NPC,
    INDUSTRY_SKILL_MULT,
    SCC_SURCHARGE,
    STRUCTURE_MAT_SAVING,
    STRUCTURE_TIME_ATHANOR,
    STRUCTURE_TIME_RAITARU,
    STRUCTURE_TIME_SOTIYO,
    STRUCTURE_TIME_TATARA,
    TE_MULT_PER_LEVEL,
    WASTEFACTOR_BY_CATEGORY,
    calc_eiv,
    calc_job_cost_fees,
    calc_material_for_runs,
    calc_material_per_run,
    calc_production_time,
    calc_waste_factor,
)

"""工业计划的活动契约 — 每种作业「需要什么输入蓝图 / 产出什么」的唯一真源。

生产计划（production_plans）从「制造计划」泛化为「工业计划」后，
`product_type_id` / `blueprint_type_id` 的语义随 `activity` 变化，
所有消费方（启动校验、蓝图绑定、采购聚合、类别推导、产能占用）
必须经本模块判定，不得各自硬编码 `activity='manufacturing'`。

语义契约:
    activity                      product_type_id 是        blueprint_type_id 是
    ----------------------------  -----------------------  ---------------------
    manufacturing                 造出来的物品              制造蓝图
    copying                       产出的 BPC 代表的蓝图      被拷贝的 BPO
    invention                     产出的 T2/T3 蓝图         被发明的 T2 蓝图（T1 由它反查）
    researching_*_efficiency      被研究的那个蓝图          被研究的 BPO

推论：科研行的产物**不在** `blueprint_products.activity='manufacturing'` 里
（蓝图不是制造品），任何「按产物反查制造蓝图」的逻辑对科研行都会得到错误结果。
"""

from __future__ import annotations

from domain.research import (
    ACTIVITY_COPYING,
    ACTIVITY_INVENTION,
    ACTIVITY_RESEARCH_ME,
    ACTIVITY_RESEARCH_TE,
    SCIENCE_ACTIVITIES,
)

ACTIVITY_MANUFACTURING = "manufacturing"
ACTIVITY_REACTION = "reaction"

# 全部已知活动
ALL_ACTIVITIES = frozenset({ACTIVITY_MANUFACTURING, ACTIVITY_REACTION, *SCIENCE_ACTIVITIES})

# ── 输入蓝图规则 ──
# bpo_or_bpc: BPO 或流程足够的 BPC（制造；现状不变）
# bpo_only:   只能是蓝图原本（拷贝/研究都不接受 BPC）
# bpc_runs:   必须是 BPC，且剩余流程 ≥ 本计划要跑的流程（发明消耗 T1 BPC 流程）
RULE_BPO_OR_BPC = "bpo_or_bpc"
RULE_BPO_ONLY = "bpo_only"
RULE_BPC_RUNS = "bpc_runs"
RULE_NONE = "none"

INPUT_BLUEPRINT_RULE: dict[str, str] = {
    ACTIVITY_MANUFACTURING: RULE_BPO_OR_BPC,
    ACTIVITY_COPYING: RULE_BPO_ONLY,
    ACTIVITY_INVENTION: RULE_BPC_RUNS,
    ACTIVITY_RESEARCH_ME: RULE_BPO_ONLY,
    ACTIVITY_RESEARCH_TE: RULE_BPO_ONLY,
    ACTIVITY_REACTION: RULE_BPO_OR_BPC,
}

# ── 产出口径 ──
OUTPUT_ITEM = "item"  # 造出的物品（入库 inventory_items）
OUTPUT_BPC = "bpc"  # 产出的蓝图拷贝（入库 user_blueprints）
OUTPUT_IMPROVED_BPO = "improved_bpo"  # 被研究后等级提升的蓝图原本（更新 user_blueprints.me/te）

OUTPUT_KIND: dict[str, str] = {
    ACTIVITY_MANUFACTURING: OUTPUT_ITEM,
    ACTIVITY_COPYING: OUTPUT_BPC,
    ACTIVITY_INVENTION: OUTPUT_BPC,
    ACTIVITY_RESEARCH_ME: OUTPUT_IMPROVED_BPO,
    ACTIVITY_RESEARCH_TE: OUTPUT_IMPROVED_BPO,
    ACTIVITY_REACTION: OUTPUT_ITEM,
}

# blueprint_materials / blueprint_activities 名称不一致的活动
MATERIAL_ACTIVITY_NAME: dict[str, str] = {
    ACTIVITY_RESEARCH_ME: "research_material",
    ACTIVITY_RESEARCH_TE: "research_time",
}


def normalize(activity: str | None) -> str:
    """未知/空 activity 一律归 manufacturing（旧行兼容）。"""
    act = str(activity or "").strip()
    return act if act in ALL_ACTIVITIES else ACTIVITY_MANUFACTURING


def is_science(activity: str | None) -> bool:
    """是否科研作业（拷贝/发明/ME-TE 研究）。"""
    return normalize(activity) in SCIENCE_ACTIVITIES


def input_blueprint_rule(activity: str | None) -> str:
    """该活动需要的输入蓝图规则 → RULE_* 常量。"""
    return INPUT_BLUEPRINT_RULE.get(normalize(activity), RULE_BPO_OR_BPC)


def needs_input_blueprint(activity: str | None) -> bool:
    """该活动是否必须绑定一张输入蓝图才能开工。"""
    return input_blueprint_rule(activity) != RULE_NONE


def output_kind(activity: str | None) -> str:
    """该活动的产出口径 → OUTPUT_* 常量。"""
    return OUTPUT_KIND.get(normalize(activity), OUTPUT_ITEM)


def product_is_blueprint(activity: str | None) -> bool:
    """产物是否是一张蓝图（科研=True）→ 消费方禁止按「制造产物」反查关键数据。"""
    return output_kind(activity) != OUTPUT_ITEM


def accepts_bpo(activity: str | None) -> bool:
    """该活动是否接受蓝图原本（BPO）。"""
    return input_blueprint_rule(activity) in (RULE_BPO_OR_BPC, RULE_BPO_ONLY)


def accepts_bpc(activity: str | None) -> bool:
    """该活动是否接受蓝图拷贝（BPC）。"""
    return input_blueprint_rule(activity) in (RULE_BPO_OR_BPC, RULE_BPC_RUNS)


def input_blueprint_hint(activity: str | None) -> str:
    """输入蓝图不足时的用户提示（启动校验用）。

    制造/反应沿用历史文案「无可用蓝图」（既有行为与测试契约）。
    """
    rule = input_blueprint_rule(activity)
    if rule == RULE_BPO_ONLY:
        return "拷贝/研究只能基于蓝图原本(BPO)，蓝图拷贝(BPC)不可再拷贝或研究"
    if rule == RULE_BPC_RUNS:
        return "发明需要绑定 T1 蓝图拷贝(BPC)，且流程数不少于本计划要跑的流程"
    return "无可用蓝图"


def material_activity(activity: str | None) -> str:
    """该活动在 blueprint_materials / blueprint_activities 表里的活动名。"""
    act = normalize(activity)
    return MATERIAL_ACTIVITY_NAME.get(act, act)

"""
EVE Online 游戏公式常量。

来源:
- 制造: https://wiki.eveuniversity.org/Manufacturing
- 贸易: https://wiki.eveuniversity.org/Trade
"""


from core.constants import (
    HUB_NAMES,  # noqa: F401 — re-export
    TRADE_HUB_IDS,
)

# ════════════════════════════════════════════════════
#  经纪人费 — Broker Fee = (1.0% - 0.05% × BrokerRelations) / standing_factor
#  standing_factor = 2^(0.14 × faction_standing + 0.06 × corp_standing)
# ════════════════════════════════════════════════════
BROKER_FEE_BASE = 1.0
BROKER_RELATION_MULT = 0.05  # 经纪人关系学每级降低
STANDING_FACTION_WEIGHT = 0.14  # faction standing 指数权重
STANDING_CORP_WEIGHT = 0.06  # corp standing 指数权重
BROKER_FEE_MIN = 0.1  # 最低经纪人费率，来源: EVE Wiki

# ════════════════════════════════════════════════════
#  制造 — 来源: https://wiki.eveuniversity.org/Manufacturing
# ════════════════════════════════════════════════════
INDUSTRY_SKILL_MULT = 0.04  # 工业理论 (3380) 每级 -4% 时间
ADV_INDUSTRY_SKILL_MULT = 0.03  # 高级工业理论 (3388) 每级 -3% 时间
TE_MULT_PER_LEVEL = 0.01  # TE 每级 -1% 时间
ME_WASTE_BASE = 0.1  # 线性化近似 — 实际公式见 domain/formulas.py 的 calc_waste_factor

# ════════════════════════════════════════════════════
#  贸易 — 来源: https://wiki.eveuniversity.org/Trade
# ════════════════════════════════════════════════════
ACCOUNTING_MULT = 0.03  # 会计学每级 -3% 销售税
SALES_TAX_BASE = 2.0  # 基础销售税率
ADV_BROKER_DISCOUNT = 5  # 高级经纪人关系学每级 +5% 改单折扣
RELIST_BASE_DISCOUNT = 50  # 0 级时改单折扣 50%

# ════════════════════════════════════════════════════
#  精炼 — 来源: https://wiki.eveuniversity.org/Reprocessing
# ════════════════════════════════════════════════════
REPROCESSING_STATION_BASE = 0.50  # NPC 空间站基础精炼率
REPROCESSING_FACILITY_BONUS = 0.52  # 玩家设施基础精炼率（Tatara；Citadel/工程复合体 0.50、Athanor 0.51）
REPROCESSING_IMPLANT_MULT = 0.02  # 精炼植入体插件每级加成
# 技能系数取自**客户端 SDE 的技能描述**（第一方文案，比 wiki 硬）：
#   3385 提炼学概论「每升一级，矿石和冰矿提炼产出提高 3%」
#   3389 提炼效率理论「每升一级…提高 2%」
SKILL_REPROCESSING = 0.03
SKILL_REPROCESSING_EFFICIENCY = 0.02
SKILL_SPECIALIZATION = 0.02  # 矿石专精（如凡晶石处理技术）每级 +2%
# 上限：NPC 站满技能 = 50% × 1.15 × 1.10 × 1.10 = 69.58%（EVEWiki「NPC 站满技能 70%」；
# 旧值 0.575 是误把 wiki 产率表里「概论V、效率理论0」那一格当成了封顶值）
REPROCESSING_MAX_YIELD_NPC = 0.70
REPROCESSING_MAX_YIELD_FACILITY = 0.85  # 玩家结构最高 ~85%（本仓库未建模钻机，留作上限）

# ════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════


def _hub_region_id(hub: str | None) -> int:
    """hub 名称 → region_id，None 或未知时默认 Jita"""
    if hub is None:
        return TRADE_HUB_IDS["Jita"]
    return TRADE_HUB_IDS.get(hub, TRADE_HUB_IDS["Jita"])


# ════════════════════════════════════════════════════
#  精炼产出率计算
# ════════════════════════════════════════════════════


def calc_refining_yield(
    skills: dict | None = None,
    *,
    is_player_facility: bool = False,
    station_base: float | None = None,
    implant_bonus: float = 0.0,
    ore_skill_level: int = 0,
) -> float:
    """计算精炼产出率 (0.0~1.0)

    各项**乘性**叠加（互相独立相乘），依据是客户端技能描述：
        产率 = 基础 × (1 + 3%×提炼学概论) × (1 + 2%×提炼效率理论)
                   × (1 + 2%×矿石专精) × (1 + 插件加成)

    对照 EVEWiki 的 NPC 站产率表（2026-08 修订）逐格吻合：
    概论V = 57.50%、概论V+效率理论V = 63.25%、再加矿石专精V = 69.57%。

    Args:
        skills: 角色技能字典，含 "提炼学概论"、"提炼效率理论"
        is_player_facility: 是否在玩家设施（NPC站 vs Upwell结构）
        station_base: 自定义设施基础率（覆盖默认）
        implant_bonus: 植入体精炼插件加成（0.0~1.0 的比例）
        ore_skill_level: 对应矿石专精技能的等级（0-5）

    Returns:
        精炼产出率（例：0.6325 = 63.25%）
    """
    skills = skills or {}
    base = station_base or (REPROCESSING_FACILITY_BONUS if is_player_facility else REPROCESSING_STATION_BASE)
    mult = (
        (1.0 + SKILL_REPROCESSING * max(0, int(skills.get("提炼学概论", 0) or 0)))
        * (1.0 + SKILL_REPROCESSING_EFFICIENCY * max(0, int(skills.get("提炼效率理论", 0) or 0)))
        * (1.0 + SKILL_SPECIALIZATION * max(0, int(ore_skill_level or 0)))
        * (1.0 + max(0.0, implant_bonus))
    )
    max_yield = REPROCESSING_MAX_YIELD_FACILITY if is_player_facility else REPROCESSING_MAX_YIELD_NPC
    return min(base * mult, max_yield)


# ════════════════════════════════════════════════════
#  共享费率计算 — 制造/贸易评分共用
# ════════════════════════════════════════════════════


def calc_broker_rate(skills: dict, market_data: dict) -> float:
    """计算经纪人费率 (%)。

    公式: (1.0% - 0.05% × 经纪人关系学等级) / 2^(0.14×faction+0.06×corp)
    最低 0.1%。
    """
    broker_rel = skills.get("经纪人关系学", 0)
    faction_standing = market_data.get("faction_standing", 5.0)
    corp_standing = market_data.get("corp_standing", 5.0)
    standing_factor = 2 ** (
        STANDING_FACTION_WEIGHT * max(0, faction_standing) + STANDING_CORP_WEIGHT * max(0, corp_standing)
    )
    rate = (
        (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_rel) / standing_factor
        if standing_factor > 0
        else BROKER_FEE_BASE
    )
    return max(BROKER_FEE_MIN, rate)


def calc_relist_discount(skills: dict) -> float:
    """计算改单折扣 (%)。基础 50%，高级经纪人关系学每级 +5%，上限 100%。"""
    adv_rel = int(skills.get("高级经纪人关系学", 0))
    return min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)


def calc_sales_tax_rate(skills: dict) -> float:
    """计算销售税率 (%)。基础 2%，会计学每级 -3%。"""
    accounting = int(skills.get("会计学", 0))
    return SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

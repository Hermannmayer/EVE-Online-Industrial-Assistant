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
from core.skill_keys import (
    ACCOUNTING,
    ADVANCED_BROKER_RELATIONS,
    BROKER_RELATIONS,
    REPROCESSING,
    REPROCESSING_EFFICIENCY,
)

# ════════════════════════════════════════════════════
#  经纪人费（NPC 空间站）— Broker Fee = 3% − 0.3%×BrokerRelations
#                                       − 0.03%×faction − 0.02%×corp，下限 1%
#  来源: https://wiki.eveuniversity.org/Tax（2026-05-23 修订）+
#        https://wiki.eveuniversity.org/Skills:Trade
#  注意: 玩家 Upwell 结构市场的经纪人费由结构主设定，技能无效（wiki 明示），
#        本公式只适用 NPC 空间站。
# ════════════════════════════════════════════════════
BROKER_FEE_BASE = 3.0
BROKER_RELATION_MULT = 0.3  # 经纪人关系学每级 -0.3 个百分点
STANDING_FACTION_WEIGHT = 0.03  # 势力声望每点 -0.03 个百分点
STANDING_CORP_WEIGHT = 0.02  # 军团声望每点 -0.02 个百分点
BROKER_FEE_MIN = 1.0  # NPC 空间站下限 1%

# ════════════════════════════════════════════════════
#  制造 — 来源: https://wiki.eveuniversity.org/Manufacturing
# ════════════════════════════════════════════════════
INDUSTRY_SKILL_MULT = 0.04  # 工业理论 (3380) 每级 -4% 时间
ADV_INDUSTRY_SKILL_MULT = 0.03  # 高级工业理论 (3388) 每级 -3% 时间
TE_MULT_PER_LEVEL = 0.01  # TE 每级 -1% 时间

# ════════════════════════════════════════════════════
#  贸易 — 来源: https://wiki.eveuniversity.org/Tax +
#        https://wiki.eveuniversity.org/Skills:Trade
#  2019-07 改版后会计学 -11%/级；2025-03-12.1 销售税 4% → 7.5%；
#  高级经纪人关系学 +6 个百分点/级（V 级 = 80% 折扣）。
# ════════════════════════════════════════════════════
ACCOUNTING_MULT = 0.11  # 会计学每级 -11% 销售税
SALES_TAX_BASE = 7.5  # 基础销售税率（2025-03-12.1 起）
ADV_BROKER_DISCOUNT = 6  # 高级经纪人关系学每级 +6 个百分点改单折扣
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
# 玩家结构「完美精炼」上限 90.6%（Upwell 结构 + 满技能 + 满 rig + 4% 植入体）
REPROCESSING_MAX_YIELD_FACILITY = 0.906
# Upwell 结构基础产率（官方 Reprocessing：Citadel/工程复合体 50%、Athanor 51%、Tatara 52%）。
# 旧实现对所有玩家结构一律套 0.52（Tatara），Athanor/Citadel 会算高 1~2 个百分点。
REPROCESSING_STRUCTURE_BASE: dict[str, float] = {
    "citadel": 0.50,
    "engineering_complex": 0.50,
    "athanor": 0.51,
    "tatara": 0.52,
}

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
    structure_type: str | None = None,
    security_mult: float = 0.0,
    rig_mult: float = 0.0,
    implant_bonus: float = 0.0,
    ore_skill_level: int = 0,
) -> float:
    """计算精炼产出率 (0.0~1.0)

    各项**乘性**叠加（互相独立相乘），依据是客户端技能描述：
        产率 = 基础 × (1 + 3%×提炼学概论) × (1 + 2%×提炼效率理论)
                   × (1 + 2%×矿石专精) × (1 + 插件加成) × (1+安全系数) × (1+rig 加成)

    - NPC 空间站基础 = **50%**，与 EVEWiki 产率表逐格吻合：
      概论V = 57.50%、概论V+效率理论V = 63.25%、再加矿石专精V = 69.57%，上限 70%。
    - 玩家 Upwell 结构基础按 `REPROCESSING_STRUCTURE_BASE`（Citadel/工程复合体 50%、
      Athanor 51%、Tatara 52%），上限 90.6%（完美精炼）。
    - ``security_mult`` / ``rig_mult`` 由调用方按结构所在安全区与装配的 rig 提供
      （官方公式里的 security 与 rig 项；具体格值来源存疑，见审计 01-15）。

    Args:
        skills: 角色技能字典，含 "提炼学概论"、"提炼效率理论"
        is_player_facility: 是否在玩家设施（NPC站 vs Upwell结构）
        station_base: 自定义设施基础率（覆盖默认）
        structure_type: Upwell 结构类型 key（citadel/engineering_complex/athanor/tatara），
            仅 is_player_facility=True 时生效；None → Tatara 52%（向后兼容）
        security_mult: 安全区加成（0.0 = 不计，高安 rig 场景通常给小数比例）
        rig_mult: 结构 rig 精炼加成（0.0 = 不计）
        implant_bonus: 植入体精炼插件加成（0.0~1.0 的比例）
        ore_skill_level: 对应矿石专精技能的等级（0-5）

    Returns:
        精炼产出率（例：0.6325 = 63.25%）
    """
    skills = skills or {}
    if station_base is not None:
        base = station_base
    elif is_player_facility:
        base = REPROCESSING_STRUCTURE_BASE.get(structure_type or "tatara", REPROCESSING_FACILITY_BONUS)
    else:
        base = REPROCESSING_STATION_BASE
    mult = (
        (1.0 + SKILL_REPROCESSING * max(0, int(skills.get(REPROCESSING, 0) or 0)))
        * (1.0 + SKILL_REPROCESSING_EFFICIENCY * max(0, int(skills.get(REPROCESSING_EFFICIENCY, 0) or 0)))
        * (1.0 + SKILL_SPECIALIZATION * max(0, int(ore_skill_level or 0)))
        * (1.0 + max(0.0, implant_bonus))
        * (1.0 + max(0.0, float(security_mult)))
        * (1.0 + max(0.0, float(rig_mult)))
    )
    max_yield = REPROCESSING_MAX_YIELD_FACILITY if is_player_facility else REPROCESSING_MAX_YIELD_NPC
    return min(base * mult, max_yield)


# ════════════════════════════════════════════════════
#  共享费率计算 — 制造/贸易评分共用
# ════════════════════════════════════════════════════


def calc_broker_rate(skills: dict, market_data: dict) -> float:
    """计算 NPC 空间站经纪人费率 (%)。

    公式（EVE Uni `Tax`，2026-05）：``3% − 0.3%×BR − 0.03%×F − 0.02%×C``，下限 1%。
    声望缺失按 0 处理（= 无声望加成，最差档）；负声望会抬高费率，与游戏一致。
    玩家 Upwell 结构市场由结构主定价、技能无效，本函数不适用。
    """
    broker_rel = max(0, int(skills.get(BROKER_RELATIONS, 0) or 0))
    faction_standing = float(market_data.get("faction_standing", 0.0) or 0.0)
    corp_standing = float(market_data.get("corp_standing", 0.0) or 0.0)
    rate = (
        BROKER_FEE_BASE
        - BROKER_RELATION_MULT * broker_rel
        - STANDING_FACTION_WEIGHT * faction_standing
        - STANDING_CORP_WEIGHT * corp_standing
    )
    return max(BROKER_FEE_MIN, rate)


def calc_relist_discount(skills: dict) -> float:
    """计算改单折扣 (%)。基础 50%，高级经纪人关系学每级 +6 个百分点（V 级 = 80%）。"""
    adv_rel = max(0, int(skills.get(ADVANCED_BROKER_RELATIONS, 0) or 0))
    return min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)


def calc_sales_tax_rate(skills: dict) -> float:
    """计算销售税率 (%)。基础 7.5%，会计学每级 -11%（V 级 = 3.375%）。"""
    accounting = max(0, int(skills.get(ACCOUNTING, 0) or 0))
    return SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)


def calc_relist_fee(
    new_total: float,
    price_increase: float,
    broker_rate_pct: float,
    relist_discount_pct: float,
) -> float:
    """改单费（ISK）—— 官方两段式（EVE Uni `Skills:Trade`「Advanced Broker Relations」）：

    1. 涨价差额按**全额**经纪人费率计：``max(0, 涨价差额) × rate``（降价时该段为 0）；
    2. 新总价按**折扣后**费率计：``新总价 × rate × (1 − 改单折扣)``。

    两段相加即本次改单的经纪人费用（初始挂单费另计、不退）。
    """
    rate = float(broker_rate_pct) / 100.0
    delta = max(0.0, float(price_increase))
    discount = min(max(0.0, float(relist_discount_pct)), 100.0) / 100.0
    return delta * rate + max(0.0, float(new_total)) * rate * (1.0 - discount)

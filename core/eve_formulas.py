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
INSTALL_FEE_RATE = 0.05  # 安装费 = 5% × 成品收入
INDUSTRY_SKILL_MULT = 0.04  # 工业理论 (3380) 每级 -4% 时间
ADV_INDUSTRY_SKILL_MULT = 0.03  # 高级工业理论 (3388) 每级 -3% 时间
TE_MULT_PER_LEVEL = 0.01  # TE 每级 -1% 时间
ME_WASTE_BASE = 0.1  # ME 0 = 10% 浪费，每级 -1%

# ════════════════════════════════════════════════════
#  贸易 — 来源: https://wiki.eveuniversity.org/Trade
# ════════════════════════════════════════════════════
ACCOUNTING_MULT = 0.03  # 会计学每级 -3% 销售税
SALES_TAX_BASE = 2.0  # 基础销售税率
ADV_BROKER_DISCOUNT = 5  # 高级经纪人关系学每级 +5% 改单折扣
RELIST_BASE_DISCOUNT = 50  # 0 级时改单折扣 50%

# ════════════════════════════════════════════════════
#  基础矿物 type_id → 中文名映射（type_id < 178，不在 item 表中）
# ════════════════════════════════════════════════════
_MINERAL_NAMES = {
    34: "三钛合金",
    35: "类银超金属",
    36: "同位聚合体",
    37: "超新星诺克石",
    38: "晶状石英核岩",
    39: "碳纤维",
    40: "建筑用预制块",
}
_RACE_ME = {4247: "****残余物", 4312: "****残余物"}  # 补全用
_MINERAL_NAMES.update(_RACE_ME)


# ════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════


def resolve_item_name(c, type_id: int) -> str:
    """统一物品名称解析：item 表 → 矿物硬编码 → str(id)"""
    if type_id in _MINERAL_NAMES:
        return _MINERAL_NAMES[type_id]
    nrow = c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (type_id,)).fetchone()
    return (nrow[0] or nrow[1]) if nrow else str(type_id)


def _mat_name(mat_id: int, c) -> str:
    """查询材料名称，优先查 item 表，基础矿物用硬编码"""
    return resolve_item_name(c, mat_id)


def _hub_region_id(hub: str | None) -> int:
    """hub 名称 → region_id，None 或未知时默认 Jita"""
    if hub is None:
        return TRADE_HUB_IDS["Jita"]
    return TRADE_HUB_IDS.get(hub, TRADE_HUB_IDS["Jita"])

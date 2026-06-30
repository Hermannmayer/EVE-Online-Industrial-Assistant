"""
物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
"""

from core.eve_formulas import (
    ACCOUNTING_MULT,
    ADV_BROKER_DISCOUNT,
    BROKER_FEE_BASE,
    BROKER_FEE_MIN,
    BROKER_RELATION_MULT,
    RELIST_BASE_DISCOUNT,
    SALES_TAX_BASE,
    STANDING_CORP_WEIGHT,
    STANDING_FACTION_WEIGHT,
)
from services.database_manager import get_db
from services.scoring import get_price

db = get_db()

# ════════════════════════════════════════════════════
#  四大贸易中心之间的跳跃数（High-sec 安全路线）
# ════════════════════════════════════════════════════
TRADE_HUB_DISTANCES: dict[tuple[str, str], int] = {
    ("Jita", "Amarr"): 72,
    ("Jita", "Dodixie"): 12,
    ("Jita", "Rens"): 18,
    ("Amarr", "Dodixie"): 62,
    ("Amarr", "Rens"): 60,
    ("Dodixie", "Rens"): 30,
}
# 反向对称
for (a, b), d in list(TRADE_HUB_DISTANCES.items()):
    TRADE_HUB_DISTANCES[(b, a)] = d


def get_distance_jumps(source: str, destination: str) -> int | None:
    """获取两个贸易中心之间的跳跃数，未知路线返回 None"""
    return TRADE_HUB_DISTANCES.get((source, destination))


def estimate_freight_cost(
    volume_m3: float,
    distance_jumps: int,
    collateral: float,
    price_per_jump: float = 500_000,
    price_per_m3: float = 200,
    use_public_freight: bool = True,
) -> dict:
    """
    估算跨区域货物运输的运费。

    两种计价模式：
    1. 公开货运（use_public_freight=True）：按体积 + 抵押价值计价
       - 公开货运公司如 PushX、Red Frog、Haulers Channel
       - 一般按体积（isk/m³）和抵押（% of collateral）收费
    2. 自有运输（use_public_freight=False）：按跳跃数计价（燃料成本）
       - 使用自己的货船运输
       - 只需燃料成本（isk/跳）

    参数:
        volume_m3: 物品总体积 (m³)
        distance_jumps: 跳跃数
        collateral: 货物抵押价值 (ISK)
        price_per_jump: 每跳燃料成本 (ISK)，默认 500,000
        price_per_m3: 公开货运每 m³ 费率 (ISK)，默认 200
        use_public_freight: 是否使用公开货运

    返回:
        {
            "freight_cost": float,      # 估算运费
            "collateral_fee": float,    # 抵押附加费（公开货运）
            "fuel_cost": float,         # 燃料成本（自有运输）
            "total_cost": float,        # 总运输成本
            "mode": str,                # 运输模式
            "breakdown": {...},         # 明细
        }
    """
    if volume_m3 <= 0:
        volume_m3 = 1.0
    if distance_jumps <= 0:
        distance_jumps = 1

    breakdown = {}

    if use_public_freight:
        # 公开货运：体积费 + 抵押附加费
        volume_fee = volume_m3 * price_per_m3
        # 抵押附加费 = collateral × 0.02（2% 行业标准费率）
        collateral_pct = 0.02
        collateral_fee = collateral * collateral_pct
        freight_cost = volume_fee + collateral_fee
        fuel_cost = 0.0

        breakdown = {
            "volume_fee": round(volume_fee, 2),
            "collateral_pct": round(collateral_pct * 100, 1),
            "collateral_fee": round(collateral_fee, 2),
            "price_per_m3": price_per_m3,
        }
        mode = "public_freight"
    else:
        # 自有运输：仅燃料成本
        fuel_cost = price_per_jump * distance_jumps
        freight_cost = fuel_cost
        collateral_fee = 0.0

        breakdown = {
            "price_per_jump": price_per_jump,
            "fuel_cost": round(fuel_cost, 2),
        }
        mode = "self_transport"

    return {
        "freight_cost": round(freight_cost, 2),
        "collateral_fee": round(collateral_fee if use_public_freight else 0, 2),
        "fuel_cost": round(fuel_cost if not use_public_freight else 0, 2),
        "total_cost": round(freight_cost, 2),
        "mode": mode,
        "breakdown": breakdown,
    }


def calc_transport_profit(
    type_id: int,
    buy_hub: str,
    sell_hub: str,
    buy_price_type: str,
    sell_price_type: str,
    quantity: int,
    distance_jumps: int,
    char_config: dict | None = None,
    use_public_freight: bool = True,
) -> dict:
    """
    计算跨区域运输的净利润（包含运费和贸易费用）。

    参数:
        type_id: 物品 type_id
        buy_hub: 购买区域
        sell_hub: 出售区域
        buy_price_type: 买入价类型 'buy'/'sell'
        sell_price_type: 卖出价类型 'buy'/'sell'
        quantity: 数量
        distance_jumps: 跳跃数
        char_config: 角色配置（技能等级等）
        use_public_freight: 是否使用公开货运

    返回:
        {
            "buy_cost": float,
            "sell_revenue": float,
            "freight_cost": float,
            "broker_cost": float,
            "sales_tax": float,
            "net_profit": float,
            "margin_pct": float,
            "isk_per_m3": float,
            "total_volume_m3": float,
            "status": str,
        }
    """
    result = {
        "buy_cost": 0.0,
        "sell_revenue": 0.0,
        "freight_cost": 0.0,
        "broker_cost": 0.0,
        "sales_tax": 0.0,
        "net_profit": 0.0,
        "margin_pct": 0.0,
        "isk_per_m3": 0.0,
        "total_volume_m3": 0.0,
        "status": "",
    }

    # 1. 获取买卖价格
    buy_price = get_price(type_id, buy_price_type, buy_hub)
    sell_price = get_price(type_id, sell_price_type, sell_hub)

    if not buy_price or not sell_price:
        result["status"] = "no_price"
        return result

    # 2. 获取物品体积
    with db.connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        volume_m3 = row[0] or 1.0 if row else 1.0

    total_volume_m3 = volume_m3 * quantity

    # 3. 获取角色技能配置
    skills = char_config.get("skills", {}) if char_config else {}
    market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
    market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    # 4. 计算买入经纪人费
    broker_lvl = skills.get("经纪人关系学", 0)
    adv_rel = skills.get("高级经纪人关系学", 0)
    accounting = skills.get("会计学", 0)

    # 买入声望因子
    fs_buy = market_data_buy.get("faction_standing", 5.0)
    cs_buy = market_data_buy.get("corp_standing", 5.0)
    sf_buy = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_buy) + STANDING_CORP_WEIGHT * max(0, cs_buy))
    broker_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_buy if sf_buy > 0 else BROKER_FEE_BASE
    broker_rate = max(BROKER_FEE_MIN, broker_rate)

    # 改单折扣
    relist_discount = min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

    # 买入费用 = 1次挂单 + 1次改单
    buy_broker_pct = broker_rate + broker_rate * (1 - relist_discount / 100)

    # 5. 计算卖出费率（声望可能不同）
    fs_sell = market_data_sell.get("faction_standing", 5.0)
    cs_sell = market_data_sell.get("corp_standing", 5.0)
    sf_sell = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_sell) + STANDING_CORP_WEIGHT * max(0, cs_sell))
    sell_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_sell if sf_sell > 0 else BROKER_FEE_BASE
    sell_rate = max(BROKER_FEE_MIN, sell_rate)

    # 卖出费用 = 1次挂单 + 1次改单 + 销售税
    sell_broker_pct = sell_rate + sell_rate * (1 - relist_discount / 100)
    sales_tax_rate = SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

    # 6. 基础成本/收入
    raw_buy_cost = buy_price * quantity
    raw_sell_revenue = sell_price * quantity

    buy_broker_cost = raw_buy_cost * (buy_broker_pct / 100)
    sell_broker_cost = raw_sell_revenue * (sell_broker_pct / 100)
    sales_tax = raw_sell_revenue * (sales_tax_rate / 100)

    total_buy_cost = raw_buy_cost + buy_broker_cost
    total_sell_revenue = raw_sell_revenue - sell_broker_cost - sales_tax
    total_broker_cost = buy_broker_cost + sell_broker_cost

    # 7. 计算运费
    collateral = raw_buy_cost  # 抵押价值 = 买入总成本
    freight_result = estimate_freight_cost(
        volume_m3=total_volume_m3,
        distance_jumps=distance_jumps,
        collateral=collateral,
        use_public_freight=use_public_freight,
    )
    freight_cost = freight_result["total_cost"]

    # 8. 计算净利润
    net_profit = total_sell_revenue - total_buy_cost - freight_cost
    buy_total_including_freight = total_buy_cost + freight_cost
    margin_pct = net_profit / buy_total_including_freight * 100 if buy_total_including_freight > 0 else 0

    isk_per_m3 = net_profit / total_volume_m3 if total_volume_m3 > 0 else net_profit

    return {
        "buy_cost": round(total_buy_cost, 2),
        "sell_revenue": round(total_sell_revenue, 2),
        "freight_cost": round(freight_cost, 2),
        "broker_cost": round(total_broker_cost, 2),
        "sales_tax": round(sales_tax, 2),
        "net_profit": round(net_profit, 2),
        "margin_pct": round(margin_pct, 2),
        "isk_per_m3": round(isk_per_m3, 2),
        "total_volume_m3": round(total_volume_m3, 2),
        "freight_breakdown": freight_result["breakdown"],
        "freight_mode": freight_result["mode"],
        "status": "",
    }


def list_trade_hub_distances() -> list[dict]:
    """返回所有贸易中心对的跳跃距离，供 UI 使用"""
    seen = set()
    result = []
    for (a, b), d in TRADE_HUB_DISTANCES.items():
        key = tuple(sorted([a, b]))
        if key in seen:
            continue
        seen.add(key)
        result.append({"from": a, "to": b, "jumps": d})
    return result

"""
制造评分 / 贸易评分 计算逻辑
"""
import sqlite3
import math
from core.paths import DB_PATH

# 四大贸易中心的 market_prices 基准
# buy_price = 最高买单, sell_price = 最低卖单
TRADE_HUB_IDS = {
    "Jita": 10000002,
    "Amarr": 10000043,
    "Dodixie": 10000032,
    "Rens": 10000030,
}


def get_price(type_id: int, price_type: str) -> float | None:
    """
    从 market_prices 获取价格。
    price_type: 'buy' → buy_price, 'sell' → sell_price
    """
    # 注意：market_prices 中的 buy_price 是最高买单，sell_price 是最低卖单
    col = "buy_price" if price_type == "buy" else "sell_price"
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(f"SELECT {col} FROM market_prices WHERE type_id = ? ORDER BY id DESC LIMIT 1", (type_id,))
        row = c.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_volume(type_id: int, vol_type: str = "total") -> int:
    """获取成交量。vol_type: 'buy' / 'sell' / 'total'"""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("""
            SELECT buy_volume, sell_volume FROM market_prices
            WHERE type_id = ? ORDER BY id DESC LIMIT 1
        """, (type_id,))
        row = c.fetchone()
        if not row:
            return 0
        if vol_type == "buy":
            return row[0] or 0
        elif vol_type == "sell":
            return row[1] or 0
        return (row[0] or 0) + (row[1] or 0)
    finally:
        conn.close()


def calc_manufacturing_score(
    type_id: int,
    char_config: dict,
    mat_source_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility_tax_pct: float = 0.0,
    price_type_mat: str = "sell",   # 材料用卖单价（你买入的价格）
    price_type_prod: str = "sell",  # 成品用卖单价（你卖出的价格）
) -> dict:
    """
    计算制造评分。

    返回:
    {
        "score": 0-100,
        "profit_per_run": float,
        "margin_pct": float,
        "cost_per_unit": float,
        "revenue_per_unit": float,
        "hours_per_run": float,
        "status": str,        # 空=可制造, "no_blueprint"=无蓝图, "no_price"=无价格
        "breakdown": { ... }
    }
    """
    result = {
        "score": 0.0,
        "profit_per_run": 0.0,
        "margin_pct": 0.0,
        "cost_per_unit": 0.0,
        "revenue_per_unit": 0.0,
        "hours_per_run": 0.0,
        "status": "",
        "breakdown": {},
    }

    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()

        # 1. 查找有哪些蓝图产出此物品
        c.execute("""
            SELECT bp.blueprint_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
            LIMIT 1
        """, (type_id,))
        bp_row = c.fetchone()
        if not bp_row:
            result["status"] = "no_blueprint"
            return result

        bp_id, prod_qty, base_time = bp_row
        prod_qty = prod_qty or 1

        # 2. 成品价格
        prod_price = get_price(type_id, price_type_prod)
        if not prod_price:
            result["status"] = "no_price"
            return result

        # 3. 查材料
        c.execute("""
            SELECT bm.material_type_id, bm.quantity
            FROM blueprint_materials bm
            WHERE bm.blueprint_type_id = ? AND bm.activity = 'manufacturing'
        """, (bp_id,))
        materials = c.fetchall()

        if not materials:
            result["status"] = "no_materials"
            return result

        # 4. 计算材料成本
        total_mat_cost = 0.0
        for mat_id, mat_qty in materials:
            mat_price = get_price(mat_id, price_type_mat)
            if mat_price:
                total_mat_cost += mat_qty * mat_price

        # 5. 从人物配置读取费率
        skills = char_config.get("skills", {}) if char_config else {}
        market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}
        faction_standing = market_data.get("faction_standing", 5.0)
        corp_standing = market_data.get("corp_standing", 5.0)

        # 计算经纪人费率
        broker_rel = skills.get("经纪人关系学", 0)
        standing_factor = 2 ** (0.14 * max(0, faction_standing) + 0.06 * max(0, corp_standing))
        broker_rate = (1.0 - 0.05 * broker_rel) / standing_factor if standing_factor > 0 else 1.0
        broker_rate = max(0.1, broker_rate)  # %

        # 销售税率
        accounting = skills.get("会计学", 0)
        sales_tax_rate = 2.0 * (1 - 0.03 * accounting)  # %

        # 6. 计算单次利润
        revenue = prod_price * prod_qty
        total_cost = total_mat_cost
        facility_fee = total_cost * (facility_tax_pct / 100)
        total_cost += facility_fee
        bf = revenue * (broker_rate / 100)
        st = revenue * (sales_tax_rate / 100)
        total_cost += bf + st

        profit = revenue - total_cost
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        if profit <= 0:
            result["margin_pct"] = round(margin_pct, 2)
            result["profit_per_run"] = round(profit, 2)
            result["cost_per_unit"] = round(total_cost / prod_qty, 2)
            result["hours_per_run"] = round(base_time / 3600, 2)
            result["revenue_per_unit"] = round(prod_price, 2)
            return result  # score 保持 0

        # 7. 制造时间
        # 技能倍率：Industry(3380) -4%/级, Advanced Industry(3388) -3%/级
        ind_lvl = skills.get("工业理论", 5)  # 对应 type_id 3380
        adv_lvl = skills.get("高级工业理论", 5)  # 对应 type_id 3388
        skill_mod = (1 - 0.04 * ind_lvl) * (1 - 0.03 * adv_lvl)
        actual_time = base_time * skill_mod
        hours_per_run = actual_time / 3600

        # 8. 计算评分
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        # 成交量
        volume = get_volume(type_id, "total")

        # 前置检查
        if volume == 0:
            return result

        profit_score = min(margin_pct * 4, 40)  # 10% = 40分

        volume_factor = min(volume / 5_000_000, 1.0)
        volume_score = volume_factor * 30  # 500万 = 30分

        isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
        efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)  # 5000万/h = 30分

        total_score = profit_score + volume_score + efficiency_score

        result.update({
            "score": round(total_score, 1),
            "profit_per_run": round(profit, 2),
            "margin_pct": round(margin_pct, 2),
            "cost_per_unit": round(total_cost / prod_qty, 2),
            "revenue_per_unit": round(prod_price, 2),
            "hours_per_run": round(hours_per_run, 2),
            "status": "",
            "breakdown": {
                "profit_score": round(profit_score, 1),
                "volume_score": round(volume_score, 1),
                "efficiency_score": round(efficiency_score, 1),
                "isk_per_hour": round(isk_per_hour, 2),
                "broker_rate": round(broker_rate, 3),
                "sales_tax_rate": round(sales_tax_rate, 3),
                "facility_fee": round(facility_fee, 2),
            },
        })

    finally:
        conn.close()

    return result


def calc_trade_score(
    type_id: int,
    buy_hub: str = "Jita",
    sell_hub: str = "Jita",
    buy_price_type: str = "buy",   # 买入价来源
    sell_price_type: str = "sell", # 卖出价来源
    char_config: dict = None,
    quantity: int = 1,
) -> dict:
    """
    计算贸易评分。

    返回:
    {
        "score": 0-100,
        "buy_cost": float,
        "sell_revenue": float,
        "gross_profit": float,
        "margin_pct": float,
        "profit_per_m3": float,
        "status": str,
    }
    """
    result = {
        "score": 0.0,
        "buy_cost": 0.0,
        "sell_revenue": 0.0,
        "gross_profit": 0.0,
        "margin_pct": 0.0,
        "profit_per_m3": 0.0,
        "status": "",
    }

    buy_price = get_price(type_id, buy_price_type)
    sell_price = get_price(type_id, sell_price_type)

    if not buy_price or not sell_price:
        result["status"] = "no_price"
        return result

    # 获取体积
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        volume_m3 = row[0] or 1.0 if row else 1.0
    finally:
        conn.close()

    skills = char_config.get("skills", {}) if char_config else {}
    market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
    market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    # 买入方费用
    fs_buy = market_data_buy.get("faction_standing", 5.0)
    cs_buy = market_data_buy.get("corp_standing", 5.0)
    broker_buy = skills.get("经纪人关系学", 0)
    sf_buy = 2 ** (0.14 * max(0, fs_buy) + 0.06 * max(0, cs_buy))
    buy_fee_rate = (1.0 - 0.05 * broker_buy) / sf_buy if sf_buy > 0 else 1.0
    buy_fee_rate = max(0.1, buy_fee_rate)

    # 卖出方费用
    fs_sell = market_data_sell.get("faction_standing", 5.0)
    cs_sell = market_data_sell.get("corp_standing", 5.0)
    sf_sell = 2 ** (0.14 * max(0, fs_sell) + 0.06 * max(0, cs_sell))
    sell_fee_rate = (1.0 - 0.05 * broker_buy) / sf_sell if sf_sell > 0 else 1.0
    sell_fee_rate = max(0.1, sell_fee_rate)

    accounting = skills.get("会计学", 0)
    sales_tax_rate = 2.0 * (1 - 0.03 * accounting)

    buy_cost = buy_price * quantity + buy_price * quantity * (buy_fee_rate / 100)
    sell_revenue = sell_price * quantity - sell_price * quantity * ((sell_fee_rate + sales_tax_rate) / 100)
    gross_profit = sell_revenue - buy_cost
    margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0

    if gross_profit <= 0:
        result["margin_pct"] = round(margin_pct, 2)
        result["buy_cost"] = round(buy_cost, 2)
        result["sell_revenue"] = round(sell_revenue, 2)
        result["gross_profit"] = round(gross_profit, 2)
        return result
        return result

    volume = get_volume(type_id, "total")
    if volume == 0:
        return result

    margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0
    profit_per_m3 = gross_profit / volume_m3 if volume_m3 > 0 else gross_profit

    margin_score = min(margin_pct * 5, 50)  # 10% = 50分
    volume_factor = min(volume / 5_000_000, 1.0)
    vol_score = volume_factor * 50  # 500万 = 50分
    total_score = margin_score + vol_score

    result.update({
        "score": round(total_score, 1),
        "buy_cost": round(buy_cost, 2),
        "sell_revenue": round(sell_revenue, 2),
        "gross_profit": round(gross_profit, 2),
        "margin_pct": round(margin_pct, 2),
        "profit_per_m3": round(profit_per_m3, 2),
    })

    return result

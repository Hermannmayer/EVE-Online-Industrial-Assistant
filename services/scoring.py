"""
制造评分 / 贸易评分 计算逻辑
"""

import threading
import time
from collections import OrderedDict

from core.eve_formulas import (
    ACCOUNTING_MULT,
    ADV_BROKER_DISCOUNT,
    ADV_INDUSTRY_SKILL_MULT,
    BROKER_FEE_BASE,
    BROKER_FEE_MIN,
    BROKER_RELATION_MULT,
    INDUSTRY_SKILL_MULT,
    INSTALL_FEE_RATE,
    ME_WASTE_BASE,
    RELIST_BASE_DISCOUNT,
    SALES_TAX_BASE,
    STANDING_CORP_WEIGHT,
    STANDING_FACTION_WEIGHT,
    TE_MULT_PER_LEVEL,
    _hub_region_id,
    _mat_name,
)
from services.database_manager import get_db

db = get_db()


# ════════════════════════════════════════════════════
#  评分结果缓存 — 30 分钟 TTL，有界 LRU 淘汰（线程安全）
#  原 services/scoring_cache.py
# ════════════════════════════════════════════════════


class ScoringCache:
    """线程安全的有界评分缓存，过期被动清理 + LRU 淘汰"""

    def __init__(self, max_size: int = 500, ttl: int = 1800):
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._evict_expired_locked()
            entry = self._cache.get(key)
            if entry is None:
                return None
            timestamp, result = entry
            if time.time() - timestamp >= self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return result

    def set(self, key: str, result: dict):
        with self._lock:
            self._evict_expired_locked()
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), result)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def _evict_expired_locked(self):
        cutoff = time.time() - self._ttl
        expired = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in expired:
            del self._cache[k]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


# 兼容层：模块级函数委托给默认实例
_default = ScoringCache()


def get_cache(key: str) -> dict | None:
    return _default.get(key)


def set_cache(key: str, result: dict):
    _default.set(key, result)


def invalidate_cache():
    _default.invalidate()


def get_price(type_id: int, price_type: str, hub: str | None = None) -> float | None:
    """
    从 market_prices 获取指定区域的价格。
    price_type: 'buy' → buy_price, 'sell' → sell_price
    hub: 贸易中心名称, 如 'Jita', 'Amarr'；None 时返回任意区域
    """
    _VALID_PRICE_COLS = {"buy": "buy_price", "sell": "sell_price"}
    col = _VALID_PRICE_COLS.get(price_type)
    if col is None:
        return None
    with db.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and row[0] is not None:
                return row[0]
            # 降级：该区域无数据，尝试其他区域
            c.execute(f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1", (type_id,))
        else:
            c.execute(f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1", (type_id,))
        row = c.fetchone()
        return row[0] if row else None


def get_volume(type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
    """获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'"""
    with db.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and (row[0] or row[1]):
                return row[0] + row[1] if vol_type == "total" else (row[0] if vol_type == "buy" else row[1])
            # 降级：该区域无数据，尝试其他区域
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        else:
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        row = c.fetchone()
        if not row:
            return 0
        if vol_type == "buy":
            return row[0] or 0
        elif vol_type == "sell":
            return row[1] or 0
        return (row[0] or 0) + (row[1] or 0)


def get_system_cost_index(system_id: int | None, activity: str = "manufacturing") -> float:
    """从数据库获取星系的制造成本指数(SCI)。默认1.0（无加成）。"""
    if system_id is None:
        return 1.0
    with db.connect("ref") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
            (system_id, activity),
        )
        row = c.fetchone()
        return row[0] if row else 1.0


def calc_manufacturing_score(
    type_id: int,
    char_config: dict,
    mat_source_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility_tax_pct: float = 0.0,
    price_type_mat: str = "sell",  # 材料用卖单价（你买入的价格）
    price_type_prod: str = "sell",  # 成品用卖单价（你卖出的价格）
    bp_me: int = 0,  # 蓝图材料效率 0-10，每级减1%浪费
    bp_te: int = 0,  # 蓝图时间效率 0-20，每级减1%时间
    system_id: int | None = None,  # 制造星系ID，用于查询SCI
    structure_bonus: float = 0.0,  # 建筑改装件减免 (0.0-0.05)，含ME/TE/cost rig
) -> dict:
    """
    计算制造评分。

    参数:
        type_id: 成品 type_id
        char_config: 角色配置 {"skills": {"工业理论": 5, "高级工业理论": 5, ...}}
        mat_source_hub: 材料购买区域
        sell_hub: 成品出售区域
        facility_tax_pct: 设施税百分比
        price_type_mat: 材料价格类型 'buy'/'sell'
        price_type_prod: 成品价格类型 'buy'/'sell'
        bp_me: 蓝图材料效率 (0-10)，ME 0=1.1x材料, ME 10=1.0x
        bp_te: 蓝图时间效率 (0-20)，TE 0=1.0x时间, TE 20=0.8x
        system_id: 制造星系ID，None=不计安装费，否则查 industry_system_costs
        structure_bonus: 建筑改装件总减免 (0.0-0.05)，乘入安装费折扣

    返回:
    {
        "score": 0-100,
        "profit_per_run": float,
        "margin_pct": float,
        "isk_per_hour": float,
        "breakdown": {...},
        "materials": [...],
        ...
    }

    费用逻辑:
      - 安装费 = 0.05 × 成品收入 × SCI × (1 - 建筑减免) × (1 + 设施税%)
      - 制造卖出时: 1次挂单经纪人费 + 1次改单经纪人费 + 销售税
      - 买材料不产生经纪人费（直接吃现价卖单）
      - ME 浪费: waste_factor = 1 + 0.1 * (1 - ME/10)
      - TE 时间: te_modifier = 1 - TE * 0.01
      - system_id=None 时 SCI=1.0（不计安装费）
    """
    result = {
        "score": 0.0,
        "profit_per_run": 0.0,
        "margin_pct": 0.0,
        "isk_per_hour": 0.0,
        "cost_per_unit": 0.0,
        "revenue_per_unit": 0.0,
        "hours_per_run": 0.0,
        "status": "",
        "breakdown": {},
    }

    with db.connect("ref", "mkt", "bp") as conn:
        c = conn.cursor()

        # 1. 查找有哪些蓝图产出此物品
        c.execute(
            """
            SELECT bp.blueprint_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
            LIMIT 1
        """,
            (type_id,),
        )
        bp_row = c.fetchone()
        if not bp_row:
            result["status"] = "no_blueprint"
            return result

        bp_id, prod_qty, base_time = bp_row
        prod_qty = prod_qty or 1

        # 2. 成品价格（使用 sell_hub 区域）
        prod_price = get_price(type_id, price_type_prod, sell_hub)
        if not prod_price:
            result["status"] = "no_price"
            return result

        # 3. 查材料
        c.execute(
            """
            SELECT bm.material_type_id, bm.quantity
            FROM blueprint_materials bm
            WHERE bm.blueprint_type_id = ? AND bm.activity = 'manufacturing'
        """,
            (bp_id,),
        )
        mat_rows = c.fetchall()

        if not mat_rows:
            result["status"] = "no_materials"
            return result

        # 4. 计算材料成本（含 ME 浪费因子）
        # ME 0 → waste_factor 1.1 (10%浪费), ME 10 → 1.0 (无浪费)
        waste_factor = 1 + ME_WASTE_BASE * (1 - bp_me / 10)
        total_mat_cost = 0.0
        mat_detail = []
        for mat_id, mat_qty in mat_rows:
            mat_price = get_price(mat_id, price_type_mat, mat_source_hub)
            waste_qty = mat_qty * waste_factor
            if mat_price:
                total_mat_cost += waste_qty * mat_price
            mat_name = _mat_name(mat_id, c)
            mat_detail.append(
                {
                    "name": mat_name,
                    "base_qty": mat_qty,
                    "qty": round(waste_qty, 2),
                    "waste_factor": round(waste_factor, 2),
                    "unit_price": mat_price or 0.0,
                    "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                }
            )
        result["materials"] = mat_detail

        # 5. 从人物配置读取费率
        skills = char_config.get("skills", {}) if char_config else {}
        market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}
        faction_standing = market_data.get("faction_standing", 5.0)
        corp_standing = market_data.get("corp_standing", 5.0)

        # 经纪人费率
        broker_rel = skills.get("经纪人关系学", 0)
        standing_factor = 2 ** (
            STANDING_FACTION_WEIGHT * max(0, faction_standing) + STANDING_CORP_WEIGHT * max(0, corp_standing)
        )
        broker_rate = (
            (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_rel) / standing_factor
            if standing_factor > 0
            else BROKER_FEE_BASE
        )
        broker_rate = max(BROKER_FEE_MIN, broker_rate)

        # 改单折扣：高级经纪人关系学 每级+5%, 0级=50%
        adv_rel = skills.get("高级经纪人关系学", 0)
        relist_discount = min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

        # 销售税率
        accounting = skills.get("会计学", 0)
        sales_tax_rate = SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

        # 6. 安装费：0.05 × 成品收入 × SCI × (1 - 建筑减免) × (1 + 设施税%)
        revenue = prod_price * prod_qty
        total_cost = total_mat_cost
        sci = get_system_cost_index(system_id, "manufacturing")
        install_base = INSTALL_FEE_RATE * revenue
        facility_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
        total_cost += facility_fee
        broker_init = revenue * (broker_rate / 100)
        broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
        sales_tax = revenue * (sales_tax_rate / 100)
        total_cost += broker_init + broker_relist + sales_tax

        profit = revenue - total_cost
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        if profit <= 0:
            ind_lvl = skills.get("工业理论", 5)
            adv_lvl = skills.get("高级工业理论", 5)
            skill_mod = (1 - INDUSTRY_SKILL_MULT * ind_lvl) * (1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl)
            te_modifier = 1 - bp_te * TE_MULT_PER_LEVEL
            result["margin_pct"] = round(margin_pct, 2)
            result["profit_per_run"] = round(profit, 2)
            result["cost_per_unit"] = round(total_cost / prod_qty, 2)
            result["hours_per_run"] = round(base_time * skill_mod * te_modifier / 3600, 2)
            result["revenue_per_unit"] = round(prod_price, 2)
            return result  # score 保持 0

        # 7. 制造时间
        # 技能倍率：Industry(3380) -4%/级, Advanced Industry(3388) -3%/级
        ind_lvl = skills.get("工业理论", 5)  # 对应 type_id 3380
        adv_lvl = skills.get("高级工业理论", 5)  # 对应 type_id 3388
        skill_mod = (1 - INDUSTRY_SKILL_MULT * ind_lvl) * (1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl)
        # 蓝图 TE 修正：TE 0 → 1.0x, TE 20 → 0.8x
        te_modifier = 1 - bp_te * TE_MULT_PER_LEVEL
        actual_time = base_time * skill_mod * te_modifier
        hours_per_run = actual_time / 3600

        # 8. 计算评分
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        # 成交量
        volume = get_volume(type_id, "total", sell_hub)

        # 前置检查
        if volume == 0:
            return result

        profit_score = min(margin_pct * 4, 40)  # 10% = 40分

        volume_factor = min(volume / 5_000_000, 1.0)
        volume_score = volume_factor * 30  # 500万 = 30分

        isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
        efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)  # 5000万/h = 30分

        total_score = profit_score + volume_score + efficiency_score

        result.update(
            {
                "score": round(total_score, 1),
                "profit_per_run": round(profit, 2),
                "margin_pct": round(margin_pct, 2),
                "isk_per_hour": round(isk_per_hour, 2),
                "cost_per_unit": round(total_cost / prod_qty, 2),
                "revenue_per_unit": round(prod_price, 2),
                "hours_per_run": round(hours_per_run, 2),
                "status": "",
                "breakdown": {
                    "bp_me": bp_me,
                    "bp_te": bp_te,
                    "waste_factor": round(waste_factor, 2),
                    "te_modifier": round(te_modifier, 2),
                    "profit_score": round(profit_score, 1),
                    "volume_score": round(volume_score, 1),
                    "efficiency_score": round(efficiency_score, 1),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "revenue": round(revenue, 2),
                    "material_cost": round(total_mat_cost, 2),
                    "broker_init": round(broker_init, 2),
                    "broker_relist": round(broker_relist, 2),
                    "sales_tax": round(sales_tax, 2),
                    "facility_fee": round(facility_fee, 2),
                    "install_base": round(install_base, 2),
                    "sci": round(sci, 4),
                    "structure_bonus": round(structure_bonus, 4),
                    "facility_tax_pct": round(facility_tax_pct, 2),
                    "broker_rate": round(broker_rate, 3),
                    "sales_tax_rate": round(sales_tax_rate, 3),
                    "relist_discount": round(relist_discount, 1),
                },
            }
        )

    return result


def calc_trade_score(
    type_id: int,
    buy_hub: str = "Jita",
    sell_hub: str = "Jita",
    buy_price_type: str = "buy",  # 买入价来源
    sell_price_type: str = "sell",  # 卖出价来源
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

    buy_price = get_price(type_id, buy_price_type, buy_hub)
    sell_price = get_price(type_id, sell_price_type, sell_hub)

    if not buy_price or not sell_price:
        result["status"] = "no_price"
        return result

    # 获取体积
    with db.connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        volume_m3 = row[0] or 1.0 if row else 1.0

    skills = char_config.get("skills", {}) if char_config else {}
    market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
    market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    # 经纪人费率（买入/卖出）
    broker_lvl = skills.get("经纪人关系学", 0)

    fs_buy = market_data_buy.get("faction_standing", 5.0)
    cs_buy = market_data_buy.get("corp_standing", 5.0)
    sf_buy = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_buy) + STANDING_CORP_WEIGHT * max(0, cs_buy))
    broker_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_buy if sf_buy > 0 else BROKER_FEE_BASE
    broker_rate = max(BROKER_FEE_MIN, broker_rate)

    # 改单折扣：高级经纪人关系学 每级+5%, 0级=50%
    adv_rel = skills.get("高级经纪人关系学", 0)
    relist_discount = min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

    # 买入费用 = 1次挂单 + 1次改单
    buy_init = broker_rate
    buy_relist = broker_rate * (1 - relist_discount / 100)
    buy_fee_total = buy_init + buy_relist

    # 卖出费率（声望可能不同）
    fs_sell = market_data_sell.get("faction_standing", 5.0)
    cs_sell = market_data_sell.get("corp_standing", 5.0)
    sf_sell = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_sell) + STANDING_CORP_WEIGHT * max(0, cs_sell))
    sell_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_sell if sf_sell > 0 else BROKER_FEE_BASE
    sell_rate = max(BROKER_FEE_MIN, sell_rate)

    # 卖出费用 = 1次挂单 + 1次改单 + 销售税
    sell_init = sell_rate
    sell_relist = sell_rate * (1 - relist_discount / 100)
    accounting = skills.get("会计学", 0)
    sales_tax_rate = SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)
    sell_fee_total = sell_init + sell_relist + sales_tax_rate

    buy_cost = buy_price * quantity + buy_price * quantity * (buy_fee_total / 100)
    sell_revenue = sell_price * quantity - sell_price * quantity * (sell_fee_total / 100)
    gross_profit = sell_revenue - buy_cost
    margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0

    if gross_profit <= 0:
        result["margin_pct"] = round(margin_pct, 2)
        result["buy_cost"] = round(buy_cost, 2)
        result["sell_revenue"] = round(sell_revenue, 2)
        result["gross_profit"] = round(gross_profit, 2)
        return result

    volume = get_volume(type_id, "total", sell_hub)
    if volume == 0:
        return result

    margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0
    profit_per_m3 = gross_profit / volume_m3 if volume_m3 > 0 else gross_profit

    margin_score = min(margin_pct * 5, 50)  # 10% = 50分
    volume_factor = min(volume / 5_000_000, 1.0)
    vol_score = volume_factor * 50  # 500万 = 50分
    total_score = margin_score + vol_score

    result.update(
        {
            "score": round(total_score, 1),
            "buy_cost": round(buy_cost, 2),
            "sell_revenue": round(sell_revenue, 2),
            "gross_profit": round(gross_profit, 2),
            "margin_pct": round(margin_pct, 2),
            "profit_per_m3": round(profit_per_m3, 2),
        }
    )

    return result


# ════════════════════════════════════════════════════
#  反应（Reaction）利润评分
# ════════════════════════════════════════════════════

REACTION_INSTALL_FEE_RATE = 0.05  # 反应安装费 = 5% × 成品收入


def calc_reaction_score(
    type_id: int,
    char_config: dict,
    mat_source_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility_tax_pct: float = 0.0,
    price_type_mat: str = "sell",
    price_type_prod: str = "sell",
    system_id: int | None = None,
    structure_bonus: float = 0.0,
) -> dict:
    """
    计算反应（Reaction）利润评分。

    参数:
        type_id: 反应产物的 type_id
        char_config: 角色配置 {"skills": {"高级工业理论": 5, ...}, ...}
        mat_source_hub: 材料购买区域
        sell_hub: 成品出售区域
        facility_tax_pct: 设施税百分比
        price_type_mat: 材料价格类型 'buy'/'sell'
        price_type_prod: 成品价格类型 'buy'/'sell'
        system_id: 反应星系 ID，None=不计安装费
        structure_bonus: 建筑改装件减免 (0.0-0.05)

    返回:
    {
        "score": 0-100,
        "profit_per_run": float,
        "margin_pct": float,
        "isk_per_hour": float,
        "cost_per_unit": float,
        "revenue_per_unit": float,
        "hours_per_run": float,
        "status": "",
        "materials": [...],
        "breakdown": {...},
    }

    与 calc_manufacturing_score 的差异:
      - 查 activity='reaction' 的蓝图数据
      - 无 ME/TE 概念：waste_factor=1.0, 无 TE 修正
      - 时间仅受 Advanced Industry 技能影响（-3%/级）
      - 安装费使用反应专用 SCI
    """
    result = {
        "score": 0.0,
        "profit_per_run": 0.0,
        "margin_pct": 0.0,
        "isk_per_hour": 0.0,
        "cost_per_unit": 0.0,
        "revenue_per_unit": 0.0,
        "hours_per_run": 0.0,
        "status": "",
        "breakdown": {},
    }

    with db.connect("ref", "mkt", "bp") as conn:
        c = conn.cursor()

        # 1. 查找反应蓝图
        c.execute(
            """
            SELECT bp.blueprint_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.product_type_id = ? AND bp.activity = 'reaction'
            LIMIT 1
            """,
            (type_id,),
        )
        bp_row = c.fetchone()
        if not bp_row:
            result["status"] = "no_blueprint"
            return result

        bp_id, prod_qty, base_time = bp_row
        prod_qty = prod_qty or 1

        # 2. 成品价格
        prod_price = get_price(type_id, price_type_prod, sell_hub)
        if not prod_price:
            result["status"] = "no_price"
            return result

        # 3. 查反应材料
        c.execute(
            """
            SELECT bm.material_type_id, bm.quantity
            FROM blueprint_materials bm
            WHERE bm.blueprint_type_id = ? AND bm.activity = 'reaction'
            """,
            (bp_id,),
        )
        mat_rows = c.fetchall()

        if not mat_rows:
            result["status"] = "no_materials"
            return result

        # 4. 计算材料成本（反应无 ME 浪费，waste_factor=1.0）
        waste_factor = 1.0
        total_mat_cost = 0.0
        mat_detail = []
        for mat_id, mat_qty in mat_rows:
            mat_price = get_price(mat_id, price_type_mat, mat_source_hub)
            waste_qty = mat_qty * waste_factor
            if mat_price:
                total_mat_cost += waste_qty * mat_price
            mat_name = _mat_name(mat_id, c)
            mat_detail.append(
                {
                    "name": mat_name,
                    "base_qty": mat_qty,
                    "qty": round(waste_qty, 2),
                    "waste_factor": round(waste_factor, 2),
                    "unit_price": mat_price or 0.0,
                    "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                }
            )
        result["materials"] = mat_detail

        # 5. 从人物配置读取费率
        skills = char_config.get("skills", {}) if char_config else {}
        market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}
        faction_standing = market_data.get("faction_standing", 5.0)
        corp_standing = market_data.get("corp_standing", 5.0)

        # 经纪人费率
        broker_rel = skills.get("经纪人关系学", 0)
        standing_factor = 2 ** (
            STANDING_FACTION_WEIGHT * max(0, faction_standing) + STANDING_CORP_WEIGHT * max(0, corp_standing)
        )
        broker_rate = (
            (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_rel) / standing_factor
            if standing_factor > 0
            else BROKER_FEE_BASE
        )
        broker_rate = max(BROKER_FEE_MIN, broker_rate)

        # 改单折扣
        adv_rel = skills.get("高级经纪人关系学", 0)
        relist_discount = min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

        # 销售税率
        accounting = skills.get("会计学", 0)
        sales_tax_rate = SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

        # 6. 安装费：0.05 × 成品收入 × SCI × (1 - 建筑减免) × (1 + 设施税%)
        revenue = prod_price * prod_qty
        total_cost = total_mat_cost
        sci = get_system_cost_index(system_id, "reaction")
        install_base = REACTION_INSTALL_FEE_RATE * revenue
        facility_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
        total_cost += facility_fee
        broker_init = revenue * (broker_rate / 100)
        broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
        sales_tax = revenue * (sales_tax_rate / 100)
        total_cost += broker_init + broker_relist + sales_tax

        profit = revenue - total_cost
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        # 7. 反应时间：仅受 Advanced Industry 技能影响（-3%/级），无 TE 修正
        adv_lvl = skills.get("高级工业理论", 5)
        skill_mod = 1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl
        actual_time = base_time * skill_mod
        hours_per_run = actual_time / 3600

        # 8. 负利润时提前返回
        if profit <= 0:
            result["margin_pct"] = round(margin_pct, 2)
            result["profit_per_run"] = round(profit, 2)
            result["cost_per_unit"] = round(total_cost / prod_qty, 2)
            result["hours_per_run"] = round(hours_per_run, 2)
            result["revenue_per_unit"] = round(prod_price, 2)
            return result

        # 9. 评分
        margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

        volume = get_volume(type_id, "total", sell_hub)
        if volume == 0:
            return result

        profit_score = min(margin_pct * 4, 40)  # 10% = 40分
        volume_factor = min(volume / 5_000_000, 1.0)
        volume_score = volume_factor * 30  # 500万 = 30分
        isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
        efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)  # 5000万/h = 30分

        total_score = profit_score + volume_score + efficiency_score

        result.update(
            {
                "score": round(total_score, 1),
                "profit_per_run": round(profit, 2),
                "margin_pct": round(margin_pct, 2),
                "isk_per_hour": round(isk_per_hour, 2),
                "cost_per_unit": round(total_cost / prod_qty, 2),
                "revenue_per_unit": round(prod_price, 2),
                "hours_per_run": round(hours_per_run, 2),
                "status": "",
                "breakdown": {
                    "waste_factor": round(waste_factor, 2),
                    "profit_score": round(profit_score, 1),
                    "volume_score": round(volume_score, 1),
                    "efficiency_score": round(efficiency_score, 1),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "revenue": round(revenue, 2),
                    "material_cost": round(total_mat_cost, 2),
                    "broker_init": round(broker_init, 2),
                    "broker_relist": round(broker_relist, 2),
                    "sales_tax": round(sales_tax, 2),
                    "facility_fee": round(facility_fee, 2),
                    "install_base": round(install_base, 2),
                    "sci": round(sci, 4),
                    "structure_bonus": round(structure_bonus, 4),
                    "facility_tax_pct": round(facility_tax_pct, 2),
                    "broker_rate": round(broker_rate, 3),
                    "sales_tax_rate": round(sales_tax_rate, 3),
                    "relist_discount": round(relist_discount, 1),
                },
            }
        )

    return result

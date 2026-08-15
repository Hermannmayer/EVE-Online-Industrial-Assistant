"""制造评分纯函数 — 无 self/无 DB/无 Qt/无缓存，可脱离 SQLite 单测。

与 services/scoring_service.py 的 ScoringService.calc_manufacturing_score 逐字节对齐：
本模块只做纯计算，DB 读取（蓝图/材料/名称/价格/SCI/成交量/研究成本）全部由
application/scoring_facade.py 在调用前完成并注入。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.eve_formulas import ADV_INDUSTRY_SKILL_MULT, calc_broker_rate, calc_relist_discount, calc_sales_tax_rate
from domain.formulas import (
    calc_job_cost_fees,
    calc_material_per_run,
    calc_production_time,
)
from domain.ports import PriceProvider


@dataclass(frozen=True)
class Material:
    """单条材料 — 名称已在 application 层解析好，单价由 PriceProvider 提供。"""

    type_id: int
    name: str
    base_qty: int
    wastefactor: int


@dataclass(frozen=True)
class BlueprintRecipe:
    """已从 DB 取出的蓝图 + 材料（名称已解析）。"""

    product_type_id: int
    blueprint_type_id: int
    prod_qty: int
    base_time: int
    materials: tuple[Material, ...]


def calc_manufacturing_score(
    *,
    recipe: BlueprintRecipe,
    prod_price: float,
    prices: PriceProvider,
    research_cost: float,
    char_config: dict | None,
    mat_source_hub: str,
    sell_hub: str,
    price_type_mat: str,
    bp_me: int,
    bp_te: int,
    system_id: int | None,
    structure_bonus: float,
    structure_time_mod: float,
    structure_mat_saving: float,
    facility_tax_pct: float,
    is_alpha: bool,
) -> dict:
    """纯函数：给定蓝图 + 价格提供者 + 参数，计算制造评分结果 dict。

    输出与重构前 ScoringService.calc_manufacturing_score 完全一致（含逐字段 round）。
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

    # 材料成本计算（使用正确的浪费公式 + ceil 取整）
    total_mat_cost = 0.0
    mat_detail = []
    eiv_materials: list[tuple[int, float]] = []
    for mat in recipe.materials:
        wastefactor = mat.wastefactor or 10  # 兜底 T1
        mat_price = prices.get_price(mat.type_id, price_type_mat, mat_source_hub)
        # EIV 使用 adjusted_price（更稳定），兜底用 mat_price
        adj_price = prices.get_adjusted_price(mat.type_id) or mat_price or 0.0
        # 单件材料(基础量=1)不受ME影响——如T1舰船、矿物、组件等
        # 因为 ceil(1×(100-ME)/100)=1，ME 无法将 1 个减到 0 个
        if mat.base_qty <= 1:
            per_run_qty = mat.base_qty
            is_whole_item = True
        else:
            per_run_qty = calc_material_per_run(mat.base_qty, wastefactor, bp_me, structure_mat_saving)
            is_whole_item = False
        waste_qty = per_run_qty  # 每轮次仅用 per_run_qty（已含 ME 调整）
        if mat_price:
            total_mat_cost += waste_qty * mat_price
        # EIV 基础材料量（ME0 无浪费）× adjusted_price
        eiv_materials.append((mat.base_qty, adj_price))
        mat_detail.append(
            {
                "name": mat.name,
                "type_id": mat.type_id,
                "base_qty": mat.base_qty,
                "qty": waste_qty,
                "wastefactor": wastefactor,
                "waste_factor": round(per_run_qty / mat.base_qty, 4) if mat.base_qty > 0 else 1.0,
                "unit_price": mat_price or 0.0,
                "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                "is_whole_item": is_whole_item,
            }
        )
    result["materials"] = mat_detail

    skills = char_config.get("skills", {}) if char_config else {}
    market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    broker_rate = calc_broker_rate(skills, market_data)
    relist_discount = calc_relist_discount(skills)
    sales_tax_rate = calc_sales_tax_rate(skills)

    revenue = prod_price * recipe.prod_qty
    total_cost = total_mat_cost
    sci = prices.get_system_cost_index(system_id, "manufacturing", hub=sell_hub)

    # EIV 计算 & 安装费（加法结构）
    eiv = sum(qty * price for qty, price in eiv_materials)
    # structure_bonus: 传入的 0.0 表示 NPC 无加成 → 乘数 1.0
    # 传入的负值表示折扣（如 -0.1 → 乘数 0.9）
    sb_mult = 1.0 + structure_bonus
    alpha_tax = 0.0025 if is_alpha else 0.0
    fee_detail = calc_job_cost_fees(
        eiv=eiv,
        sci=sci,
        structure_mult=sb_mult,
        facility_tax=facility_tax_pct / 100,
        alpha_tax=alpha_tax,
    )
    system_cost_fee = fee_detail["system_cost"]
    facility_tax_fee = fee_detail["facility_tax"]
    scc_fee = fee_detail["scc"]
    alpha_fee = fee_detail["alpha_tax"]
    installation_fee = fee_detail["total_fee"]
    total_cost += installation_fee

    broker_init = revenue * (broker_rate / 100)
    # 改单差额计费：改单只对「改价差额」部分收一次 broker 费（× 改单折扣）。
    # 无历史挂单价时用成本价近似 —— 假设已按成本挂单、改价到售价只补差额。
    unit_cost = total_cost / recipe.prod_qty if recipe.prod_qty > 0 else 0.0
    relist_delta = max(0.0, prod_price - unit_cost) * recipe.prod_qty
    broker_relist = relist_delta * (broker_rate / 100) * (1 - relist_discount / 100)
    sales_tax = revenue * (sales_tax_rate / 100)
    total_cost += broker_init + broker_relist + sales_tax

    # 未取整原始值：供 calculate_personal_margin 复用，
    # 保证无库存时个人利润率与市场利润率在 2 位小数内严格相等
    result["revenue_per_run"] = revenue
    result["fees_per_run"] = installation_fee + broker_init + broker_relist + sales_tax

    # 研究成本（拷贝/发明）— T1 拷贝、T2/T3 发明，计入总成本
    total_cost += research_cost

    profit = revenue - total_cost

    # 时间计算（使用 calc_production_time）
    ind_lvl = skills.get("工业理论", 5)
    adv_lvl = skills.get("高级工业理论", 5)
    actual_time = calc_production_time(
        base_time=recipe.base_time,
        industry_skill=ind_lvl,
        adv_industry_skill=adv_lvl,
        te_level=bp_te,
        structure_time_mod=structure_time_mod,
    )
    hours_per_run = actual_time / 3600
    margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

    # 费用明细字典（与游戏安装费类目对齐）
    breakdown = {
        "bp_me": bp_me,
        "bp_te": bp_te,
        "isk_per_hour": 0.0,
        "revenue": round(revenue, 2),
        "material_cost": round(total_mat_cost, 2),
        "broker_init": round(broker_init, 2),
        "broker_relist": round(broker_relist, 2),
        "sales_tax": round(sales_tax, 2),
        # 安装费（Job Cost）— 与游戏内显示结构一致
        "eiv": round(eiv, 2),  # 预估物品价值
        "sci": round(sci, 4),  # 星系成本指数
        "system_cost": round(system_cost_fee, 2),  # 项目毛成本（星系成本指数 × EIV）
        "facility_tax": round(facility_tax_fee, 2),  # 设施税
        "scc_surcharge": round(scc_fee, 2),  # SCC 附加费
        "alpha_tax": round(alpha_fee, 2),  # Alpha 税
        "installation_fee": round(installation_fee, 2),  # 项目总费用
        "structure_bonus": round(structure_bonus, 4),
        "structure_time_mod": round(structure_time_mod, 4),
        "structure_mat_saving": round(structure_mat_saving, 4),
        "facility_tax_pct": round(facility_tax_pct, 2),
        "broker_rate": round(broker_rate, 3),
        "sales_tax_rate": round(sales_tax_rate, 3),
        "relist_discount": round(relist_discount, 1),
        "research_cost": round(research_cost, 2),  # 拷贝/发明研究成本
    }

    if profit <= 0:
        result.update(
            {
                "margin_pct": round(margin_pct, 2),
                "profit_per_run": round(profit, 2),
                "cost_per_unit": round(total_cost / recipe.prod_qty, 2),
                "hours_per_run": round(hours_per_run, 2),
                "revenue_per_unit": round(prod_price, 2),
                "breakdown": breakdown,
            }
        )
        return result

    volume = prices.get_volume(recipe.product_type_id, "total", sell_hub)
    if volume == 0:
        return result

    profit_score = min(margin_pct * 4, 40)
    volume_factor = min(volume / 5_000_000, 1.0)
    volume_score = volume_factor * 30
    isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
    efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)
    total_score = profit_score + volume_score + efficiency_score

    breakdown.update(
        {
            "profit_score": round(profit_score, 1),
            "volume_score": round(volume_score, 1),
            "efficiency_score": round(efficiency_score, 1),
            "isk_per_hour": round(isk_per_hour, 2),
        }
    )

    result.update(
        {
            "score": round(total_score, 1),
            "profit_per_run": round(profit, 2),
            "margin_pct": round(margin_pct, 2),
            "isk_per_hour": round(isk_per_hour, 2),
            "cost_per_unit": round(total_cost / recipe.prod_qty, 2),
            "revenue_per_unit": round(prod_price, 2),
            "hours_per_run": round(hours_per_run, 2),
            "status": "",
            "breakdown": breakdown,
        }
    )

    return result


# ════════════════════════════════════════════════════════════════
#  贸易评分纯函数
# ════════════════════════════════════════════════════════════════


def calc_trade_score(
    *,
    type_id: int,
    buy_price: float,
    sell_price: float,
    volume_m3: float,
    prices: PriceProvider,
    char_config: dict | None,
    buy_hub: str,
    sell_hub: str,
    quantity: int,
) -> dict:
    """纯函数：给定买卖价/体积/成交量，计算贸易评分结果 dict。

    输出与重构前 ScoringService.calc_trade_score 完全一致。
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

    skills = char_config.get("skills", {}) if char_config else {}
    market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
    market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    broker_rate = calc_broker_rate(skills, market_data_buy)
    relist_discount = calc_relist_discount(skills)
    sales_tax_rate = calc_sales_tax_rate(skills)

    # 差额计费：初始挂单全额 broker；改单只对「买/卖价差额」部分收一次 broker（× 改单折扣）
    buy_fee_total = broker_rate + broker_rate * (1 - relist_discount / 100)

    sell_rate = calc_broker_rate(skills, market_data_sell)
    # 卖出侧：初始挂单全额 broker（按买入成本近似）+ 改单差额 broker + 销售税
    sell_fee_total = (
        (
            broker_rate
            + (sell_price - buy_price) / sell_price * broker_rate * (1 - relist_discount / 100)
            + sales_tax_rate
        )
        if sell_price > 0
        else sell_rate + sell_rate * (1 - relist_discount / 100) + sales_tax_rate
    )

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

    volume = prices.get_volume(type_id, "total", sell_hub)
    if volume == 0:
        return result

    margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0
    profit_per_m3 = gross_profit / volume_m3 if volume_m3 > 0 else gross_profit

    margin_score = min(margin_pct * 5, 50)
    volume_factor = min(volume / 5_000_000, 1.0)
    vol_score = volume_factor * 50
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


# ════════════════════════════════════════════════════════════════
#  反应评分纯函数
# ════════════════════════════════════════════════════════════════

REACTION_INSTALL_FEE_RATE = 0.05


def calc_reaction_score(
    *,
    product_type_id: int,
    prod_qty: int,
    base_time: int,
    prod_price: float,
    materials: tuple[tuple[int, str, int], ...],
    prices: PriceProvider,
    char_config: dict | None,
    mat_source_hub: str,
    sell_hub: str,
    price_type_mat: str,
    system_id: int | None,
    structure_bonus: float,
    facility_tax_pct: float,
) -> dict:
    """纯函数：给定反应蓝图/材料/价格，计算反应评分结果 dict。

    与制造评分差异：无 ME/TE（waste_factor=1.0）、时间仅受高级工业理论影响、专用 SCI。
    输出与重构前 ScoringService.calc_reaction_score 完全一致。
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

    # 材料成本（反应无 ME 浪费，waste_factor=1.0）
    waste_factor = 1.0
    total_mat_cost = 0.0
    mat_detail = []
    for mat_id, mat_name, mat_qty in materials:
        mat_price = prices.get_price(mat_id, price_type_mat, mat_source_hub)
        waste_qty = mat_qty * waste_factor
        if mat_price:
            total_mat_cost += waste_qty * mat_price
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

    # 从人物配置读取费率
    skills = char_config.get("skills", {}) if char_config else {}
    market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    broker_rate = calc_broker_rate(skills, market_data)
    relist_discount = calc_relist_discount(skills)
    sales_tax_rate_val = calc_sales_tax_rate(skills)

    # 安装费
    revenue = prod_price * prod_qty
    total_cost = total_mat_cost
    sci = prices.get_system_cost_index(system_id, "reaction", hub=mat_source_hub)
    install_base = REACTION_INSTALL_FEE_RATE * revenue
    reaction_install_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
    total_cost += reaction_install_fee
    broker_init = revenue * (broker_rate / 100)
    broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
    sales_tax = revenue * (sales_tax_rate_val / 100)
    total_cost += broker_init + broker_relist + sales_tax

    profit = revenue - total_cost
    margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

    # 反应时间
    adv_lvl = skills.get("高级工业理论", 5)
    skill_mod = 1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl
    actual_time = base_time * skill_mod
    hours_per_run = actual_time / 3600

    # 负利润时提前返回
    if profit <= 0:
        result["margin_pct"] = round(margin_pct, 2)
        result["profit_per_run"] = round(profit, 2)
        result["cost_per_unit"] = round(total_cost / prod_qty, 2)
        result["hours_per_run"] = round(hours_per_run, 2)
        result["revenue_per_unit"] = round(prod_price, 2)
        return result

    # 评分
    margin_pct = profit / total_cost * 100 if total_cost > 0 else 0
    volume = prices.get_volume(product_type_id, "total", sell_hub)
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
                "reaction_install_fee": round(reaction_install_fee, 2),
                "install_base": round(install_base, 2),
                "sci": round(sci, 4),
                "structure_bonus": round(structure_bonus, 4),
                "facility_tax_pct": round(facility_tax_pct, 2),
                "broker_rate": round(broker_rate, 3),
                "sales_tax_rate": round(sales_tax_rate_val, 3),
                "relist_discount": round(relist_discount, 1),
            },
        }
    )

    return result

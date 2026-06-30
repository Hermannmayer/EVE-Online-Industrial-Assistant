"""
评分服务 — 将制造/贸易评分逻辑封装为可注入的服务类
"""

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
    resolve_item_name,
)
from services.database_manager import DatabaseManager
from services.scoring import (
    ScoringCache,
    get_price,
    get_system_cost_index,
    get_volume,
)


class ScoringService:
    def __init__(self, db: DatabaseManager, cache: ScoringCache):
        self._db = db
        self._cache = cache

    # ── 经纪人费率计算（去重：制造/贸易共用） ──

    def _calc_broker_rate(self, skills: dict, market_data: dict) -> float:
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

    def _calc_relist_discount(self, skills: dict) -> float:
        adv_rel = skills.get("高级经纪人关系学", 0)
        return min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

    def _calc_sales_tax_rate(self, skills: dict) -> float:
        accounting = skills.get("会计学", 0)
        return SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

    # ── 制造评分 ──

    def calc_manufacturing_score(
        self,
        type_id: int,
        char_config: dict,
        mat_source_hub: str = "Jita",
        sell_hub: str = "Jita",
        facility_tax_pct: float = 0.0,
        price_type_mat: str = "sell",
        price_type_prod: str = "sell",
        bp_me: int = 0,
        bp_te: int = 0,
        system_id: int | None = None,
        structure_bonus: float = 0.0,
    ) -> dict:
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

        with self._db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()

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

            prod_price = get_price(type_id, price_type_prod, sell_hub, _db=self._db)
            if not prod_price:
                result["status"] = "no_price"
                return result

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

            waste_factor = 1 + ME_WASTE_BASE * (1 - bp_me / 10)
            total_mat_cost = 0.0
            mat_detail = []
            for mat_id, mat_qty in mat_rows:
                mat_price = get_price(mat_id, price_type_mat, mat_source_hub, _db=self._db)
                waste_qty = mat_qty * waste_factor
                if mat_price:
                    total_mat_cost += waste_qty * mat_price
                mat_name = resolve_item_name(c, mat_id)
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

            skills = char_config.get("skills", {}) if char_config else {}
            market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

            broker_rate = self._calc_broker_rate(skills, market_data)
            relist_discount = self._calc_relist_discount(skills)
            sales_tax_rate = self._calc_sales_tax_rate(skills)

            revenue = prod_price * prod_qty
            total_cost = total_mat_cost
            sci = get_system_cost_index(system_id, "manufacturing", _db=self._db)
            install_base = INSTALL_FEE_RATE * revenue
            facility_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
            total_cost += facility_fee
            broker_init = revenue * (broker_rate / 100)
            broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
            sales_tax = revenue * (sales_tax_rate / 100)
            total_cost += broker_init + broker_relist + sales_tax

            profit = revenue - total_cost

            if profit <= 0:
                ind_lvl = skills.get("工业理论", 5)
                adv_lvl = skills.get("高级工业理论", 5)
                skill_mod = (1 - INDUSTRY_SKILL_MULT * ind_lvl) * (1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl)
                te_modifier = 1 - bp_te * TE_MULT_PER_LEVEL
                margin_pct = profit / total_cost * 100 if total_cost > 0 else 0
                result["margin_pct"] = round(margin_pct, 2)
                result["profit_per_run"] = round(profit, 2)
                result["cost_per_unit"] = round(total_cost / prod_qty, 2)
                result["hours_per_run"] = round(base_time * skill_mod * te_modifier / 3600, 2)
                result["revenue_per_unit"] = round(prod_price, 2)
                return result

            margin_pct = profit / total_cost * 100
            ind_lvl = skills.get("工业理论", 5)
            adv_lvl = skills.get("高级工业理论", 5)
            skill_mod = (1 - INDUSTRY_SKILL_MULT * ind_lvl) * (1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl)
            te_modifier = 1 - bp_te * TE_MULT_PER_LEVEL
            actual_time = base_time * skill_mod * te_modifier
            hours_per_run = actual_time / 3600

            volume = get_volume(type_id, "total", sell_hub, _db=self._db)
            if volume == 0:
                return result

            profit_score = min(margin_pct * 4, 40)
            volume_factor = min(volume / 5_000_000, 1.0)
            volume_score = volume_factor * 30
            isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
            efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)
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

    # ── 贸易评分 ──

    def calc_trade_score(
        self,
        type_id: int,
        buy_hub: str = "Jita",
        sell_hub: str = "Jita",
        buy_price_type: str = "buy",
        sell_price_type: str = "sell",
        char_config: dict = None,
        quantity: int = 1,
    ) -> dict:
        result = {
            "score": 0.0,
            "buy_cost": 0.0,
            "sell_revenue": 0.0,
            "gross_profit": 0.0,
            "margin_pct": 0.0,
            "profit_per_m3": 0.0,
            "status": "",
        }

        buy_price = get_price(type_id, buy_price_type, buy_hub, _db=self._db)
        sell_price = get_price(type_id, sell_price_type, sell_hub, _db=self._db)
        if not buy_price or not sell_price:
            result["status"] = "no_price"
            return result

        with self._db.connect("ref") as conn:
            c = conn.cursor()
            c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
            row = c.fetchone()
            volume_m3 = row[0] or 1.0 if row else 1.0

        skills = char_config.get("skills", {}) if char_config else {}
        market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
        market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

        broker_rate = self._calc_broker_rate(skills, market_data_buy)
        relist_discount = self._calc_relist_discount(skills)
        sales_tax_rate = self._calc_sales_tax_rate(skills)

        buy_fee_total = broker_rate + broker_rate * (1 - relist_discount / 100)

        sell_rate = self._calc_broker_rate(skills, market_data_sell)
        sell_fee_total = sell_rate + sell_rate * (1 - relist_discount / 100) + sales_tax_rate

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

        volume = get_volume(type_id, "total", sell_hub, _db=self._db)
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

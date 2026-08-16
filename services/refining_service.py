"""
精炼价值计算
"""

from core.eve_formulas import calc_refining_yield
from services.pricing_service import PricingService


class RefiningService:
    def __init__(self, db, pricing_service=None):
        self._db = db
        self._pricing = pricing_service or PricingService(db)

    def filter_refinable(self, items: list[dict]) -> list[dict]:
        """过滤出有精炼材料数据的物品。"""
        model_items = []
        with self._db.connect("ref") as conn:
            cur = conn.cursor()
            for item in items:
                cur.execute(
                    "SELECT COUNT(*) FROM reprocessing_materials WHERE type_id = ?",
                    (item["type_id"],),
                )
                if cur.fetchone()[0] > 0:
                    model_items.append(item)
        return model_items

    def calc_value(
        self,
        type_id,
        quantity=1,
        *,
        skills=None,
        is_player_facility=False,
        price_hub="Jita",
        yield_override=None,
        ore_skill=0,
    ) -> dict:
        """完整实现（从 scoring_service.py 迁移）"""
        from services.name_resolver import resolve_item_name

        yield_rate = (
            yield_override
            if yield_override is not None
            else calc_refining_yield(skills, is_player_facility=is_player_facility)
        )
        yield_rate += ore_skill * 0.02
        yield_rate = min(yield_rate, 0.85)

        with self._db.connect("ref") as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT material_type_id, quantity FROM reprocessing_materials WHERE type_id = ?",
                (type_id,),
            )
            materials = cur.fetchall()

        if not materials:
            return {
                "yield_rate": yield_rate,
                "output": [],
                "total_value": 0,
                "input_value": 0,
                "profit": 0,
                "margin_pct": 0,
            }

        output = []
        total_value = 0.0
        with self._db.connect("ref") as conn:
            cur = conn.cursor()
            for mat_id, mat_qty in materials:
                qty = mat_qty * yield_rate * quantity
                price = self._pricing.get_price(mat_id, "sell", price_hub) or 0.0
                total = round(qty * price, 2)
                name = resolve_item_name(cur, mat_id)
                output.append(
                    {
                        "type_id": mat_id,
                        "name": name,
                        "qty": round(qty, 2),
                        "price": price,
                        "total": total,
                    }
                )
                total_value += total

        input_price = self._pricing.get_price(type_id, "sell", price_hub) or 0.0
        input_value = input_price * quantity
        profit = total_value - input_value
        margin_pct = (profit / input_value * 100) if input_value > 0 else 0.0

        return {
            "yield_rate": round(yield_rate, 4),
            "output": output,
            "total_value": round(total_value, 2),
            "input_value": round(input_value, 2),
            "profit": round(profit, 2),
            "margin_pct": round(margin_pct, 2),
        }

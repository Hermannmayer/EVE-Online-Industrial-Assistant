"""
精炼价值计算

数据来源：reference.db reprocessing_materials（可精炼物料与产出）、
market.db 价格（经 PricingService）。产率公式 calc_refining_yield 在 core.eve_formulas。
被估算页 refine_worker 消费。
"""

from core.eve_formulas import calc_refining_yield
from services.pricing_service import PricingService

#: 矿石类目（SDE `category_id`）。**只有矿石吃「矿石专精」** —— 模块/弹药/船体虽然也有回收
#: 配方，但技能表里没有对应的处理技术，拿组名去拼必然拼出个不存在的技能。
_ORE_CATEGORY_ID = 25

#: 按名字推不出来的矿石组 → 技能英文名（核对过 SDE 里确实存在该技能）
_ORE_SKILL_EXCEPTIONS = {
    "Mercoxit": "Mercoxit Ore Processing",  # 技能名里多了个 Ore
}
#: 卫星小行星按稀有度共用技能：`<Rarity> Moon Asteroids` → `<Rarity> Moon Ore Processing`
_MOON_ASTEROIDS_SUFFIX = " Moon Asteroids"
_MOON_PROCESSING_SUFFIX = " Moon Ore Processing"


def _ore_skill_candidates(group_en: str) -> list[str]:
    """矿石组英文名 → 可能的专精技能英文名（按优先级，取第一个在 SDE 里存在的）。"""
    if group_en in _ORE_SKILL_EXCEPTIONS:
        return [_ORE_SKILL_EXCEPTIONS[group_en]]
    out: list[str] = []
    if group_en.endswith(_MOON_ASTEROIDS_SUFFIX):
        rarity = group_en[: -len(_MOON_ASTEROIDS_SUFFIX)]
        out.append(f"{rarity}{_MOON_PROCESSING_SUFFIX}")
    out.append(f"{group_en} Processing")
    if "Ice" in group_en:
        # 冰矿只有一个技能；压缩冰（`Ancient Compressed Ice`）也吃它
        out.append("Ice Processing")
    return out


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

    def ore_skill_info(self, type_id: int) -> tuple[bool, str]:
        """→ `(是不是矿石, 矿石专精技能名/中文或空串)`。

        依据是 SDE 自身的命名：矿石类目里专精技能恒为「<矿石组英文名> Processing」——
        逐条核对过 39 个有回收配方的矿石组，经典矿石（凡晶石/灰岩/斜长岩/双多特…）全部命中。
        三类按名字推不出来的另作处理（都核对过 SDE 里确实存在那个技能）：

        - 卫星小行星按稀有度共用：`Common Moon Asteroids` → `Common Moon Ore Processing`；
        - 冰矿只有一个技能 `Ice Processing`，压缩冰（`Ancient Compressed Ice`）也用它；
        - 基腹断岩是 `Mercoxit Ore Processing`（技能名里多一个 `Ore`）。

        ⚠️ **2024 年后的新矿种（杜希石/艾弗石/萤石…）第二个值返回空串**：SDE 里既没有同名
        技能，本地也查不到官方关联 —— EVE 用 dogma 属性 `reprocessingSkillType` 把矿种连到
        技能，而本仓的 `item_dogma` 只导入了 456 条**空壳**、0 条带该属性。这类矿种按 0 级算，
        由调用方在界面上写明「未映射」；**绝不猜一个技能上去**（猜错就是静默算错 ISK）。

        第一个值用来区分「不是矿石」与「是矿石但没映射上」—— 两者在界面上该说不同的话。
        """
        with self._db.connect("ref") as conn:
            row = conn.execute(
                "SELECT category_id, en_group_name FROM item WHERE type_id = ?", (int(type_id),)
            ).fetchone()
            if not row or int(row[0] or 0) != _ORE_CATEGORY_ID:
                return False, ""
            group = str(row[1] or "")
            if not group:
                return True, ""
            for en_name in _ore_skill_candidates(group):
                found = conn.execute("SELECT zh_name FROM item WHERE en_name = ?", (en_name,)).fetchone()
                if found and found[0]:
                    return True, str(found[0])
        return True, ""

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
            else calc_refining_yield(skills, is_player_facility=is_player_facility, ore_skill_level=ore_skill)
        )
        # 矿石专精已进公式（乘性）；上限由公式按 NPC 站/玩家结构分别施加
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

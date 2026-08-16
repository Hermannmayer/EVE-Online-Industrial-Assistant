"""蓝图数据查询仓库"""

from __future__ import annotations


class BlueprintRepository:
    """蓝图只读查询"""

    def __init__(self, db):
        self._db = db

    def get_blueprint_for_product(self, product_type_id: int, activity: str = "manufacturing") -> tuple | None:
        """查找产出指定物品的蓝图 → (blueprint_type_id, output_qty, base_time) or None"""
        with self._db.connect("ref", "bp") as conn:
            r = conn.execute(
                """SELECT bp.blueprint_type_id, bp.quantity, ba.time
                   FROM bp.blueprint_products bp
                   JOIN bp.blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id AND ba.activity = bp.activity
                   WHERE bp.product_type_id = ? AND bp.activity = ? LIMIT 1""",
                (product_type_id, activity),
            ).fetchone()
            return (r[0], r[1] or 1, r[2]) if r else None

    def get_materials(self, blueprint_type_id: int, activity: str = "manufacturing") -> list[tuple]:
        """获取蓝图材料 → [(material_type_id, quantity, wastefactor), ...]"""
        from services.manufacturing_calculator import DEFAULT_WASTEFACTOR

        with self._db.connect("bp") as conn:
            rows = conn.execute(
                """SELECT material_type_id, quantity, ?
                   FROM blueprint_materials WHERE blueprint_type_id = ? AND activity = ?""",
                (DEFAULT_WASTEFACTOR, blueprint_type_id, activity),
            ).fetchall()
            return [(r[0], r[1], r[2] or 10) for r in rows]

    def get_all_product_ids(self, activity: str = "manufacturing") -> list[int]:
        with self._db.connect("bp") as conn:
            rows = conn.execute(
                "SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity = ?", (activity,)
            ).fetchall()
            return [r[0] for r in rows]

    def get_all_blueprint_product_ids(self) -> set[int]:
        """所有出现在 blueprint_products 中的产出物 type_id。"""
        with self._db.connect("bp") as conn:
            rows = conn.execute("SELECT DISTINCT product_type_id FROM blueprint_products").fetchall()
            return {r[0] for r in rows}

    def get_t1_manufacturable_product_ids(self) -> set[int]:
        """T1 制造产物：有制造蓝图，且该蓝图不是发明产物。"""
        with self._db.connect("bp") as conn:
            rows = conn.execute(
                """SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                WHERE bp.activity='manufacturing'
                AND bp.blueprint_type_id NOT IN (
                    SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                )"""
            ).fetchall()
            return {r[0] for r in rows}

    def get_t2_manufacturable_product_ids(self) -> set[int]:
        """T2 发明产物：有制造蓝图，且该蓝图由发明产出。"""
        with self._db.connect("bp") as conn:
            rows = conn.execute(
                """SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                WHERE bp.activity='manufacturing'
                AND bp.blueprint_type_id IN (
                    SELECT product_type_id FROM blueprint_products WHERE activity='invention'
                )"""
            ).fetchall()
            return {r[0] for r in rows}

    def get_faction_manufacturable_product_ids(self) -> set[int]:
        """势力蓝图制造产物：制造产物名称匹配常见势力关键词。"""
        with self._db.connect("ref", "bp") as conn:
            rows = conn.execute(
                """SELECT DISTINCT bp.product_type_id FROM blueprint_products bp
                JOIN item i ON bp.product_type_id=i.type_id
                WHERE bp.activity='manufacturing' AND (
                    i.en_name LIKE '%Navy%' OR i.en_name LIKE '%Faction%'
                    OR i.en_name LIKE '%Imperial%' OR i.en_name LIKE '%Republic%'
                    OR i.en_name LIKE '%Federation%' OR i.en_name LIKE '%State%')"""
            ).fetchall()
            return {r[0] for r in rows}

    def get_manufacturable_market_tree(self) -> list[dict]:
        """可制造物品关联的市场分类树（id/parent/name 字典列表）。"""
        with self._db.connect("ref", "bp") as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE ancestors(id) AS (
                    SELECT DISTINCT i.market_group_id
                    FROM item i
                    JOIN blueprint_products bp ON i.type_id = bp.product_type_id
                    WHERE bp.activity = 'manufacturing'
                    UNION ALL
                    SELECT mt.parent_group_id
                    FROM market_tree mt
                    JOIN ancestors a ON mt.market_group_id = a.id
                    WHERE mt.parent_group_id IS NOT NULL
                )
                SELECT DISTINCT mt.market_group_id, mt.parent_group_id, mt.zh_name
                FROM market_tree mt
                WHERE mt.market_group_id IN (SELECT id FROM ancestors)
                ORDER BY mt.zh_name
                """
            ).fetchall()
            return [{"id": i, "p": p, "n": z or f"G{i}"} for i, p, z in rows]

    def get_manufacturing_materials(
        self, product_type_id: int
    ) -> tuple[int, list[tuple[int, int, str, str, float | None]]] | None:
        """查询产品制造材料及最新卖价。

        返回 (blueprint_type_id, [(material_type_id, quantity, zh_name, en_name, sell_price), ...])；
        无制造蓝图时返回 None。
        """
        with self._db.connect("ref", "mkt", "bp") as conn:
            bp = conn.execute(
                """SELECT blueprint_type_id
                FROM blueprint_products
                WHERE product_type_id=? AND activity='manufacturing' ORDER BY blueprint_type_id LIMIT 1""",
                (product_type_id,),
            ).fetchone()
            if not bp:
                return None
            bp_id = int(bp[0])
            rows = conn.execute(
                """SELECT bm.material_type_id,bm.quantity,i.zh_name,i.en_name,mp.sell_price
                FROM blueprint_materials bm JOIN item i ON bm.material_type_id=i.type_id
                LEFT JOIN mkt.market_prices mp ON mp.type_id=i.type_id
                AND mp.fetch_time=(SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id=i.type_id)
                WHERE bm.blueprint_type_id=? AND bm.activity='manufacturing' ORDER BY i.zh_name""",
                (bp_id,),
            ).fetchall()
            return bp_id, [
                (int(r[0]), int(r[1]), str(r[2] or ""), str(r[3] or ""), float(r[4]) if r[4] is not None else None)
                for r in rows
            ]

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

    def get_bp_detail(self, type_id: int) -> dict | None:
        """获取蓝图详情（跨库 JOIN ref + bp）"""
        with self._db.connect("ref", "bp") as conn:
            row = conn.execute(
                """SELECT b.type_id, i.name, b.product_type_id, pi.name AS product_name,
                          b.quantity, b.time, b.me, b.pe
                   FROM bp.blueprints b
                   JOIN ref.item i ON b.type_id = i.type_id
                   LEFT JOIN ref.item pi ON b.product_type_id = pi.type_id
                   WHERE b.type_id = ? ORDER BY b.me, b.pe LIMIT 1""",
                (type_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_all_product_ids(self, activity: str = "manufacturing") -> list[int]:
        with self._db.connect("bp") as conn:
            rows = conn.execute(
                "SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity = ?", (activity,)
            ).fetchall()
            return [r[0] for r in rows]

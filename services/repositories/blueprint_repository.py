"""蓝图数据查询仓库"""

from __future__ import annotations

from collections.abc import Iterable

from services.blueprint_reader import get_blueprint_products

#: `IN (...)` 分批上限（SQLite 变量上限 999，留余量）
_BATCH_SIZE = 900


class BlueprintRepository:
    """蓝图只读查询"""

    def __init__(self, db):
        self._db = db

    def get_blueprint_for_product(self, product_type_id: int, activity: str = "manufacturing") -> tuple | None:
        """查找产出指定物品的蓝图 → (blueprint_type_id, output_qty, base_time) or None

        走统一入口 `blueprint_reader.get_blueprint_products`：同一产物挂 CCP 测试蓝图
        与真实蓝图时取真实蓝图（见该模块 `_TEST_BLUEPRINT_SQL` 说明）。
        """
        with self._db.connect("ref", "bp") as conn:
            r = get_blueprint_products(conn, product_type_id, activity)
            return (r[0], r[1] or 1, r[2]) if r else None

    def get_materials(self, blueprint_type_id: int, activity: str = "manufacturing") -> list[tuple]:
        """获取蓝图材料 → [(material_type_id, quantity, wastefactor), ...]"""
        from domain.formulas import DEFAULT_WASTEFACTOR

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
        """可制造物品关联的市场分类树（id/parent/name 字典列表）。

        `activity` 同时取 `manufacturing` 与 `reaction`：反应产物（111 个）原先
        进不了树 —— 「类别 = 反应」下整棵树 988/988 个节点全空（节点的可制造性由
        同一个 `blueprint_products` 判，树里没有它的分类自然一个都点不出来）。
        实测并入后 988 → 994 行，新增 6 个节点全在「制造和研究 → 材料 → 反应材料」下
        （反应材料 / 高级卫星材料 / 加工过的卫星材料 / 增效剂材料 / 聚合物材料 /
        分子熔铸材料），无节点消失。
        """
        with self._db.connect("ref", "bp") as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE ancestors(id) AS (
                    SELECT DISTINCT i.market_group_id
                    FROM item i
                    JOIN blueprint_products bp ON i.type_id = bp.product_type_id
                    WHERE bp.activity IN ('manufacturing', 'reaction')
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

    def get_product_market_groups(self, type_ids: Iterable[int]) -> dict[int, int]:
        """产物 type_id → 市场分类 id（`{product_type_id: market_group_id}`）。

        只含 `reference.db.item` 里查得到、且 `market_group_id IS NOT NULL` 的行；
        查不到的产物不在返回字典里（调用方按「没有分类」处理）。空输入 → `{}`。

        调用方（可制造物品窗口）拿它判断每个树节点在当前「类别」下有没有物品。
        """
        ids = sorted({int(t) for t in type_ids})
        out: dict[int, int] = {}
        if not ids:
            return out
        with self._db.connect("ref") as conn:
            for start in range(0, len(ids), _BATCH_SIZE):
                batch = ids[start : start + _BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                rows = conn.execute(
                    f"SELECT type_id, market_group_id FROM item "
                    f"WHERE market_group_id IS NOT NULL AND type_id IN ({placeholders})",
                    batch,
                ).fetchall()
                out.update({int(r[0]): int(r[1]) for r in rows})
        return out

    def get_manufacturing_blueprint_name(self, product_type_id: int) -> str | None:
        """产物 type_id → 其制造/反应蓝图的**中文名**（蓝图物品本身的名字）。

        同一物品既有制造又有反应蓝图时优先制造。找不到蓝图、或蓝图物品在
        `item` 表里没有名字（中英文都空）→ `None`。
        """
        with self._db.connect("ref", "bp") as conn:
            row = conn.execute(
                """SELECT i.zh_name, i.en_name
                   FROM blueprint_products bp JOIN item i ON i.type_id = bp.blueprint_type_id
                   WHERE bp.product_type_id = ? AND bp.activity IN ('manufacturing', 'reaction')
                   ORDER BY CASE WHEN bp.activity = 'manufacturing' THEN 0 ELSE 1 END LIMIT 1""",
                (product_type_id,),
            ).fetchone()
        if not row:
            return None
        return row[0] or row[1] or None

    def get_manufacturing_materials(
        self, product_type_id: int
    ) -> tuple[int, list[tuple[int, int, str, str, float | None]]] | None:
        """查询产品制造材料及最新卖价。

        返回 (blueprint_type_id, [(material_type_id, quantity, zh_name, en_name, sell_price), ...])；
        无制造蓝图时返回 None。
        """
        with self._db.connect("ref", "mkt", "bp") as conn:
            bp = get_blueprint_products(conn, product_type_id, "manufacturing")
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

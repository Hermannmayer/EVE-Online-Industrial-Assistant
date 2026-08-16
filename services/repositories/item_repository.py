"""物品基础数据查询仓库"""

from __future__ import annotations

from sqlite3 import Connection


class ItemRepository:
    """物品数据只读查询"""

    def __init__(self, db):
        self._db = db

    def get_name(self, type_id: int, conn: Connection | None = None) -> str:
        """获取物品名称：矿物映射优先 → zh_name → en_name → str(type_id)"""
        from services.name_resolver import resolve_item_name

        if conn is not None:
            return resolve_item_name(conn, type_id)
        with self._db.connect("ref") as c:
            return resolve_item_name(c, type_id)

    def get_volume(self, type_id: int) -> float:
        with self._db.connect("ref") as conn:
            r = conn.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,)).fetchone()
            return float(r[0]) if r and r[0] else 1.0

    def get_by_id(self, type_id: int) -> dict | None:
        with self._db.connect("ref") as conn:
            r = conn.execute(
                "SELECT type_id, zh_name, en_name, volume, group_id, market_group_id " "FROM item WHERE type_id = ?",
                (type_id,),
            ).fetchone()
            return dict(r) if r else None

    def get_by_name(self, name: str) -> dict | None:
        """按中/英文名精确查找单个物品。"""
        with self._db.connect("ref") as conn:
            r = conn.execute(
                "SELECT type_id, zh_name, en_name FROM item WHERE zh_name=? OR en_name=? LIMIT 1",
                (name, name),
            ).fetchone()
            if not r:
                return None
            return {"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""}

    def search_by_name(self, keyword: str, limit: int = 50) -> list[dict]:
        with self._db.connect("ref") as conn:
            like = f"%{keyword}%"
            rows = conn.execute(
                """SELECT type_id, zh_name, en_name FROM item
                   WHERE en_name LIKE ? OR zh_name LIKE ?
                   ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                            LENGTH(en_name), type_id
                   LIMIT ?""",
                (like, like, f"{keyword}%", f"{keyword}%", limit),
            ).fetchall()
            return [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in rows]

    def get_root_market_categories(self) -> list[tuple[int, str]]:
        """根级市场分类 [(market_group_id, zh_name), ...]。"""
        with self._db.connect("ref") as conn:
            rows = conn.execute(
                "SELECT market_group_id, zh_name FROM market_tree "
                "WHERE parent_group_id IS NULL ORDER BY zh_name"
            ).fetchall()
            return [(int(r[0]), str(r[1] or "")) for r in rows]

    def get_market_descendants(self, market_group_id: int) -> set[int]:
        """递归获取指定市场分类下所有物品 type_id。"""
        with self._db.connect("ref") as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE sub AS (
                    SELECT market_group_id FROM market_tree WHERE market_group_id = ?
                    UNION ALL
                    SELECT m.market_group_id FROM market_tree m JOIN sub ON m.parent_group_id = sub.market_group_id
                )
                SELECT DISTINCT i.type_id FROM item i
                WHERE i.market_group_id IN (SELECT market_group_id FROM sub)
                """,
                (market_group_id,),
            ).fetchall()
            return {int(r[0]) for r in rows}

    def count(self) -> int:
        with self._db.connect("ref") as conn:
            r = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            return r[0] if r else 0

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

    def count(self) -> int:
        with self._db.connect("ref") as conn:
            r = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            return r[0] if r else 0

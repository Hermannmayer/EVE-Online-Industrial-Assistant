"""生产计划 CRUD 仓库"""

from __future__ import annotations

from datetime import UTC, datetime


class PlanRepository:
    """生产计划表的增删改查"""

    def __init__(self, db):
        self._db = db

    SCHEMA = """CREATE TABLE IF NOT EXISTS production_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_type_id INTEGER NOT NULL,
        product_name TEXT,
        blueprint_type_id INTEGER,
        runs INTEGER DEFAULT 1,
        parallels INTEGER DEFAULT 1,
        me_level INTEGER DEFAULT 0,
        te_level INTEGER DEFAULT 0,
        mat_hub TEXT DEFAULT 'Jita',
        sell_hub TEXT DEFAULT 'Jita',
        facility TEXT DEFAULT '',
        char_name TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        profit REAL DEFAULT 0,
        margin REAL DEFAULT 0,
        score REAL DEFAULT 0,
        material_cost REAL DEFAULT 0,
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT
    );"""

    def ensure_table(self):
        with self._db.connect("user") as conn:
            conn.executescript(self.SCHEMA)

    def get_by_id(self, plan_id: int) -> dict | None:
        with self._db.connect("user") as conn:
            r = conn.execute("SELECT * FROM production_plans WHERE id = ?", (plan_id,)).fetchone()
            return dict(r) if r else None

    def get_all(self, status: str | None = None) -> list[dict]:
        with self._db.connect("user") as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM production_plans WHERE status = ? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM production_plans ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def save(self, plan: dict) -> int:
        with self._db.connect("user") as conn:
            now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            c = conn.cursor()
            c.execute(
                """INSERT INTO production_plans
                   (product_type_id, product_name, blueprint_type_id, runs, parallels,
                    me_level, te_level, mat_hub, sell_hub, facility, char_name,
                    status, profit, margin, score, material_cost, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.get("product_type_id"),
                    plan.get("product_name"),
                    plan.get("blueprint_type_id"),
                    plan.get("runs", 1),
                    plan.get("parallels", 1),
                    plan.get("me_level", 0),
                    plan.get("te_level", 0),
                    plan.get("mat_hub", "Jita"),
                    plan.get("sell_hub", "Jita"),
                    plan.get("facility", ""),
                    plan.get("char_name", ""),
                    plan.get("status", "pending"),
                    plan.get("profit", 0),
                    plan.get("margin", 0),
                    plan.get("score", 0),
                    plan.get("material_cost", 0),
                    now,
                ),
            )
            return c.lastrowid or 0

    def update(self, plan_id: int, **fields) -> bool:
        if not fields:
            return False
        with self._db.connect("user") as conn:
            sets = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [plan_id]
            conn.execute(f"UPDATE production_plans SET {sets} WHERE id = ?", vals)
            return conn.total_changes > 0

    def delete(self, plan_id: int) -> bool:
        with self._db.connect("user") as conn:
            conn.execute("DELETE FROM production_plans WHERE id = ?", (plan_id,))
            return conn.total_changes > 0

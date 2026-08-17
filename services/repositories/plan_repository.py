"""生产计划 CRUD 仓库"""

from __future__ import annotations

from datetime import UTC, datetime


class PlanRepository:
    """生产计划表的增删改查"""

    def __init__(self, db):
        self._db = db

    # 允许通过动态更新写入的列白名单，防止任意字段名拼接进 SQL。
    ALLOWED_FIELDS = frozenset(
        {
            "product_type_id",
            "product_name",
            "blueprint_type_id",
            "runs",
            "parallels",
            "me_level",
            "te_level",
            "mat_hub",
            "sell_hub",
            "facility",
            "char_name",
            "status",
            "profit",
            "margin",
            "score",
            "material_cost",
            "created_at",
            "started_at",
            "completed_at",
            "facility_cost_mult",
            "calculated_time",
            "notes",
            "group_number",
            "sub_level",
            "output_location",
            "market_margin",
            "personal_margin",
            "daily_output",
            "materials_ready",
            "iskph",
            "deposit_hangar_id",
            "deposited",
            "assigned_blueprint_id",
            "mat_hangar_id",
            "material_short",
            "deducted_materials",
            "solar_system_id",
            "source_mother_ids",
            "component_parent_type_id",
            "demand",
        }
    )

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
        completed_at TEXT,
        facility_cost_mult REAL DEFAULT 1.0,
        calculated_time REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        group_number INTEGER DEFAULT 0,
        sub_level INTEGER DEFAULT 0,
        output_location TEXT DEFAULT '',
        market_margin REAL DEFAULT 0,
        personal_margin REAL DEFAULT 0,
        daily_output REAL DEFAULT 0,
        materials_ready INTEGER DEFAULT 0,
        iskph REAL DEFAULT 0,
        deposit_hangar_id INTEGER DEFAULT NULL,
        deposited INTEGER DEFAULT 0,
        assigned_blueprint_id INTEGER DEFAULT NULL,
        mat_hangar_id INTEGER DEFAULT NULL,
        material_short TEXT DEFAULT '',
        deducted_materials TEXT DEFAULT '',
        solar_system_id INTEGER DEFAULT NULL,
        source_mother_ids TEXT DEFAULT '',
        component_parent_type_id INTEGER DEFAULT NULL,
        demand INTEGER DEFAULT 0
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

    def find_by_group_product(self, group_number: int, product_type_id: int) -> int | None:
        """按分组号+产品查找已存在的子计划 id。"""
        with self._db.connect("user") as conn:
            r = conn.execute(
                "SELECT id FROM production_plans WHERE group_number=? AND product_type_id=? LIMIT 1",
                (group_number, product_type_id),
            ).fetchone()
            return int(r[0]) if r else None

    def save(self, plan: dict) -> int:
        with self._db.connect("user") as conn:
            now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            c = conn.cursor()
            c.execute(
                """INSERT INTO production_plans
                   (product_type_id, product_name, blueprint_type_id, runs, parallels,
                    me_level, te_level, mat_hub, sell_hub, facility, char_name,
                    status, profit, margin, score, material_cost, created_at, materials_ready)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
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

    @staticmethod
    def _allowed_fields(fields: dict) -> dict:
        return {k: v for k, v in fields.items() if k in PlanRepository.ALLOWED_FIELDS}

    def update(self, plan_id: int, **fields) -> bool:
        fields = self._allowed_fields(fields)
        if not fields:
            return False
        with self._db.connect("user") as conn:
            sets = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [plan_id]
            conn.execute(f"UPDATE production_plans SET {sets} WHERE id = ?", vals)
            return conn.total_changes > 0  # type: ignore[no-any-return]

    def update_many(self, plan_ids: list[int], **fields) -> int:
        """批量更新多条计划的同一组字段（列名来自内部，参数化值）。返回受影响行数。"""
        fields = self._allowed_fields(fields)
        if not plan_ids or not fields:
            return 0
        with self._db.connect("user") as conn:
            sets = ", ".join(f"{k} = ?" for k in fields)
            ph = ",".join("?" * len(plan_ids))
            vals = list(fields.values()) + list(plan_ids)
            cur = conn.execute(f"UPDATE production_plans SET {sets} WHERE id IN ({ph})", vals)
            return int(cur.rowcount)

    def update_batch(self, rows: list[tuple[int, dict]]) -> int:
        """批量异构更新：rows = [(plan_id, {field: value}), ...]，单连接单事务。返回更新行数。"""
        if not rows:
            return 0
        total = 0
        with self._db.connect("user") as conn:
            for plan_id, fields in rows:
                fields = self._allowed_fields(fields)
                if not fields:
                    continue
                sets = ", ".join(f"{k} = ?" for k in fields)
                vals = list(fields.values()) + [plan_id]
                cur = conn.execute(f"UPDATE production_plans SET {sets} WHERE id = ?", vals)
                total += int(cur.rowcount)
        return total

    def insert_child_plan(
        self,
        *,
        product_type_id: int,
        product_name: str,
        blueprint_type_id: int,
        runs: int,
        parallels: int,
        me_level: int,
        te_level: int,
        group_number: int,
        sub_level: int,
        mat_hangar_id: int | None,
        solar_system_id: int | None,
        deposit_hangar_id: int | None = None,
        source_mother_ids: str = "",
        component_parent_type_id: int | None = None,
        demand: int = 0,
    ) -> int:
        """插入一条拆解子计划（含分组/层级/机库/引用式需求字段）。"""
        with self._db.connect("user") as conn:
            cur = conn.execute(
                """
                INSERT INTO production_plans
                (product_type_id, product_name, blueprint_type_id, runs, parallels, me_level, te_level,
                 status, group_number, sub_level, mat_hangar_id, solar_system_id, deposit_hangar_id,
                 materials_ready, source_mother_ids, component_parent_type_id, demand)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    product_type_id,
                    product_name,
                    blueprint_type_id,
                    runs,
                    parallels,
                    me_level,
                    te_level,
                    group_number,
                    sub_level,
                    mat_hangar_id,
                    solar_system_id,
                    deposit_hangar_id,
                    source_mother_ids,
                    component_parent_type_id,
                    demand,
                ),
            )
            return int(cur.lastrowid or 0)

    def delete_many(self, plan_ids: list[int]) -> int:
        """批量删除计划（蓝图表关联清理由调用方 release_blueprint 处理）。返回删除行数。"""
        if not plan_ids:
            return 0
        with self._db.connect("user") as conn:
            ph = ",".join("?" * len(plan_ids))
            cur = conn.execute(f"DELETE FROM production_plans WHERE id IN ({ph})", list(plan_ids))
            return int(cur.rowcount)

    def delete(self, plan_id: int) -> bool:
        with self._db.connect("user") as conn:
            # 清理蓝图绑定关联表（若表存在），避免孤儿占用
            has_bindings = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='plan_blueprint_bindings'"
            ).fetchone()
            if has_bindings:
                conn.execute("DELETE FROM plan_blueprint_bindings WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM production_plans WHERE id = ?", (plan_id,))
            return conn.total_changes > 0  # type: ignore[no-any-return]

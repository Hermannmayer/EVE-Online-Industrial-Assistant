"""
蓝图数据访问层 — 统一蓝图查询接口。

替代多处分散的 SELECT FROM blueprint_materials 查询。
依赖 blueprint.db 中的 blueprint_materials 表。
"""

from __future__ import annotations

import sqlite3

from domain.formulas import DEFAULT_WASTEFACTOR

#: 蓝图表查找索引。三张表虽有复合主键（自带 sqlite_autoindex），但 `blueprint_products`
#: 的查询按 product_type_id（非主键前缀）过滤，另外两张按 (blueprint_type_id, activity)
#: 过滤时计划器仍选全表扫 —— 实测 `research_cost_for_item`（仍在用的逐件路径）：
#: 无索引 3.92 ms/件 → 建索引后 0.10 ms/件（**37×**，200 件 784ms → 21ms）。
#: 归因已排除 ANALYZE：只跑统计信息、不建索引仍是 ~760 ms。
_BLUEPRINT_INDEXES = (
    ("idx_bp_materials_bp_act", "blueprint_materials", "blueprint_type_id, activity"),
    ("idx_bp_products_prod_act", "blueprint_products", "product_type_id, activity"),
    ("idx_bp_activities_bp", "blueprint_activities", "blueprint_type_id"),
)


def blueprint_index_sql() -> list[str]:
    """蓝图表索引的 CREATE 语句（导入器与 schema 迁移共用这一处定义）。"""
    return [f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})" for name, table, cols in _BLUEPRINT_INDEXES]


def get_blueprint_materials(
    conn: sqlite3.Connection,
    blueprint_type_id: int,
    activity: str = "manufacturing",
) -> list[tuple[int, int, int]]:
    """获取蓝图所需材料列表。

    Args:
        conn: blueprint.db 的数据库连接
        blueprint_type_id: 蓝图 type_id
        activity: 活动类型（默认 'manufacturing'）

    Returns:
        [(material_type_id, quantity, wastefactor), ...]
        空列表表示无材料。
    """
    cur = conn.execute(
        """
        SELECT material_type_id, quantity, COALESCE(wastefactor, ?)
        FROM blueprint_materials
        WHERE blueprint_type_id = ? AND activity = ?
        """,
        (DEFAULT_WASTEFACTOR, blueprint_type_id, activity),
    )
    return cur.fetchall()


def get_blueprint_products(
    conn: sqlite3.Connection,
    product_type_id: int,
    activity: str = "manufacturing",
) -> tuple[int, int, int] | None:
    """根据产品 type_id 查找对应的蓝图信息。

    Args:
        conn: blueprint.db 的连接
        product_type_id: 产品 type_id
        activity: 活动类型（默认 'manufacturing'）

    Returns:
        (blueprint_type_id, quantity, base_time) 或 None
    """
    cur = conn.execute(
        """
        SELECT bp.blueprint_type_id, bp.quantity, ba.time
        FROM blueprint_products bp
        JOIN blueprint_activities ba
            ON ba.blueprint_type_id = bp.blueprint_type_id
            AND ba.activity = bp.activity
        WHERE bp.product_type_id = ? AND bp.activity = ?
        LIMIT 1
        """,
        (product_type_id, activity),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return (int(row[0]), int(row[1]), int(row[2]))


class SqliteBlueprintReader:
    """BlueprintReader 适配 — 基于 sqlite 连接的蓝图查询（实现 domain.bom.BlueprintReader）。"""

    def __init__(self, conn):
        self._conn = conn

    def product(self, product_type_id: int, activity: str = "manufacturing") -> tuple[int, int] | None:
        row = get_blueprint_products(self._conn, product_type_id, activity)
        if row is None:
            return None
        return (row[0], row[1])  # (blueprint_type_id, per_run_output)

    def materials(self, blueprint_type_id: int, activity: str = "manufacturing") -> list[tuple[int, int, int]]:
        return get_blueprint_materials(self._conn, blueprint_type_id, activity)

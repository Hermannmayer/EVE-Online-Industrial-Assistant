"""
蓝图数据访问层 — 统一蓝图查询接口。

替代多处分散的 SELECT FROM blueprint_materials 查询。
依赖 blueprint.db 中的 blueprint_materials 表。
"""

from __future__ import annotations

import sqlite3

from services.manufacturing_calculator import DEFAULT_WASTEFACTOR


def get_blueprint_wastefactor(
    conn: sqlite3.Connection,
    blueprint_type_id: int,
    activity: str = "manufacturing",
) -> int:
    """查询蓝图的材料 wastefactor。

    Args:
        conn: blueprint.db 的数据库连接
        blueprint_type_id: 蓝图 type_id
        activity: 活动类型（默认 'manufacturing'）

    Returns:
        wastefactor 值（T1=10）。SDE 无值时返回 DEFAULT_WASTEFACTOR（10）。
    """
    cur = conn.execute(
        """
        SELECT wastefactor FROM blueprint_materials
        WHERE blueprint_type_id = ? AND activity = ?
        LIMIT 1
        """,
        (blueprint_type_id, activity),
    )
    row = cur.fetchone()
    if row is None:
        return DEFAULT_WASTEFACTOR
    # wastefactor 可能是 None（旧数据无此列）
    val: int | None = row[0]
    return val if val is not None else DEFAULT_WASTEFACTOR


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

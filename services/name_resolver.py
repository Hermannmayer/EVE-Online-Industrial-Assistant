"""
统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。

解析优先级: terminology.item_overrides > item.zh_name > item.en_name > str(id)
"""

from __future__ import annotations

import sqlite3

from services.terminology import term


def resolve_item_name(conn: sqlite3.Connection, type_id: int) -> str:
    """统一物品名称解析：term override → item 表 → str(id)。

    Args:
        conn: reference.db 的数据库连接
        type_id: 物品 type_id

    Returns:
        物品名称（优先中文，其次英文，最后回退到字符串 id）
    """
    override = term.item_override(type_id)
    if override is not None:
        return override
    cur = conn.execute(
        "SELECT zh_name, en_name FROM item WHERE type_id = ?",
        (type_id,),
    )
    row = cur.fetchone()
    if row:
        name: str = row[0] or row[1]
        if name:
            return name
    return str(type_id)


def resolve_item_names_batch(
    conn: sqlite3.Connection,
    type_ids: list[int],
) -> dict[int, str]:
    """批量查询物品名称，减少数据库往返。

    Args:
        conn: reference.db 的连接
        type_ids: 需要查询的 type_id 列表

    Returns:
        {type_id: name, ...}
    """
    if not type_ids:
        return {}

    result: dict[int, str] = {}
    remaining: list[int] = []

    # 先查 terminology.json 覆盖
    for tid in type_ids:
        override = term.item_override(tid)
        if override is not None:
            result[tid] = override
        else:
            remaining.append(tid)

    if not remaining:
        return result

    # 剩下的查数据库
    placeholders = ",".join("?" * len(remaining))
    cur = conn.execute(
        f"SELECT type_id, zh_name, en_name FROM item WHERE type_id IN ({placeholders})",
        remaining,
    )
    for row in cur.fetchall():
        result[row[0]] = row[1] or row[2]
    # 未查到的用 str(id)
    for tid in remaining:
        if tid not in result:
            result[tid] = str(tid)
    return result


def mat_name(mat_id: int, conn: sqlite3.Connection) -> str:
    """查询材料名称，优先查 item 表，基础矿物走 terminology.json 覆盖。"""
    return resolve_item_name(conn, mat_id)

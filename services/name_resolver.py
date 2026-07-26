"""
统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。
从 core/eve_formulas.py 迁移至此，原位置保留 deprecated wrapper。

解析优先级: terminology.item_overrides > 矿物硬编码 > item.zh_name > item.en_name
"""

from __future__ import annotations

import sqlite3

from services.terminology import term

# ═══════════════════════════════════════════════════════
#  基础矿物 type_id → 中文名映射（type_id < 178，不在 item 表中）
# ═══════════════════════════════════════════════════════
_MINERAL_NAMES: dict[int, str] = {
    34: "三钛合金",
    35: "类银超金属",
    36: "同位聚合体",
    37: "超新星诺克石",
    38: "晶状石英核岩",
    39: "碳纤维",
    40: "建筑用预制块",
    4247: "****残余物",
    4312: "****残余物",
}


def resolve_item_name(conn: sqlite3.Connection, type_id: int) -> str:
    """统一物品名称解析：term override → 矿物硬编码 → item 表 → str(id)。

    Args:
        conn: reference.db 的数据库连接
        type_id: 物品 type_id

    Returns:
        物品名称（优先中文，其次英文，最后回退到字符串 id）
    """
    override = term.item_override(type_id)
    if override is not None:
        return override
    if type_id in _MINERAL_NAMES:
        return _MINERAL_NAMES[type_id]
    cur = conn.execute(
        "SELECT zh_name, en_name FROM item WHERE type_id = ?",
        (type_id,),
    )
    row = cur.fetchone()
    if row:
        name: str = row[0] or row[1]
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

    # 先从矿物硬编码中找
    result: dict[int, str] = {
        tid: _MINERAL_NAMES[tid]
        for tid in type_ids
        if tid in _MINERAL_NAMES
    }

    # 剩下的查数据库
    remaining = [tid for tid in type_ids if tid not in result]
    if not remaining:
        return result

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
    """查询材料名称，优先查 item 表，基础矿物用硬编码。"""
    return resolve_item_name(conn, mat_id)

"""
统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。

解析优先级: terminology.item_overrides > item.zh_name > item.en_name > str(id)
"""

from __future__ import annotations

import re
import sqlite3

from services.terminology import term


def search_item_type_id(conn: sqlite3.Connection, name: str) -> int | None:
    """名称→type_id：精确 → terminology 反向 → LIKE 模糊 → 引号归一化 LIKE。

    未命中返回 None。供剪贴板解析（库存修正/移库）使用。

    注意：基础矿物（type_id 34-40）不在 item 表，仅在 terminology.json 注册，
    因此 terminology 反向必须在 LIKE 之前，避免「三钛合金」被 LIKE 误匹配到
    「三钛合金条」等名称含子串的无关物品。
    """
    name = name.strip()
    if not name:
        return None
    # 1. 精确匹配
    row = conn.execute(
        "SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name, name)
    ).fetchone()
    if row:
        return int(row[0])
    # 2. terminology.item_overrides 反向（基础矿物 34-40 等不在 item 表）
    term._ensure()
    overrides = term._data.get("item_overrides") or {}
    for tid_str, override_name in overrides.items():
        if override_name == name:
            return int(tid_str)
    # 3. LIKE 模糊匹配
    like = f"%{name}%"
    row = conn.execute(
        "SELECT type_id FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1", (like, like)
    ).fetchone()
    if row:
        return int(row[0])
    # 4. 引号归一化（ASCII/弯引号 → % 通配）
    fuzzy = re.sub(r"[\"\"'']+", "%", name)
    if fuzzy != name:
        row = conn.execute(
            "SELECT type_id FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
            (f"%{fuzzy}%", f"%{fuzzy}%"),
        ).fetchone()
        if row:
            return int(row[0])
    return None


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


def resolve_system_name(conn: sqlite3.Connection, solar_system_id: int) -> str:
    """星系显示名：中文 (英文)。中文优先 terminology.system_names，fallback 英文 → str(id)。

    Args:
        conn: reference.db 的数据库连接
        solar_system_id: 星系 solar_system_id

    Returns:
        如 "吉他 (Jita)"；未注册中文且表无英文名时回退字符串 id。
    """
    row = conn.execute(
        "SELECT solar_system_name FROM solar_system WHERE solar_system_id = ?",
        (solar_system_id,),
    ).fetchone()
    en = row[0] if row and row[0] else ""
    zh = term.system_name(en) if en else None
    if zh:
        return f"{zh} ({en})"
    return en or str(solar_system_id)


def resolve_system_names_batch(
    conn: sqlite3.Connection,
    solar_system_ids: list[int],
) -> dict[int, str]:
    """批量查询星系显示名（中英对照），减少数据库往返。"""
    if not solar_system_ids:
        return {}
    placeholders = ",".join("?" * len(solar_system_ids))
    rows = conn.execute(
        f"SELECT solar_system_id, solar_system_name FROM solar_system"
        f" WHERE solar_system_id IN ({placeholders})",
        solar_system_ids,
    ).fetchall()
    result: dict[int, str] = {}
    for sid, en in rows:
        sid = int(sid)
        en = en or ""
        zh = term.system_name(en) if en else None
        result[sid] = f"{zh} ({en})" if zh else (en or str(sid))
    return result

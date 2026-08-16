"""生产计划类别推导 — 制造/拷贝/发明/反应。

production_plans 无 activity 字段（计划全为制造），类别从蓝图活动数据推导：
- reaction：蓝图有 activity='reaction' 行
- invention(T2/T3)：制造蓝图是 activity='invention' 的产物
- copying：蓝图有 activity='copying' 行
- manufacturing：其余

约定：conn 的 primary 库须含蓝图表（reference.db 或 blueprint.db）。
"""

from __future__ import annotations

from sqlite3 import Connection

CATEGORY_MANUFACTURING = "manufacturing"
CATEGORY_COPYING = "copying"
CATEGORY_INVENTION = "invention"
CATEGORY_REACTION = "reaction"

_SYMBOLS = {
    CATEGORY_MANUFACTURING: "⚙",
    CATEGORY_COPYING: "📋",
    CATEGORY_INVENTION: "💡",
    CATEGORY_REACTION: "⚗",
}


def category_symbol(cat: str) -> str:
    """类别符号（⚙📋💡⚗）。"""
    return _SYMBOLS.get(cat, "⚙")


def load_category_map(conn: Connection, blueprint_type_ids: list[int]) -> dict[int, str]:
    """蓝图 id → 类别。优先级：reaction → invention → copying → manufacturing。"""
    ids = [b for b in blueprint_type_ids if b]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    # 反应/拷贝：蓝图自身活动行
    act_rows = conn.execute(
        f"SELECT blueprint_type_id, activity FROM blueprint_activities "
        f"WHERE blueprint_type_id IN ({placeholders}) AND activity IN ('reaction','copying')",
        ids,
    ).fetchall()
    # 发明：蓝图是 invention 产物（T2/T3）
    inv_rows = conn.execute(
        f"SELECT product_type_id FROM blueprint_products "
        f"WHERE activity='invention' AND product_type_id IN ({placeholders})",
        ids,
    ).fetchall()
    inv_set = {r[0] for r in inv_rows}

    result: dict[int, str] = {}
    for b in ids:
        acts = {a for _b, a in act_rows if _b == b}
        if "reaction" in acts:
            result[b] = CATEGORY_REACTION
        elif b in inv_set:
            result[b] = CATEGORY_INVENTION
        elif "copying" in acts:
            result[b] = CATEGORY_COPYING
        else:
            result[b] = CATEGORY_MANUFACTURING
    return result

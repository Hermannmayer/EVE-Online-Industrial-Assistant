"""生产计划类别推导 — 制造/复制/发明/反应。

production_plans 无 activity 字段（计划全为制造作业），类别从蓝图活动数据推导，
描述的是**这张蓝图的用途性质**（对齐游戏工业窗口的作业类型）：
- reaction：蓝图有 activity='reaction' 行
- invention(T2/T3)：该蓝图是 activity='invention' 的产物
- copying：蓝图有 activity='copying' 行**且无 manufacturing 行**（只能复制、不能制造）
- manufacturing：其余（含 T1 与 T2/T3 的制造蓝图 —— T2 生产同样是制造作业）

⚠️ copying 判据必须排除 manufacturing：EVE 里几乎每个可制造蓝图都能复制，
只看 copying 会把普通制造蓝图误判成复制类（实测全库 3283 个 → 修正后 70 个）。

材料效率研究 / 生产效率研究不在类别内 —— 本应用只能建制造计划，无研究作业。

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
    # 反应/复制/制造：蓝图自身活动行。
    # 必须一并取 manufacturing —— copying 的判据是「能复制且不能制造」，
    # 而 EVE 里几乎每个可制造蓝图都能复制，只看 copying 会把普通制造蓝图误判成复制类。
    act_rows = conn.execute(
        f"SELECT blueprint_type_id, activity FROM blueprint_activities "
        f"WHERE blueprint_type_id IN ({placeholders}) "
        f"AND activity IN ('reaction','copying','manufacturing')",
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
        elif "copying" in acts and "manufacturing" not in acts:
            result[b] = CATEGORY_COPYING
        else:
            result[b] = CATEGORY_MANUFACTURING
    return result

"""行业弹窗专用数据查询收敛层。

把原先散落在 ui_pyside6/views/industry/*.py 中的
``get_container().db.connect(...)`` 直接 SQL 收敛到 services 层。

这些函数只接收 DatabaseManager（由 UI 从容器传入），保持同步调用，
不改变原有 UI 线程中的 DB 访问时机。
"""

from __future__ import annotations

from typing import Any

from services.plan_aggregator import (
    calculate_output_with_overflow,
    check_inventory,
    check_user_blueprints,
    collect_direct_materials,
    expand_blueprint_requirements,
    get_market_prices,
)
from services.plan_decompose import parent_needs
from services.plan_execution import find_available_blueprints

__all__ = [
    "get_blueprint_picker_data",
    "get_blueprint_requirements",
    "get_character_usage",
    "get_child_parallel_data",
    "get_item_name",
    "get_mass_parallel_data",
    "get_materials_summary",
    "get_max_group_number",
    "get_output_summary",
    "get_subitem_plans",
    "get_system_name",
    "set_plan_deposit_hangar",
]


def get_character_usage(db) -> list[tuple[Any, Any, Any]]:
    """按 char_name 统计活跃计划。"""
    with db.connect("user") as conn:
        rows = conn.execute(
            "SELECT char_name, COUNT(*) as cnt, "
            "GROUP_CONCAT(COALESCE(product_name, CAST(product_type_id TEXT)), ', ') as details "
            "FROM production_plans "
            "WHERE status IN ('pending', 'in_progress', 'running') "
            "GROUP BY char_name "
            "ORDER BY cnt DESC"
        ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]


def get_output_summary(db) -> list[dict[str, Any]] | None:
    """查询所有生产计划并计算产出价值与溢出；无计划时返回 None。"""
    with db.connect("user", "ref", "bp", "mkt") as conn:
        plan_rows = conn.execute(
            "SELECT id, product_type_id, product_name, runs, parallels, "
            "material_cost, profit, margin, market_margin, status, me_level "
            "FROM production_plans ORDER BY created_at DESC"
        ).fetchall()

        if not plan_rows:
            return None

        plans = [
            {
                "id": r[0],
                "product_type_id": r[1],
                "product_name": r[2],
                "runs": r[3] or 1,
                "parallels": r[4] or 1,
                "material_cost": r[5] or 0.0,
                "profit": r[6] or 0.0,
                "margin": r[7] or 0.0,
                "market_margin": r[8] or r[7] or 0.0,
                "status": r[9] or "pending",
                "me_level": r[10] or 0,
            }
            for r in plan_rows
        ]
        return calculate_output_with_overflow(conn, plans)


def get_blueprint_requirements(db) -> dict[str, Any]:
    """查询活跃计划、展开蓝图需求并对比库存。

    返回 dict:
    - status: "no_active" / "no_needed" / "ok"
    - needed: {blueprint_type_id: info}
    - bp_inv: {blueprint_type_id: inventory info}
    """
    with db.connect("user", "ref", "bp") as conn:
        active_plans = conn.execute(
            "SELECT id, product_type_id, product_name, runs, parallels, me_level "
            "FROM production_plans WHERE status IN ('pending','in_progress','running','ready')"
        ).fetchall()

        if not active_plans:
            return {"status": "no_active", "needed": {}, "bp_inv": {}}

        plans = [
            {
                "product_type_id": r[1],
                "product_name": r[2],
                "runs": r[3],
                "parallels": r[4],
                "me_level": r[5],
            }
            for r in active_plans
        ]
        needed = expand_blueprint_requirements(conn, plans)
        if not needed:
            return {"status": "no_needed", "needed": {}, "bp_inv": {}}
        bp_inv = check_user_blueprints(conn, set(needed.keys()))
        return {"status": "ok", "needed": needed, "bp_inv": bp_inv}


def get_blueprint_picker_data(db, product_type_id: int) -> tuple[int | None, list[dict[str, Any]]]:
    """查询产品对应的制造蓝图类型及其可用库存蓝图。"""
    with db.connect("user", "bp", "ref") as conn:
        row = conn.execute(
            "SELECT blueprint_type_id FROM bp.blueprint_products "
            "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (product_type_id,),
        ).fetchone()
        if not row:
            return None, []
        blueprint_type_id = int(row[0])
        return blueprint_type_id, find_available_blueprints(conn, blueprint_type_id)


def get_child_parallel_data(
    db,
    plans: list[dict],
    sub_plans: list[dict],
) -> tuple[dict[int, int], dict[int, int], dict[int, str]]:
    """子项并行弹窗初始化数据：母项需求 / 单轮产出 / 格式化时长。

    需求优先读子项行的 demand 列（v12 引用式全局合并需求，避免重复求和）；
    老库无该列时回退 parent_needs 按母项当前需求推导。
    """
    with db.connect("ref", "user", "bp") as conn:
        demand = _child_demand_from_rows(sub_plans, conn, plans)
        output_per_run: dict[int, int] = {}
        durations: dict[int, str] = {}
        for p in sub_plans:
            pid = int(p["product_type_id"])
            output_per_run[pid] = _query_blueprint_output(conn, pid)
            durations[pid] = _format_blueprint_duration(conn, p.get("blueprint_type_id"))
        return demand, output_per_run, durations


def get_mass_parallel_data(
    db,
    plans: list[dict],
    sub_plans: list[dict],
) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    """大规模并行弹窗初始化数据：母项需求 / 单轮产出 / 单线总时长秒。"""
    with db.connect("ref", "user", "bp") as conn:
        demand = _child_demand_from_rows(sub_plans, conn, plans)
        per_run: dict[int, int] = {}
        duration: dict[int, int] = {}
        for p in sub_plans:
            pid = int(p["product_type_id"])
            per_run[pid] = _query_blueprint_output(conn, pid)
            dur = _query_blueprint_duration_sec(conn, p.get("blueprint_type_id"))
            duration[pid] = dur * int(p.get("runs") or 1)
        return demand, per_run, duration


def _child_demand_from_rows(sub_plans: list[dict], conn, plans: list[dict]) -> dict[int, int]:
    """共享子项需求：优先读 v12 引用式 demand 列；老库按母项 parent_needs 推导。"""
    if sub_plans and all("demand" in p for p in sub_plans):
        return {int(p["product_type_id"]): int(p.get("demand") or 0) for p in sub_plans}
    return parent_needs(conn, plans)


def get_materials_summary(db) -> dict[str, Any] | None:
    """查询活跃计划 BOM、库存与市场价；无活跃计划时返回 None。"""
    with db.connect("user", "ref", "bp", "mkt") as conn:
        active_rows = conn.execute(
            "SELECT product_type_id, runs, parallels, me_level, group_number, sub_level "
            "FROM production_plans WHERE status IN ('pending','in_progress','running','ready')"
        ).fetchall()
        if not active_rows:
            return None

        plans = [
            {
                "product_type_id": r[0],
                "runs": r[1],
                "parallels": r[2],
                "me_level": r[3],
                "group_id": r[4],
                "child_level": r[5],
            }
            for r in active_rows
        ]
        materials = collect_direct_materials(conn, plans)
        if not materials:
            return {"materials": {}, "inventory": {}, "prices": {}}
        inventory = check_inventory(conn, set(materials.keys()))
        prices = get_market_prices(conn, set(materials.keys()))
        return {"materials": materials, "inventory": inventory, "prices": prices}


def get_max_group_number(db) -> int:
    """返回 production_plans 当前最大 group_number，无记录为 0。"""
    with db.connect("user") as conn:
        row = conn.execute("SELECT COALESCE(MAX(group_number),0) FROM production_plans").fetchone()
        return int(row[0]) if row else 0


def get_subitem_plans(db, group_number: int, deeper_than: int) -> list[dict[str, Any]]:
    """查询同组更深子项产线，按 sub_level DESC, id DESC。"""
    with db.connect("user") as conn:
        rows = conn.execute(
            "SELECT * FROM production_plans WHERE group_number=? AND sub_level>? ORDER BY sub_level DESC, id DESC",
            (group_number, deeper_than),
        ).fetchall()
        return [dict(r) for r in rows]


def get_item_name(db, type_id: int) -> str:
    """按旧 UI 语义查询 item 表名称：zh_name → en_name → str(type_id)。"""
    with db.connect("ref") as conn:
        row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id=?", (type_id,)).fetchone()
    return (row[0] or row[1] or str(type_id)) if row else str(type_id)


def get_system_name(db, solar_system_id: int) -> str:
    """查询星系显示名（中文 (英文)）。"""
    from services.name_resolver import resolve_system_name

    with db.connect("ref") as conn:
        return resolve_system_name(conn, solar_system_id)


def set_plan_deposit_hangar(db, plan_id: int, hangar_id: int | None) -> None:
    """更新计划的下线产出机库。"""
    with db.connect("user") as conn:
        conn.execute(
            "UPDATE production_plans SET deposit_hangar_id=? WHERE id=?",
            (hangar_id, plan_id),
        )


# ════════════════════════════════════════════════════════════════
#  内部查询辅助
# ════════════════════════════════════════════════════════════════


def _query_blueprint_output(conn, product_type_id: int) -> int:
    row = conn.execute(
        "SELECT quantity FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
        (product_type_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] else 1


def _query_blueprint_duration_sec(conn, blueprint_type_id) -> int:
    row = conn.execute(
        "SELECT time FROM blueprint_activities WHERE blueprint_type_id=? AND activity='manufacturing' LIMIT 1",
        (blueprint_type_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] else 0


def _format_blueprint_duration(conn, blueprint_type_id) -> str:
    secs = _query_blueprint_duration_sec(conn, blueprint_type_id)
    if not secs:
        return ""
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    return f"{days}d {hours}h" if days else f"{hours}h"

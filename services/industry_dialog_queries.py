"""行业弹窗专用数据查询收敛层。

把原先散落在 ui_pyside6/views/industry/*.py 中的
``get_container().db.connect(...)`` 直接 SQL 收敛到 services 层。

这些函数只接收 DatabaseManager（由 UI 从容器传入），保持同步调用，
不改变原有 UI 线程中的 DB 访问时机。
"""

from __future__ import annotations

from typing import Any

from services.blueprint_reader import get_blueprint_products
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


def get_output_summary(db) -> list[dict[str, Any]] | None:
    """查询所有生产计划并计算产出价值与溢出；无计划时返回 None。"""
    with db.connect("user", "ref", "bp", "mkt") as conn:
        plan_rows = conn.execute(
            "SELECT id, product_type_id, product_name, runs, parallels, "
            "material_cost, profit, margin, market_margin, status, me_level, sub_level "
            "FROM production_plans ORDER BY created_at DESC, id ASC"
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
                # 溢出判定要看「这件有没有子项产线真的去造」（见 calculate_output_with_overflow）
                "sub_level": r[11] or 0,
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
        # `activity` 必须取：科研行（拷贝/发明/研究）的 product_type_id 是**蓝图**，
        # 少了它 `is_science(None)` 会归一到制造 → 按「产物反查制造蓝图」查不到 →
        # 整行静默丢弃，发明/拷贝的前置蓝图在表里一个都不显示（2026-10-02 修）。
        # `id` 供拷贝行解析 `plan_blueprint_bindings` 的绑定 BPO。
        active_plans = conn.execute(
            "SELECT id, product_type_id, product_name, runs, parallels, me_level, activity "
            "FROM production_plans WHERE status IN ('pending','in_progress','running','ready')"
        ).fetchall()

        if not active_plans:
            return {"status": "no_active", "needed": {}, "bp_inv": {}}

        plans = [
            {
                "id": r[0],
                "product_type_id": r[1],
                "product_name": r[2],
                "runs": r[3],
                "parallels": r[4],
                "me_level": r[5],
                "activity": r[6],
            }
            for r in active_plans
        ]
        needed = expand_blueprint_requirements(conn, plans)
        if not needed:
            return {"status": "no_needed", "needed": {}, "bp_inv": {}}
        bp_inv = check_user_blueprints(conn, set(needed.keys()))
        return {"status": "ok", "needed": needed, "bp_inv": bp_inv}


def get_blueprint_picker_data(db, plan: dict) -> dict[str, Any]:
    """「绑定库存蓝图」弹窗的数据：该计划要绑的输入蓝图 + 库存里可选的行。

    目标蓝图按**活动**解析（`plan_aggregator.plan_input_blueprint_type_id`）：制造/反应按产物
    反查、拷贝/研究 = 被操作的那张 BPO、**发明 = 由产物那张 T2 反查出的 T1**（发明作业跑在
    T1 上）。以前无脑按 `product_type_id` 反查 `activity='manufacturing'` 的蓝图 —— 科研行的
    产物是蓝图、不是制造品，必然查不到，弹窗一片空白且不告诉用户到底缺哪张图（2026-10-06 报）。

    Returns:
        {"type_id": int | None,   # 要绑的输入蓝图；None = 蓝图库里没有对应配方行
         "name": str,             # 该蓝图显示名（解析不出时 ""）
         "is_blueprint": bool,    # False = 解析出的输入不是蓝图（T3 发明的输入是古遗物）
         "options": list[dict]}   # 库存可选蓝图，结构见 `plan_execution.find_available_blueprints`
    """
    from services.item_kind import blueprint_type_ids
    from services.plan_aggregator import _resolve_bp_name, plan_input_blueprint_type_id

    with db.connect("user", "bp", "ref") as conn:
        bp_tid = plan_input_blueprint_type_id(conn, plan)
        if not bp_tid:
            return {"type_id": None, "name": "", "is_blueprint": False, "options": []}
        bp_tid = int(bp_tid)
        return {
            "type_id": bp_tid,
            # `_resolve_bp_name` 与「所需蓝图清单」同一份取数（含「item 里没有就用产物名」回退），
            # 私有名跨模块复用有先例（plan_execution 也用 bom_expander._find_blueprint_for_product）
            "name": _resolve_bp_name(conn, bp_tid),
            "is_blueprint": bool(blueprint_type_ids(conn, [bp_tid])),
            "options": find_available_blueprints(conn, bp_tid),
        }


def get_child_parallel_data(
    db,
    plans: list[dict],
    sub_plans: list[dict],
) -> tuple[dict[int, int], dict[int, int], dict[int, str], dict[int, int]]:
    """子项并行弹窗初始化数据：母项需求 / 单轮产出 / 格式化时长 / 成品库存。

    需求优先读子项行的 demand 列（v12 引用式全局合并需求，避免重复求和）；
    老库无该列时回退 parent_needs 按母项当前需求推导。
    第三项之后多一个 `available`（子项成品在母项材料机库里的数量）—— 子项 runs 是
    **净口径**（`plan_rebuild.plan_net_runs`），弹窗不给库存就对不上账。
    """
    with db.connect("ref", "user", "bp") as conn:
        demand = _child_demand_from_rows(sub_plans, conn, plans)
        output_per_run: dict[int, int] = {}
        durations: dict[int, str] = {}
        for p in sub_plans:
            pid = int(p["product_type_id"])
            output_per_run[pid] = _query_blueprint_output(conn, pid)
            durations[pid] = _format_blueprint_duration(conn, p.get("blueprint_type_id"))
        return demand, output_per_run, durations, _child_available_stock(plans, sub_plans)


def get_mass_parallel_data(
    db,
    plans: list[dict],
    sub_plans: list[dict],
) -> tuple[dict[int, int], dict[int, int], dict[int, int], dict[int, int]]:
    """大规模并行弹窗初始化数据：母项需求 / 单轮产出 / 单线总时长秒 / 成品库存。

    第四项 `available` 与 `get_child_parallel_data` 同源（净口径排产要用）。
    """
    with db.connect("ref", "user", "bp") as conn:
        demand = _child_demand_from_rows(sub_plans, conn, plans)
        per_run: dict[int, int] = {}
        duration: dict[int, int] = {}
        for p in sub_plans:
            pid = int(p["product_type_id"])
            per_run[pid] = _query_blueprint_output(conn, pid)
            dur = _query_blueprint_duration_sec(conn, p.get("blueprint_type_id"))
            duration[pid] = dur * int(p.get("runs") or 1)
        return demand, per_run, duration, _child_available_stock(plans, sub_plans)


def _child_available_stock(plans: list[dict], sub_plans: list[dict]) -> dict[int, int]:
    """每个子项成品在**首个引用母项的制造机库**里的库存 {product_type_id: 数量}。

    口径与 `plan_rebuild._finalize_runs` 的 `stocks` 同源：按母项 `mat_hangar_id` 取那个机库的
    成品库存快照（不是原材料库存）。「首个引用母项」取 `source_mother_ids` 里 id 最小的一条
    （`rebuild_children` 按 `SELECT *` 顺序挑 `first_mother`，rowid 序即 id 序）；
    老行没有 `source_mother_ids` 就按组号找同组母项，再退回子项自己的 `mat_hangar_id`
    （建行时就是照抄母项那个）。
    """
    from services import inventory_manager

    mothers = {
        int(p["id"]): p for p in plans if p.get("id") and int(p.get("child_level") or p.get("sub_level") or 0) == 0
    }
    cache: dict[int, dict[int, int]] = {}
    out: dict[int, int] = {}
    for p in sub_plans:
        pid = int(p.get("product_type_id") or 0)
        hid = _first_mother_hangar(p, mothers, plans)
        if not hid:
            out[pid] = 0
            continue
        if hid not in cache:
            cache[hid] = inventory_manager.get_hangar_stock(hid)
        out[pid] = int(cache[hid].get(pid, 0))
    return out


def _first_mother_hangar(child: dict, mothers: dict[int, dict], plans: list[dict]) -> int | None:
    """子项对应的「首个引用母项」的材料机库 id（取不到返回 None）。"""
    sources = sorted(
        int(s) for s in str(child.get("source_mother_ids") or "").replace(" ", "").split(",") if s.isdigit()
    )
    for mid in sources:
        hid = (mothers.get(mid) or {}).get("mat_hangar_id")
        if hid:
            return int(hid)
    gid = child.get("group_id") or child.get("group_number")
    if gid:
        for m in plans:
            if int(m.get("child_level") or m.get("sub_level") or 0) != 0:
                continue
            if (m.get("group_id") or m.get("group_number")) == gid and m.get("mat_hangar_id"):
                return int(m["mat_hangar_id"])
    hid = child.get("mat_hangar_id")
    return int(hid) if hid else None


def _child_demand_from_rows(sub_plans: list[dict], conn, plans: list[dict]) -> dict[int, int]:
    """共享子项需求：优先读 v12 引用式 demand 列；老库按母项 parent_needs 推导。"""
    if sub_plans and all("demand" in p for p in sub_plans):
        return {int(p["product_type_id"]): int(p.get("demand") or 0) for p in sub_plans}
    return parent_needs(conn, plans)


def get_materials_summary(db) -> dict[str, Any] | None:
    """查询活跃计划 BOM、库存与市场价；无活跃计划时返回 None。

    `activity` / `blueprint_type_id` / `decryptor_type_id` 是**科研行取料**用的（同
    `load_active_plans_for_procurement`）：填料总表对科研行走
    `plan_execution.material_requirements`（数据核心 + 解码器按作业次数算），
    少了 `activity` 会被当成制造行按产物反查蓝图 —— 而科研行的产物是蓝图、查不到，
    整行静默消失（用户 2026-10-06 报）。
    """
    with db.connect("user", "ref", "bp", "mkt") as conn:
        active_rows = conn.execute(
            "SELECT product_type_id, runs, parallels, me_level, group_number, sub_level, "
            "activity, blueprint_type_id, decryptor_type_id "
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
                "activity": r[6],
                "blueprint_type_id": r[7],
                "decryptor_type_id": r[8],
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
    """单轮产出量（按产物取配方，缺省 1）。统一入口会排除 CCP 测试蓝图。"""
    row = get_blueprint_products(conn, product_type_id, "manufacturing")
    return int(row[1]) if row and row[1] else 1


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

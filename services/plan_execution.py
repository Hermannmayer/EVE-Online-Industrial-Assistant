"""
生产计划执行 — 倒计时 / 材料校验扣减 / 蓝图绑定占用消耗 / 完成入库

把「生产计划」从静态排产升级为可执行产线追踪：
  pending ──启动──▶ in_progress ──倒计时到期──▶ ready ──完成──▶ completed
  本模块只做纯逻辑与参数化 SQL，不依赖任何 UI；DB 经 get_container().db 访问。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from core.logger import log

# ════════════════════════════════════════════════════════════════
#  时间工具
# ════════════════════════════════════════════════════════════════

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _now_str() -> str:
    return datetime.now(UTC).strftime(_TIME_FMT)


def remaining_seconds(plan: dict, *, now: datetime | None = None) -> int | None:
    """倒计时剩余秒数。非进行中 / 无 started_at / 无时长 → None；已超时返回负值。

    now 可注入便于测试；started_at 以 naive UTC 解析（存储格式 "%Y-%m-%d %H:%M:%S"）。
    """
    if plan.get("status") not in ("in_progress", "running"):
        return None
    started = plan.get("started_at")
    duration = float(plan.get("calculated_time") or 0)
    if not started or duration <= 0:
        return None
    try:
        started_dt = datetime.strptime(started, _TIME_FMT)
    except (ValueError, TypeError):
        return None
    now_dt = now or datetime.now(UTC)
    if now_dt.tzinfo is not None:
        now_dt = now_dt.replace(tzinfo=None)
    return int((started_dt + timedelta(seconds=duration) - now_dt).total_seconds())


def expire_overdue_plans(db=None) -> int:
    """把已超时的进行中计划置为 ready（重启补算）。返回受影响行数。

    db: 可选注入的 DatabaseManager（便于测试）；None 时用 get_container().db。
    """
    db_mgr = db or _container().db
    now = datetime.now(UTC).replace(tzinfo=None)
    overdue: list[int] = []
    with db_mgr.connect("user") as conn:
        rows = conn.execute(
            "SELECT id, started_at, calculated_time FROM production_plans "
            "WHERE status IN ('in_progress','running') AND started_at IS NOT NULL"
        ).fetchall()
        for pid, started, dur in rows:
            try:
                started_dt = datetime.strptime(started, _TIME_FMT)
            except (ValueError, TypeError):
                continue
            if not dur or float(dur) <= 0:
                continue
            if (started_dt + timedelta(seconds=float(dur))) <= now:
                overdue.append(pid)
        updated = 0
        if overdue:
            ph = ",".join("?" for _ in overdue)
            cur = conn.execute(f"UPDATE production_plans SET status='ready' WHERE id IN ({ph})", overdue)
            updated = cur.rowcount
    return updated


# ════════════════════════════════════════════════════════════════
#  材料校验 / 扣减
# ════════════════════════════════════════════════════════════════


def material_requirements(plan: dict) -> list[dict]:
    """计算计划总材料需求 [{type_id, name, need}]。

    need = 每轮 ME 调整量 × runs × parallels，数据源为
    scoring_service.calculate_plan_metrics 返回的 materials（每轮量）。
    评分失败时返回空列表并记 log。
    """
    from services.char_config_resolver import resolve_char_config

    char_name = (plan.get("char_name") or "").strip()
    try:
        char_config = resolve_char_config(char_name=char_name) or {}
        metrics = _container().scoring_service().calculate_plan_metrics(plan, char_config)
    except Exception:
        log.exception("计算计划 %s 材料需求失败", plan.get("id"))
        return []
    runs = max(int(plan.get("runs", 1)), 1)
    parallels = max(int(plan.get("parallels", 1)), 1)
    total_mult = runs * parallels
    reqs = []
    for m in metrics.get("materials", []) or []:
        if not m.get("type_id"):
            continue
        reqs.append(
            {
                "type_id": int(m["type_id"]),
                "name": m.get("name", ""),
                "need": round((m.get("qty") or 0) * total_mult),
            }
        )
    return reqs


def check_materials(plan: dict, mat_hangar_id: int | None) -> list[dict]:
    """对照材料机库库存，返回 [{type_id, name, need, owned, missing}]。

    mat_hangar_id 为 None（未设置材料机库）时不校验，返回空列表。
    """
    if not mat_hangar_id:
        return []
    from services import inventory_manager

    reqs = material_requirements(plan)
    stock = inventory_manager.get_hangar_stock(mat_hangar_id)
    result = []
    for r in reqs:
        owned = int(stock.get(r["type_id"], 0))
        result.append({**r, "owned": owned, "missing": max(0, r["need"] - owned)})
    return result


def get_plans_for_mat_hangar(mat_hangar_id: int) -> list[dict]:
    """列出以该机库为材料机库的活跃计划（status NOT IN ('completed','done')）。

    供「材料覆盖率/缺口」视图聚合需求使用。
    """
    with _container().db.connect("user") as conn:
        cur = conn.execute(
            "SELECT * FROM production_plans WHERE mat_hangar_id = ? AND status NOT IN ('completed','done') ORDER BY id",
            (mat_hangar_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def aggregate_material_requirements(plans: list[dict], mat_hangar_id: int) -> list[dict]:
    """跨计划聚合材料需求：按 type_id 累加 need，对照材料机库库存算缺口。

    评分失败的计划跳过（material_requirements 已返回空）；名称统一用
    services.name_resolver.resolve_item_name 解析（terminology 覆盖优先）。

    Returns:
        [{type_id, name, need, owned, missing}]，按 need 降序。
    """
    from services import inventory_manager
    from services.name_resolver import resolve_item_name

    agg: dict[int, dict] = {}
    for plan in plans:
        for r in material_requirements(plan):
            tid = int(r["type_id"])
            entry = agg.setdefault(tid, {"type_id": tid, "need": 0})
            entry["need"] += int(r.get("need") or 0)
    if not agg:
        return []
    stock = inventory_manager.get_hangar_stock(mat_hangar_id)
    with _container().db.connect("ref") as conn:
        for entry in agg.values():
            tid = entry["type_id"]
            entry["name"] = resolve_item_name(conn, tid)
            owned = int(stock.get(tid, 0))
            entry["owned"] = owned
            entry["missing"] = max(0, entry["need"] - owned)
    return sorted(agg.values(), key=lambda e: e["need"], reverse=True)


def deduct_materials(plan: dict, mat_hangar_id: int) -> list[dict]:
    """从材料机库逐个扣减，返回 [{type_id, name, need, owned, deducted, missing}]。"""
    from services import inventory_manager

    stock = inventory_manager.get_hangar_stock(mat_hangar_id) if mat_hangar_id else {}
    result = []
    for r in material_requirements(plan):
        owned = int(stock.get(r["type_id"], 0))
        deducted = inventory_manager.deduct_item(mat_hangar_id, r["type_id"], r["need"])
        result.append({**r, "owned": owned, "deducted": deducted, "missing": max(0, r["need"] - owned)})
    return result


# ════════════════════════════════════════════════════════════════
#  启动
# ════════════════════════════════════════════════════════════════


def start_plan(
    plan: dict,
    *,
    mat_hangar_id: int | None,
    allow_short: bool = False,
    auto_bind: bool = True,
    char_name: str | None = None,
    facility: str | None = None,
) -> dict:
    """启动一条计划：校验 → 扣减材料 → 绑定蓝图 → 写 started_at/in_progress。

    char_name/facility: 可选，覆盖计划的人物/设施（产线启动小助手传入）。
    mat_hangar_id: 生效材料机库会写入 production_plans.mat_hangar_id，
    保证撤销时能按同一机库返还材料。

    Returns:
        {"ok": bool, "code": str, "message": str, "shortfalls": list, "plan_id": int}
    code 取值: already_started / already_completed / material_short / ok
    """
    from services import inventory_manager

    plan_id = plan.get("id")
    if not plan_id:
        return {"ok": False, "code": "no_id", "message": "计划无 id", "shortfalls": [], "plan_id": None}

    status = plan.get("status", "pending")
    if status in ("in_progress", "running"):
        return {
            "ok": False,
            "code": "already_started",
            "message": "计划已在生产中",
            "shortfalls": [],
            "plan_id": plan_id,
        }
    if status in ("completed", "done"):
        return {
            "ok": False,
            "code": "already_completed",
            "message": "计划已完成，请先重置为生产中",
            "shortfalls": [],
            "plan_id": plan_id,
        }

    # 1. 材料校验（mat_hangar_id 未设置则跳过）
    reqs: list[dict] = []
    shortfalls: list[dict] = []
    short_json = ""
    if mat_hangar_id:
        reqs = check_materials(plan, mat_hangar_id)
        shortfalls = [r for r in reqs if (r.get("missing") or 0) > 0]
        if shortfalls and not allow_short:
            return {
                "ok": False,
                "code": "material_short",
                "message": f"材料不足 {len(shortfalls)} 种",
                "shortfalls": shortfalls,
                "plan_id": plan_id,
            }
        if shortfalls:
            short_json = json.dumps({str(r["type_id"]): int(r["missing"]) for r in shortfalls}, ensure_ascii=False)

    # 2. 绑定蓝图：以 DB 权威值为准（传入的 plan dict 可能是绑定前的旧值）；
    #    未绑定时自动选最优（BPO 优先 → ME 最高的够用 BPC）
    assigned_bp = plan.get("assigned_blueprint_id")
    with _container().db.connect("user") as conn:
        cur = conn.execute("SELECT assigned_blueprint_id FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        db_assigned = cur[0] if cur else None
    auto_bound = False
    if db_assigned:
        assigned_bp = db_assigned
    if auto_bind and not assigned_bp:
        assigned_bp = _auto_bind_blueprint(plan)
        if assigned_bp:
            auto_bound = True

    # 3. 持久化：材料扣减 + 状态更新同一事务（任一步失败整体回滚，避免部分扣减残留）；
    #    生效 mat_hangar_id 一并落库，供撤销按同一机库返还
    now = _now_str()
    with _container().db.connect("user") as conn:
        if mat_hangar_id:
            for r in reqs:
                inventory_manager.deduct_item(mat_hangar_id, r["type_id"], r["need"], conn=conn)
        conn.execute(
            "UPDATE production_plans SET status='in_progress', started_at=?, "
            "assigned_blueprint_id=?, material_short=?, char_name=COALESCE(?, char_name), "
            "facility=COALESCE(?, facility), mat_hangar_id=COALESCE(?, mat_hangar_id) WHERE id=?",
            (now, assigned_bp, short_json, char_name, facility, mat_hangar_id, plan_id),
        )

    message = "计划已启动"
    if shortfalls:
        message += f"，材料缺口 {len(shortfalls)} 种已标记待补"
    if auto_bound:
        message += "，已自动绑定蓝图"
    return {"ok": True, "code": "ok", "message": message, "shortfalls": shortfalls, "plan_id": plan_id}


def start_plan_batch(
    plans: list[dict],
    *,
    mat_hangar_id: int | None,
    allow_short: bool = False,
    char_name: str | None = None,
    facility: str | None = None,
) -> dict:
    """批量启动（产线小助手/组）。逐条独立，单条失败不中断其余。"""
    results = []
    for plan in plans:
        res = start_plan(
            plan,
            mat_hangar_id=mat_hangar_id,
            allow_short=allow_short,
            char_name=char_name,
            facility=facility,
        )
        results.append({"plan": plan, **res})
    ok_count = sum(1 for r in results if r.get("ok"))
    return {"ok": ok_count == len(results), "ok_count": ok_count, "total": len(results), "results": results}


# ════════════════════════════════════════════════════════════════
#  完成
# ════════════════════════════════════════════════════════════════


def complete_plan(plan: dict, *, conn=None) -> dict:
    """ready/pending/in_progress → completed：入库成品 + 消耗绑定 BPC。

    conn: 可选注入的用户库连接（UI 已持有事务时传入）；None 时自开。
    成品入库 / BPC 消耗 / 状态更新在同一连接同一事务内完成，失败整体回滚；
    已 completed 的计划幂等返回（不重复入库）。
    Returns: {"ok": bool, "message": str, "deposited": int}
    """
    plan_id = plan.get("id")
    if not plan_id:
        return {"ok": False, "message": "计划无 id", "deposited": 0}
    from services import inventory_manager

    own_conn = conn is None
    if own_conn:
        conn = _container().db.direct_connect("user")
    messages: list[str] = []
    deposited = 0
    try:
        # 以 DB 权威值为准（调用方传入的 plan dict 可能是完成前的旧值）+ 幂等
        row = conn.execute(
            "SELECT status, product_type_id, deposit_hangar_id, runs, parallels, material_cost, "
            "assigned_blueprint_id FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "计划不存在", "deposited": 0}
        db_status, product_type_id, deposit_hangar_id, runs, parallels, mat_cost, assigned_bp = row
        if db_status in ("completed", "done"):
            return {"ok": True, "message": "计划已完成", "deposited": 0}

        # 1. 成品入库（同一连接同一事务）
        if deposit_hangar_id and product_type_id:
            total_mult = max(int(runs or 1), 1) * max(int(parallels or 1), 1)
            bp_conn = _container().db.direct_connect("bp")
            try:
                cur = bp_conn.execute(
                    "SELECT quantity FROM blueprint_products "
                    "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                    (product_type_id,),
                )
                row = cur.fetchone()
            finally:
                bp_conn.close()
            output_per_run = row[0] if row else 1
            total_qty = total_mult * output_per_run
            cost_price = (mat_cost or 0) / max(total_qty, 1)
            inventory_manager.add_item(deposit_hangar_id, product_type_id, total_qty, round(cost_price, 2), conn=conn)
            deposited = 1
            messages.append(f"成品 {total_qty} 件已入库")
        else:
            messages.append("未设置产出机库，跳过入库")

        # 2. 消耗绑定 BPC（runs × parallels 个制造任务）
        if assigned_bp:
            runs_used = max(int(runs or 1), 1) * max(int(parallels or 1), 1)
            res = consume_bpc_runs(conn, assigned_bp, runs_used)
            if res.get("deleted"):
                messages.append("绑定蓝图已耗尽并移除")
            elif not res.get("skipped"):
                messages.append(f"绑定蓝图剩余 {res.get('new_quantity')}×{res.get('new_runs')} 流程")

        # 3. 状态
        now = _now_str()
        conn.execute(
            "UPDATE production_plans SET status='completed', deposited=?, completed_at=?, "
            "assigned_blueprint_id=NULL WHERE id=?",
            (deposited, now, plan_id),
        )
        conn.commit()
    except Exception:
        log.exception("完成计划 %s 失败", plan_id)
        if own_conn:
            conn.rollback()
        return {"ok": False, "message": "完成失败，见日志", "deposited": 0}
    finally:
        if own_conn:
            conn.close()

    return {"ok": True, "message": "；".join(messages), "deposited": deposited}


def cancel_plan(plan: dict) -> dict:
    """撤销启动：in_progress → pending，并返还已扣减材料到材料机库。

    以 DB 权威值为准（调用方传入的 plan dict 可能是启动前的旧值）：
    返还机库取 production_plans.mat_hangar_id（start_plan 已持久化生效机库）；
    返还数量 = 需求 − 缺口（material_short 记录启动时的缺口，故 deducted = need − missing 精确还原）。
    返还按机库现有单位成本回补（避免加权平均成本被稀释）。
    返还 + 状态重置在同一事务内完成，失败整体回滚（避免重复撤销重复返还）。

    Returns: {"ok": bool, "message": str, "returned": int, "returned_list": list[dict]}
    """
    from services import inventory_manager

    plan_id = plan.get("id")
    if not plan_id:
        return {"ok": False, "message": "计划无 id", "returned": 0, "returned_list": []}

    # 权威值重读
    with _container().db.connect("user") as conn:
        row = conn.execute(
            "SELECT status, mat_hangar_id, material_short FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
    if row is None:
        return {"ok": False, "message": "计划不存在", "returned": 0, "returned_list": []}
    db_status, mat_hangar_id, material_short = row
    if db_status not in ("in_progress", "running"):
        return {"ok": False, "message": "仅生产中计划可撤销", "returned": 0, "returned_list": []}

    # 计算已扣减 = 需求 - 缺口（material_short JSON {type_id: missing_qty}）
    returned_list: list[dict] = []
    cost_map: dict[int, float] = {}
    if mat_hangar_id:
        reqs = material_requirements(plan)
        short: dict[int, int] = {}
        raw = material_short or ""
        if raw:
            try:
                short = {int(k): int(v) for k, v in json.loads(raw).items()}
            except Exception:
                short = {}
        # 机库现有单位成本（加权平均；返还时按原成本回补避免稀释）—— 读操作放在事务外
        for it in inventory_manager.get_items(mat_hangar_id):
            cost_map[it["type_id"]] = it.get("cost_price") or 0
        for r in reqs:
            tid = int(r["type_id"])
            missing = short.get(tid, 0)
            deducted = max(0, int(r["need"]) - missing)
            if deducted > 0:
                returned_list.append({"type_id": tid, "name": r.get("name", ""), "qty": deducted})

    # 返还材料 + 释放蓝图占用 + 重置状态（同一事务：失败整体回滚）
    with _container().db.connect("user") as conn:
        for r in returned_list:
            inventory_manager.add_item(mat_hangar_id, r["type_id"], r["qty"], cost_map.get(r["type_id"], 0), conn=conn)
        conn.execute(
            "UPDATE production_plans SET status='pending', started_at=NULL, material_short='', "
            "assigned_blueprint_id=NULL WHERE id=?",
            (plan_id,),
        )

    returned_total = sum(r["qty"] for r in returned_list)
    msg = "已撤销启动"
    if returned_total:
        msg += f"，返还 {returned_total} 件材料"
    elif not mat_hangar_id:
        msg += "（未设置材料机库，无材料返还）"
    return {"ok": True, "message": msg, "returned": returned_total, "returned_list": returned_list}


def reset_plan_for_reuse(plan_id: int) -> dict:
    """设为待生产：仅 completed 计划复用（不返还材料——材料已变为成品）。

    清除 started_at / completed_at / deposited / material_short 与蓝图占用，
    置回 pending 供再次启动。不触碰库存（成品已入库、材料不退回）。

    Returns: {"ok": bool, "message": str}
    """
    if not plan_id:
        return {"ok": False, "message": "计划无 id"}
    with _container().db.connect("user") as conn:
        row = conn.execute("SELECT status FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            return {"ok": False, "message": "计划不存在"}
        if row[0] not in ("completed", "done"):
            return {"ok": False, "message": "仅已完成计划可设为待生产"}
        conn.execute(
            "UPDATE production_plans SET status='pending', started_at=NULL, completed_at=NULL, "
            "deposited=0, material_short='', assigned_blueprint_id=NULL WHERE id=?",
            (plan_id,),
        )
    return {"ok": True, "message": "已重置为待生产"}


# ════════════════════════════════════════════════════════════════
#  蓝图绑定 / 占用 / 消耗
# ════════════════════════════════════════════════════════════════


def bind_blueprint(plan_id: int, blueprint_id: int) -> bool:
    """把库存蓝图绑定到计划。BPC 已被其他活跃计划占用时拒绝；BPO 可共享。"""
    if not plan_id:
        return False
    with _container().db.connect("user") as conn:
        row = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (blueprint_id,)).fetchone()
        if row is None:
            return False
        is_bpo = bool(row[0])
        if not is_bpo:
            cur = conn.execute(
                "SELECT COUNT(*) FROM production_plans "
                "WHERE assigned_blueprint_id=? AND id<>? AND status NOT IN ('completed','done')",
                (blueprint_id, plan_id),
            )
            if cur.fetchone()[0] > 0:
                return False
        conn.execute("UPDATE production_plans SET assigned_blueprint_id=? WHERE id=?", (blueprint_id, plan_id))
    return True


def release_blueprint(plan_id: int) -> bool:
    """计划取消/删除/回退时释放占用（清空 assigned_blueprint_id）。"""
    if not plan_id:
        return False
    with _container().db.connect("user") as conn:
        conn.execute("UPDATE production_plans SET assigned_blueprint_id=NULL WHERE id=?", (plan_id,))
    return True


def get_assigned_blueprint_id(plan_id: int) -> int | None:
    with _container().db.connect("user") as conn:
        row = conn.execute("SELECT assigned_blueprint_id FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        return row[0] if row else None


def get_occupied_blueprint_ids(db=None) -> set[int]:
    """返回被活跃计划（非 completed/done）占用的 user_blueprints.id 集合。"""
    db_mgr = db or _container().db
    with db_mgr.connect("user") as conn:
        rows = conn.execute(
            "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
            "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done')"
        ).fetchall()
    return {r[0] for r in rows}


def find_available_blueprints(conn, blueprint_type_id: int) -> list[dict]:
    """按蓝图类型列出库存蓝图（含占用标注/可用流程）。

    conn 需 ATTACH user/bp/ref。available_runs: BPO=INF，BPC=quantity×runs。
    """
    occupied = _occupied_ids(conn)
    rows = conn.execute(
        """
        SELECT ub.id, ub.hangar_id, ub.is_bpo, ub.me_level, ub.te_level,
               ub.runs, ub.quantity, ub.notes, h.name
        FROM user_blueprints ub
        LEFT JOIN hangars h ON ub.hangar_id = h.id
        WHERE ub.blueprint_type_id = ?
        ORDER BY ub.is_bpo DESC, ub.me_level DESC, ub.te_level DESC
        """,
        (blueprint_type_id,),
    ).fetchall()
    result = []
    for r in rows:
        is_bpo = bool(r[2])
        result.append(
            {
                "id": r[0],
                "hangar_id": r[1],
                "is_bpo": is_bpo,
                "me_level": r[3],
                "te_level": r[4],
                "runs": r[5],
                "quantity": r[6],
                "notes": r[7],
                "hangar_name": r[8] or "",
                "available_runs": float("inf") if is_bpo else int(r[6] or 0) * int(r[5] or 0),
                "occupied": r[0] in occupied,
            }
        )
    return result


def consume_bpc_runs(conn, bp_id: int, runs_used: int) -> dict:
    """完成时消耗 BPC 剩余流程；BPO 无操作。

    conn 需为 user 库连接（含事务）。返回 {"deleted", "new_quantity", "new_runs", "skipped"}。
    """
    row = conn.execute(
        "SELECT is_bpo, runs, quantity FROM user_blueprints WHERE id=?",
        (bp_id,),
    ).fetchone()
    if not row:
        return {"deleted": False, "new_quantity": 0, "new_runs": 0, "skipped": True}
    is_bpo, runs, quantity = row
    if is_bpo:
        return {"deleted": False, "new_quantity": quantity, "new_runs": runs, "skipped": True}
    new_q, new_runs = _split_bpc_consumption(int(quantity), int(runs), int(runs_used))
    if new_q <= 0 or new_runs is None:
        conn.execute("DELETE FROM user_blueprints WHERE id=?", (bp_id,))
        return {"deleted": True, "new_quantity": 0, "new_runs": 0, "skipped": False}
    conn.execute("UPDATE user_blueprints SET quantity=?, runs=? WHERE id=?", (new_q, new_runs, bp_id))
    return {"deleted": False, "new_quantity": new_q, "new_runs": new_runs, "skipped": False}


def _split_bpc_consumption(quantity: int, runs: int, used: int) -> tuple[int, int | None]:
    """纯函数：消耗 used 流程后返回应保留的 (数量, 每张剩余流程)。

    规则：整份消耗 copies=used//runs 张，余量再部分消耗 1 张；
    剩余总流程 ≤0 返回 (0, None)（调用方删行）；
    余量为 0 时保留整份张数；有余量时坍缩为单张（runs=剩余总数），保持 me/te 不变。
    """
    runs = max(int(runs), 1)
    quantity = max(int(quantity), 0)
    used = max(int(used), 0)
    total = quantity * runs
    if used >= total:
        return 0, None
    remaining = total - used
    full = remaining // runs
    rem = remaining % runs
    if rem == 0:
        return full, runs
    return 1, remaining


# ════════════════════════════════════════════════════════════════
#  内部工具
# ════════════════════════════════════════════════════════════════


def _container():
    from core.container import get_container

    return get_container()


def _occupied_ids(conn) -> set[int]:
    rows = conn.execute(
        "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
        "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done')"
    ).fetchall()
    return {r[0] for r in rows}


def _auto_bind_blueprint(plan: dict) -> int | None:
    """自动选最优库存蓝图：BPO 优先 → ME 最高的够用 BPC。返回 user_blueprints.id 或 None。"""
    product_type_id = plan.get("product_type_id")
    if not product_type_id:
        return None
    needs_runs = max(int(plan.get("runs", 1)), 1) * max(int(plan.get("parallels", 1)), 1)
    with _container().db.connect("user", "bp", "ref") as conn:
        cur = conn.execute(
            "SELECT blueprint_type_id FROM bp.blueprint_products "
            "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (product_type_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        options = find_available_blueprints(conn, row[0])
    if not options:
        return None
    for bp in options:
        if bp.get("is_bpo"):
            return int(bp["id"])
    capable = [bp for bp in options if not bp.get("occupied") and (bp.get("available_runs") or 0) >= needs_runs]
    if not capable:
        return None
    capable.sort(key=lambda b: (b.get("me_level", 0), b.get("te_level", 0)), reverse=True)
    return int(capable[0]["id"])

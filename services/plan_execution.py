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
            cur = conn.execute(
                f"UPDATE production_plans SET status='ready' WHERE id IN ({ph}) AND status IN ('in_progress','running')",
                overdue,
            )
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

    # 2. 绑定蓝图：以 DB 权威关联表绑定为准。一条产线一张蓝图：
    #    parallels 条产线需绑定 parallels 张、每张流程 ≥ runs。
    #    未绑定时仅并行=1 自动选最优（BPO 优先 → ME 最高的够用 BPC）并写入关联表；
    #    并行>1 未绑定 → 明确拒绝，引导用户在蓝图列勾选。
    plan_parallels = max(int(plan.get("parallels") or 1), 1)
    plan_runs = max(int(plan.get("runs") or 1), 1)
    binding = get_plan_binding_state(plan_id)
    bound_ids = binding["bound"]
    auto_bound = False
    if not bound_ids and auto_bind:
        # 自动选够并行所需张数（BPO 优先 → ME 最高的够用 BPC）；库存不足时仍绑已凑到的，
        # 由下方 _binding_shortfall 提示补绑。并行=1 且无可用蓝图 → 保持「不绑也能启动」宽松语义。
        picks = _auto_bind_blueprints(plan)
        if picks:
            bind_blueprints(plan_id, picks)
            bound_ids = picks
            auto_bound = True
    assigned_bp = None
    if bound_ids:
        with _container().db.connect("user") as conn:
            short = _binding_shortfall(conn, bound_ids, plan_parallels, plan_runs)
        if short:
            return {
                "ok": False,
                "code": "blueprint_short",
                "message": short,
                "shortfalls": [],
                "plan_id": plan_id,
            }
        assigned_bp = bound_ids[0]
    elif plan_parallels > 1:
        return {
            "ok": False,
            "code": "blueprint_short",
            "message": f"请先在蓝图列绑定 {plan_parallels} 张蓝图（并行 {plan_parallels} 条产线各需一张）",
            "shortfalls": [],
            "plan_id": plan_id,
        }

    # 3. 持久化：先用条件 UPDATE 原子抢占状态，再用同一事务扣减材料；
    #    任一步失败整体回滚，避免部分扣减残留和并发重复启动。
    now = _now_str()
    new_solar = inventory_manager.get_hangar_system_id(mat_hangar_id) if mat_hangar_id else None
    deducted_json = ""
    with _container().db.connect("user") as conn:
        cur = conn.execute(
            "UPDATE production_plans SET status='in_progress', started_at=?, "
            "assigned_blueprint_id=?, material_short=?, deducted_materials=?, "
            "char_name=COALESCE(?, char_name), facility=COALESCE(?, facility), "
            "mat_hangar_id=COALESCE(?, mat_hangar_id), solar_system_id=COALESCE(?, solar_system_id) "
            "WHERE id=? AND status NOT IN ('in_progress','running','completed','done')",
            (now, assigned_bp, short_json, deducted_json, char_name, facility, mat_hangar_id, new_solar, plan_id),
        )
        if cur.rowcount == 0:
            row = conn.execute("SELECT status FROM production_plans WHERE id=?", (plan_id,)).fetchone()
            status = row[0] if row else "missing"
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
            return {"ok": False, "code": "no_id", "message": "计划不存在", "shortfalls": [], "plan_id": plan_id}

        if mat_hangar_id:
            deducted_snapshot: dict[str, int] = {}
            for r in reqs:
                deducted = inventory_manager.deduct_item(mat_hangar_id, r["type_id"], r["need"], conn=conn)
                if deducted > 0:
                    deducted_snapshot[str(r["type_id"])] = deducted
            deducted_json = json.dumps(deducted_snapshot, ensure_ascii=False)
            conn.execute(
                "UPDATE production_plans SET deducted_materials=? WHERE id=?",
                (deducted_json, plan_id),
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


def output_per_run(product_type_id: int) -> int:
    """蓝图单流程产出量（查 blueprint_products，缺省 1）。"""
    try:
        bp_conn = _container().db.direct_connect("bp")
        try:
            row = bp_conn.execute(
                "SELECT quantity FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                (product_type_id,),
            ).fetchone()
            return int(row[0]) if row and row[0] else 1
        finally:
            bp_conn.close()
    except Exception:
        log.exception("查询产出量失败 type_id=%s", product_type_id)
        return 1


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

        # 0. 蓝图绑定校验：一条产线一张蓝图，每张流程 ≥ runs；不足拒绝完成（防 BPC 缺流程仍照常完成）
        plan_parallels = max(int(parallels or 1), 1)
        plan_runs = max(int(runs or 1), 1)
        bound_ids = get_plan_blueprints(plan_id)
        if not bound_ids and assigned_bp:
            bound_ids = [assigned_bp]
        if bound_ids:
            short = _binding_shortfall(conn, bound_ids, plan_parallels, plan_runs)
            if short:
                return {
                    "ok": False,
                    "message": f"蓝图绑定不满足完成条件：{short}。请先在蓝图列补绑蓝图后重试。",
                    "deposited": 0,
                }

        # 1. 原子抢占完成状态；若并发完成，只有一个事务能成功。
        now = _now_str()
        cur = conn.execute(
            "UPDATE production_plans SET status='completed', completed_at=?, deposited=0, "
            "assigned_blueprint_id=NULL, material_short='', deducted_materials='' "
            "WHERE id=? AND status NOT IN ('completed','done')",
            (now, plan_id),
        )
        if cur.rowcount == 0:
            return {"ok": True, "message": "计划已完成", "deposited": 0}

        # 2. 成品入库（同一连接同一事务；deposit_hangar_id 为 -1/None 表示「不自动入库」跳过）
        if deposit_hangar_id and deposit_hangar_id > 0 and product_type_id:
            total_mult = max(int(runs or 1), 1) * max(int(parallels or 1), 1)
            total_qty = total_mult * output_per_run(product_type_id)
            cost_price = (mat_cost or 0) / max(total_qty, 1)
            inventory_manager.add_item(deposit_hangar_id, product_type_id, total_qty, round(cost_price, 2), conn=conn)
            deposited = 1
            messages.append(f"成品 {total_qty} 件已入库")
        else:
            messages.append("未设置产出机库，跳过入库")

        # 3. 消耗绑定 BPC：一条产线一张蓝图，每张消耗该产线的 runs 流程；BPO 无限跳过。
        for bid in bound_ids:
            brow = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (bid,)).fetchone()
            if not brow:
                continue
            if brow[0]:
                messages.append("BPO 可无限次使用，跳过消耗")
                continue
            res = consume_bpc_runs(conn, bid, plan_runs)
            if res.get("skipped"):
                continue
            if res.get("deleted"):
                messages.append("绑定蓝图已耗尽并移除")
            else:
                messages.append(f"绑定蓝图剩余 {res.get('new_quantity')}×{res.get('new_runs')} 流程")

        # 完成：清理关联表绑定
        _clear_plan_bindings(conn, plan_id)

        # 4. 回写实际入库标记
        if deposited:
            conn.execute("UPDATE production_plans SET deposited=? WHERE id=?", (deposited, plan_id))

        if own_conn:
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
    返还数量 = start_plan 持久化的 deducted_materials 快照（精确还原），
    旧计划无快照时回退「需求 − 缺口」（material_short）推导。
    返还按机库现有单位成本回补（避免加权平均成本被稀释）。
    返还 + 状态重置在同一事务内完成，失败整体回滚（避免重复撤销重复返还）。

    Returns: {"ok": bool, "message": str, "returned": int, "returned_list": list[dict]}
    """
    from services import inventory_manager

    plan_id = plan.get("id")
    if not plan_id:
        return {"ok": False, "message": "计划无 id", "returned": 0, "returned_list": []}

    # 返还材料 + 释放蓝图占用 + 重置状态（同一事务：失败整体回滚）
    # 先读权威值并构造返还清单，再用条件 UPDATE 原子抢占撤销权，避免并发重复返还。
    returned_list: list[dict] = []
    cost_map: dict[int, float] = {}
    with _container().db.connect("user") as conn:
        row = conn.execute(
            "SELECT status, mat_hangar_id, material_short, deducted_materials FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "计划不存在", "returned": 0, "returned_list": []}
        db_status, mat_hangar_id, material_short, deducted_materials = row
        if db_status not in ("in_progress", "running"):
            return {"ok": False, "message": "仅生产中计划可撤销", "returned": 0, "returned_list": []}

        # 已扣减量优先取启动时持久化的快照（精确还原，不依赖评分重算——评分失败不再丢材料）；
        # 旧计划无快照 → 回退「需求 − 缺口」推导（material_short JSON {type_id: missing_qty}）
        if mat_hangar_id:
            # 机库现有单位成本（加权平均；返还时按原成本回补避免稀释）
            cost_map = inventory_manager.get_hangar_cost_map(mat_hangar_id)
            snapshot: dict[int, int] = {}
            raw_snapshot = deducted_materials or ""
            if raw_snapshot:
                try:
                    snapshot = {int(k): int(v) for k, v in json.loads(raw_snapshot).items()}
                except Exception:
                    snapshot = {}
            if snapshot:
                try:
                    from services.name_resolver import resolve_item_names_batch

                    with _container().db.connect("ref") as ref_conn:
                        names = resolve_item_names_batch(ref_conn, list(snapshot.keys()))
                except Exception:
                    names = {}  # 名称解析失败不阻断返还（name 仅用于返回列表展示）
                for tid, deducted in snapshot.items():
                    if deducted > 0:
                        returned_list.append({"type_id": tid, "name": names.get(tid, ""), "qty": deducted})
            else:
                reqs = material_requirements(plan)
                short: dict[int, int] = {}
                raw = material_short or ""
                if raw:
                    try:
                        short = {int(k): int(v) for k, v in json.loads(raw).items()}
                    except Exception:
                        short = {}
                for r in reqs:
                    tid = int(r["type_id"])
                    missing = short.get(tid, 0)
                    deducted = max(0, int(r["need"]) - missing)
                    if deducted > 0:
                        returned_list.append({"type_id": tid, "name": r.get("name", ""), "qty": deducted})

        cur = conn.execute(
            "UPDATE production_plans SET status='pending', started_at=NULL, material_short='', "
            "deducted_materials='', assigned_blueprint_id=NULL "
            "WHERE id=? AND status IN ('in_progress','running')",
            (plan_id,),
        )
        if cur.rowcount == 0:
            return {"ok": False, "message": "仅生产中计划可撤销", "returned": 0, "returned_list": []}

        for r in returned_list:
            inventory_manager.add_item(mat_hangar_id, r["type_id"], r["qty"], cost_map.get(r["type_id"], 0), conn=conn)
        _clear_plan_bindings(conn, plan_id)

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
            "deposited=0, material_short='', deducted_materials='', assigned_blueprint_id=NULL WHERE id=?",
            (plan_id,),
        )
        _clear_plan_bindings(conn, plan_id)
    return {"ok": True, "message": "已重置为待生产"}


# ════════════════════════════════════════════════════════════════
#  蓝图绑定 / 占用 / 消耗
# ════════════════════════════════════════════════════════════════


def bind_blueprint(plan_id: int, blueprint_id: int) -> bool:
    """把一张库存蓝图绑定到计划（单条产线）。BPC 已被其他活跃计划占用时拒绝；BPO 可共享。"""
    return bind_blueprints(plan_id, [blueprint_id])


def bind_blueprints(plan_id: int, blueprint_ids: list[int]) -> bool:
    """全量替换绑定：一条产线一张蓝图。

    勾选集即最终绑定集（先清空 plan_id 全部关联行再写入），避免换绑残留旧行：
    任一张仍是 UBP 的被其他活跃计划占用 → 拒绝整批（原绑定不动）。
    runs_used = 该计划 runs（每条产线串行轮数）；绑定成功后把首个蓝图镜像到单列
    assigned_blueprint_id（兼容旧单列口径消费方）。
    """
    if not plan_id:
        return False
    with _container().db.connect("user") as conn:
        prow = conn.execute(
            "SELECT COALESCE(runs,1), COALESCE(parallels,1) FROM production_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if prow is None:
            return False
        runs = max(int(prow[0]), 1)
        parallels = max(int(prow[1]), 1)
        if len(blueprint_ids) > parallels:
            log.warning("绑定蓝图 %d 张超过并行产线 %d 条（截断为前 %d 张）", len(blueprint_ids), parallels, parallels)
            blueprint_ids = blueprint_ids[:parallels]
        # 占用校验：任一张非 BPO 被其他活跃计划占用 → 整批拒绝
        for bp_id in blueprint_ids:
            row = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (bp_id,)).fetchone()
            if row is None or row[0]:
                continue  # 不存在的行或 BPO（BPO 可共享）
            cur = conn.execute(
                "SELECT COUNT(*) FROM plan_blueprint_bindings b "
                "JOIN production_plans pp ON pp.id=b.plan_id "
                "WHERE b.blueprint_id=? AND b.plan_id<>? AND pp.status NOT IN ('completed','done')",
                (bp_id, plan_id),
            )
            if cur.fetchone()[0] > 0:
                return False
        try:
            conn.execute("DELETE FROM plan_blueprint_bindings WHERE plan_id=?", (plan_id,))
        except Exception:
            log.debug("旧库无 plan_blueprint_bindings 表，跳过清空", exc_info=True)
        for bp_id in blueprint_ids:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO plan_blueprint_bindings (plan_id, blueprint_id, runs_used) VALUES (?,?,?)",
                    (plan_id, bp_id, runs),
                )
            except Exception:
                log.debug("写入关联表失败，跳过该张", exc_info=True)
        first = blueprint_ids[0] if blueprint_ids else None
        conn.execute("UPDATE production_plans SET assigned_blueprint_id=? WHERE id=?", (first, plan_id))
    return True


def bind_blueprints_many(bindings: list[tuple[int, list[int]]]) -> bool:
    """批量全量替换绑定多计划（一次连接/事务）。

    bindings: [(plan_id, [blueprint_id, ...]), ...]。被其他活跃计划占用的 BPC → 该计划整体跳过。
    """
    if not bindings:
        return False
    ok = True
    with _container().db.connect("user") as conn:
        for plan_id, bp_ids in bindings:
            if not plan_id or not bp_ids:
                ok = False
                continue
            prow = conn.execute(
                "SELECT COALESCE(runs,1), COALESCE(parallels,1) FROM production_plans WHERE id=?", (plan_id,)
            ).fetchone()
            if prow is None:
                ok = False
                continue
            runs = max(int(prow[0]), 1)
            parallels = max(int(prow[1]), 1)
            bp_ids = bp_ids[:parallels]
            bad = False
            for bp_id in bp_ids:
                brow = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (bp_id,)).fetchone()
                if brow is None or brow[0]:
                    continue
                cur = conn.execute(
                    "SELECT COUNT(*) FROM plan_blueprint_bindings b "
                    "JOIN production_plans pp ON pp.id=b.plan_id "
                    "WHERE b.blueprint_id=? AND b.plan_id<>? AND pp.status NOT IN ('completed','done')",
                    (bp_id, plan_id),
                )
                if cur.fetchone()[0] > 0:
                    bad = True
                    break
            if bad:
                ok = False
                continue
            try:
                conn.execute("DELETE FROM plan_blueprint_bindings WHERE plan_id=?", (plan_id,))
            except Exception:
                log.debug("旧库无关联表，跳过清空", exc_info=True)
            for bp_id in bp_ids:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO plan_blueprint_bindings (plan_id, blueprint_id, runs_used) VALUES (?,?,?)",
                        (plan_id, bp_id, runs),
                    )
                except Exception:
                    log.debug("写入关联表失败，跳过该张", exc_info=True)
            conn.execute("UPDATE production_plans SET assigned_blueprint_id=? WHERE id=?", (bp_ids[0], plan_id))
    return ok


def get_plan_binding_state(plan_id: int) -> dict:
    """返回计划蓝图绑定状态：bound(已绑张数清单)、need(需要的产线条数=parallels)、runs(每条产线流程)。

    供 UI（蓝图列差几张显示/选择弹窗）与启动校验共用；关联表缺失时回退旧单值列。
    """
    with _container().db.connect("user") as conn:
        prow = conn.execute(
            "SELECT COALESCE(runs,1), COALESCE(parallels,1) FROM production_plans WHERE id=?", (plan_id,)
        ).fetchone()
        runs = max(int(prow[0]), 1) if prow else 1
        parallels = max(int(prow[1]), 1) if prow else 1
        try:
            rows = conn.execute(
                "SELECT blueprint_id FROM plan_blueprint_bindings WHERE plan_id=? "
                # ORDER BY blueprint_id（表无自增 id 列，仅 (plan_id, blueprint_id) 复合主键）
                "ORDER BY blueprint_id",
                (plan_id,),
            ).fetchall()
            bound = [r[0] for r in rows]
        except Exception:
            log.debug("旧库无关联表，回退单值列", exc_info=True)
            row = conn.execute("SELECT assigned_blueprint_id FROM production_plans WHERE id=?", (plan_id,)).fetchone()
            bound = [row[0]] if row and row[0] else []
    return {"bound": bound, "need": parallels, "runs": runs}


def _bp_available_runs(conn, bp_id: int) -> int | float:
    """连接内查 BPC 可用流程 = quantity×runs；BPO 返回大数（视为无限）。"""
    row = conn.execute("SELECT is_bpo, runs, quantity FROM user_blueprints WHERE id=?", (bp_id,)).fetchone()
    if not row:
        return 0
    if row[0]:
        return 10**15
    return int(row[2] or 0) * int(row[1] or 0)


def _binding_shortfall(conn, bound_ids: list[int], parallels: int, runs: int) -> str | None:
    """校验绑定是否满足一条产线一张蓝图且每张流程≥runs；不足返回原因文本，满足返回 None。"""
    if len(bound_ids) < parallels:
        return f"绑定蓝图 {len(bound_ids)} 张不足 {parallels} 条产线（还差 {parallels - len(bound_ids)} 张）"
    for i, bid in enumerate(bound_ids, 1):
        if _bp_available_runs(conn, bid) < runs:
            return f"第 {i} 张绑定蓝图流程不足（需 ≥ {runs} 流程，当前产线每条要跑 {runs} 轮）"
    return None


def get_plan_blueprints(plan_id: int) -> list[int]:
    """返回计划绑定的库存蓝图 id 列表（关联表；无关联表时回退旧单值列）。"""
    with _container().db.connect("user") as conn:
        try:
            rows = conn.execute(
                "SELECT blueprint_id FROM plan_blueprint_bindings WHERE plan_id=?", (plan_id,)
            ).fetchall()
            if rows:
                return [r[0] for r in rows]
        except Exception:
            pass  # 旧库无关联表
        row = conn.execute("SELECT assigned_blueprint_id FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        return [row[0]] if row and row[0] else []


def _clear_plan_bindings(conn, plan_id: int) -> None:
    """清空计划的多蓝图绑定关联行（兼容旧库无关联表）。"""
    try:
        conn.execute("DELETE FROM plan_blueprint_bindings WHERE plan_id=?", (plan_id,))
    except Exception:
        pass


def release_blueprint(plan_id: int) -> bool:
    """计划取消/删除/回退时释放占用（清空关联表与旧单值列）。

    应用层模型：绑定不消耗流程，完成后才消耗——取消/回退只释放绑定、BPC 流程原样回到库存可再绑
    （与游戏"启动即扣流程"不同，提示文案需写明；已启动产线若确已在游戏中开造，须按游戏侧流程消耗为准）。
    """
    if not plan_id:
        return False
    with _container().db.connect("user") as conn:
        _clear_plan_bindings(conn, plan_id)
        conn.execute("UPDATE production_plans SET assigned_blueprint_id=NULL WHERE id=?", (plan_id,))
    return True


def get_assigned_blueprint_id(plan_id: int) -> int | None:
    with _container().db.connect("user") as conn:
        row = conn.execute("SELECT assigned_blueprint_id FROM production_plans WHERE id=?", (plan_id,)).fetchone()
        return row[0] if row else None


def get_occupied_blueprint_ids(db=None, *, exclude_plan_id: int | None = None) -> set[int]:
    """返回被活跃计划（非 completed/done）占用的 user_blueprints.id 集合。

    兼容多蓝图关联表（plan_blueprint_bindings）与旧单值列（assigned_blueprint_id）。
    exclude_plan_id: 传入计划 id 时排除其自身占用（查询本计划可选项时不把自己算作已占用）。
    """
    db_mgr = db or _container().db
    occupied: set[int] = set()
    with db_mgr.connect("user") as conn:
        try:
            if exclude_plan_id is not None:
                rows = conn.execute(
                    "SELECT DISTINCT b.blueprint_id FROM plan_blueprint_bindings b "
                    "JOIN production_plans pp ON pp.id=b.plan_id "
                    "WHERE pp.status NOT IN ('completed','done') AND b.plan_id<>?",
                    (exclude_plan_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT b.blueprint_id FROM plan_blueprint_bindings b "
                    "JOIN production_plans pp ON pp.id=b.plan_id "
                    "WHERE pp.status NOT IN ('completed','done')"
                ).fetchall()
            occupied = {r[0] for r in rows}
        except Exception:
            log.debug("旧库无 plan_blueprint_bindings 表，回退单值列", exc_info=True)
        if exclude_plan_id is not None:
            rows = conn.execute(
                "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
                "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done') AND id<>?",
                (exclude_plan_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
                "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done')"
            ).fetchall()
        occupied.update(r[0] for r in rows)
    return occupied


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
        return {"deleted": False, "new_quantity": 0, "new_runs": 0, "skipped": True, "consumed": 0}
    is_bpo, runs, quantity = row
    if is_bpo:
        return {"deleted": False, "new_quantity": quantity, "new_runs": runs, "skipped": True, "consumed": 0}
    old_total = int(quantity) * int(runs)
    new_q, new_runs = _split_bpc_consumption(int(quantity), int(runs), int(runs_used))
    if new_q <= 0 or new_runs is None:
        conn.execute("DELETE FROM user_blueprints WHERE id=?", (bp_id,))
        return {
            "deleted": True,
            "new_quantity": 0,
            "new_runs": 0,
            "skipped": False,
            "consumed": old_total,
        }
    conn.execute("UPDATE user_blueprints SET quantity=?, runs=? WHERE id=?", (new_q, new_runs, bp_id))
    return {
        "deleted": False,
        "new_quantity": new_q,
        "new_runs": new_runs,
        "skipped": False,
        "consumed": old_total - int(new_q) * int(new_runs or 0),
    }


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


def _occupied_ids(conn, *, exclude_plan_id: int | None = None) -> set[int]:
    """连接内查询占用蓝图 id 集合（兼容关联表与旧单值列）。"""
    occupied: set[int] = set()
    try:
        if exclude_plan_id is not None:
            rows = conn.execute(
                "SELECT DISTINCT b.blueprint_id FROM plan_blueprint_bindings b "
                "JOIN production_plans pp ON pp.id=b.plan_id "
                "WHERE pp.status NOT IN ('completed','done') AND b.plan_id<>?",
                (exclude_plan_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT b.blueprint_id FROM plan_blueprint_bindings b "
                "JOIN production_plans pp ON pp.id=b.plan_id "
                "WHERE pp.status NOT IN ('completed','done')"
            ).fetchall()
        occupied = {r[0] for r in rows}
    except Exception:
        log.debug("旧库无 plan_blueprint_bindings 表，回退单值列", exc_info=True)
    if exclude_plan_id is not None:
        rows = conn.execute(
            "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
            "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done') AND id<>?",
            (exclude_plan_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
            "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done')"
        ).fetchall()
    occupied.update(r[0] for r in rows)
    return occupied


def _auto_bind_blueprints(plan: dict) -> list[int]:
    """自动选最优库存蓝图：BPO 优先，其次 ME 最高的够用 BPC。返回并行产线所需张数清单。

    并行 parallels 条产线各需一张蓝图（每张流程 ≥ runs）；只选未被其他活跃计划占用的蓝图。
    库存不足时返回已凑到的张数，由调用方经 _binding_shortfall 提示补绑。
    """
    product_type_id = plan.get("product_type_id")
    if not product_type_id:
        return []
    runs = max(int(plan.get("runs", 1)), 1)
    parallels = max(int(plan.get("parallels", 1)), 1)
    with _container().db.connect("user", "bp", "ref") as conn:
        cur = conn.execute(
            "SELECT blueprint_type_id FROM bp.blueprint_products "
            "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (product_type_id,),
        )
        row = cur.fetchone()
        if not row:
            return []
        options = [o for o in find_available_blueprints(conn, row[0]) if not o.get("occupied")]
    if not options:
        return []
    picks: list[dict] = []
    # BPO 无限流程优先占用；一条产线一张
    for o in options:
        if o.get("is_bpo"):
            picks.append(o)
            if len(picks) >= parallels:
                break
    if len(picks) < parallels:
        capable = [o for o in options if not o.get("is_bpo") and (o.get("available_runs") or 0) >= runs]
        capable.sort(key=lambda b: (b.get("me_level", 0), b.get("te_level", 0)), reverse=True)
        for o in capable:
            picks.append(o)
            if len(picks) >= parallels:
                break
    return [int(o["id"]) for o in picks]


def ensure_plan_auto_bind(plan_id: int) -> bool:
    """计划尚无绑定且库存有可用蓝图时，自动绑定并行所需张数。返回是否新绑。

    供添加计划 / 重建子项后调用；已绑定或库存不足则不动。
    """
    if not plan_id or plan_id <= 0:
        return False
    if get_plan_binding_state(plan_id)["bound"]:
        return False
    with _container().db.connect("user") as conn:
        row = conn.execute(
            "SELECT product_type_id, runs, parallels FROM production_plans WHERE id=?", (plan_id,)
        ).fetchone()
    if not row:
        return False
    plan = {"product_type_id": row[0], "runs": row[1], "parallels": row[2]}
    picks = _auto_bind_blueprints(plan)
    if not picks:
        return False
    bind_blueprints(plan_id, picks)
    return True

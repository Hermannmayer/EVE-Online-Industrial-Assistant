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


def parse_cost_snapshot(raw: str | None) -> dict:
    """解析 `material_cost_snapshot` JSON → ``{"total": float | None, "unit": {type_id: 单价}}``。

    启动时写入的格式：
    ``{"total": <启动时材料总成本>, "unit": {"<type_id>": <扣减时加权平均单价>}}``。

    空串 / 非 JSON / 结构异常 → 返回 ``{}``，调用方据此回退旧口径 ——
    快照损坏不应阻断完成或撤销。
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("成本快照 JSON 解析失败，本次回退旧口径")
        return {}
    if not isinstance(data, dict):
        return {}
    unit: dict[int, float] = {}
    for k, v in (data.get("unit") or {}).items():
        try:
            unit[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    total = data.get("total")
    return {"total": float(total) if isinstance(total, int | float) else None, "unit": unit}


def _snapshot_total(raw: str | None) -> float | None:
    """快照里的材料总成本；无快照返回 None（调用方回退 material_cost）。"""
    return parse_cost_snapshot(raw).get("total")


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

    口径按活动分派（见 services.plan_job_kinds）：
      - 制造/反应：每轮量 × runs × parallels（现状不变）；
      - 科研作业：**直接用评分返回的量**——科研分支的 materials 已经按作业次数
        （发明=尝试次数、拷贝=总授权流程、研究=目标等级）算好了总量，
        再乘 runs×parallels 会重复放大。

    数据源为 scoring_service.calculate_plan_metrics 返回的 materials；失败返回空并记 log。
    """
    from services.char_config_resolver import resolve_char_config
    from services.plan_job_kinds import is_science

    char_name = (plan.get("char_name") or "").strip()
    try:
        char_config = resolve_char_config(char_name=char_name) or {}
        metrics = _container().scoring_service().calculate_plan_metrics(plan, char_config)
    except Exception:
        log.exception("计算计划 %s 材料需求失败", plan.get("id"))
        return []
    if is_science(plan.get("activity")):
        # 科研作业（拷贝/发明/研究）没有「并行产线」概念：需求量就是每轮量
        per_cycle = metrics.get("materials", []) or []
        per_cycle_mult = 1
    else:
        runs = max(int(plan.get("runs", 1)), 1)
        parallels = max(int(plan.get("parallels", 1)), 1)
        # 逐线时 metrics 带 `materials_all_lines`（Σ 各并行线的单轮量，按 type_id 合并）
        # → 只需再乘 runs。否则沿用「单线单轮量 × runs × parallels」。
        # 均匀绑定下两者逐值等价；逐线不同时必须走前者，否则会**多扣 parallels 倍**。
        all_lines = metrics.get("materials_all_lines")
        if all_lines is None:
            per_cycle = metrics.get("materials", []) or []
            per_cycle_mult = runs * parallels
        else:
            per_cycle = all_lines
            per_cycle_mult = runs
    reqs = []
    for m in per_cycle:
        if not m.get("type_id"):
            continue
        # `total_qty` = **整批取整**后的量（`domain.formulas.material_total_for_runs`），
        # 由评分链路按各自批次大小算好塞进来。缺失时才回退「单轮量 × 倍数」的旧口径 ——
        # 旧口径把 ME 减免逐轮取整后再乘轮数，对有基础量 ≥2 的材料会系统性多要货
        # （实测 22×2510 ME10：旧 50,200 / 新 49,698），正是「材料够了却报不足」的根因。
        total_qty = m.get("total_qty")
        need = total_qty if total_qty is not None else (m.get("qty") or 0) * per_cycle_mult
        reqs.append(
            {
                "type_id": int(m["type_id"]),
                "name": m.get("name", ""),
                "need": round(need),
            }
        )
    return reqs


def check_materials(
    plan: dict,
    mat_hangar_id: int | None,
    *,
    stock: dict[int, int] | None = None,
) -> list[dict]:
    """对照材料机库库存，返回 [{type_id, name, need, owned, missing}]。

    mat_hangar_id 为 None（未设置材料机库）时不校验，返回空列表。
    stock: 已取好的机库库存快照 {type_id: qty}；不传则自行查询。
      调用方（如产线小助手的 5s 轮询）可传同一份，避免每个计划重复查库。
    """
    if not mat_hangar_id:
        return []
    from services import inventory_manager

    reqs = material_requirements(plan)
    if stock is None:
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
    allow_bp_short: bool = False,
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
    bp_short_warn = ""
    if not bound_ids:
        # 严格规则（拷贝/研究要 BPO、发明要 BPC）**没绑输入蓝图根本开不了工** ——
        # 游戏里这类作业必须先指定输入蓝图。旧的「并行=1 不绑也能启动」宽松语义
        # 只留给制造/反应（它们可以靠「先启动、后勾蓝图」补救）。
        from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY, input_blueprint_rule

        with _container().db.connect("user") as conn:
            unbound_activity = _plan_activity(conn, plan_id, str(plan.get("activity") or ""))
        unbound_rule = input_blueprint_rule(unbound_activity)
        if unbound_rule in (RULE_BPO_ONLY, RULE_BPC_RUNS):
            return {
                "ok": False,
                "code": "blueprint_missing",
                "message": "未绑定输入蓝图：拷贝/研究必须指定一张蓝图原本（BPO）"
                if unbound_rule == RULE_BPO_ONLY
                else "未绑定输入蓝图：发明必须指定一张流程足够的蓝图拷贝（BPC）",
                "shortfalls": [],
                "plan_id": plan_id,
            }
    if bound_ids:
        with _container().db.connect("user") as conn:
            activity = _plan_activity(conn, plan_id, str(plan.get("activity") or ""))
            kind_violation = _blueprint_kind_violation(conn, activity, bound_ids)
            short = _binding_shortfall(conn, bound_ids, plan_parallels, plan_runs)
        if kind_violation:
            # 蓝图类型是**游戏规则**，不随 allow_bp_short 放行 —— 那不是库存不够，
            # 是游戏里根本做不到（拷贝/研究只能对 BPO，发明只能对 BPC）。
            return {
                "ok": False,
                "code": "blueprint_kind",
                "message": kind_violation,
                "shortfalls": [],
                "plan_id": plan_id,
            }
        if short and not allow_bp_short:
            return {
                "ok": False,
                "code": "blueprint_short",
                "message": short,
                "shortfalls": [],
                "plan_id": plan_id,
            }
        if short:
            # 强制启动：沿用**原有绑定**不换绑，流程按实际可用量消耗（完成时尽力扣，耗尽删行）。
            # 账面与游戏的偏差由用户在蓝图管理里做**全量剪贴板导入**矫正。
            bp_short_warn = f"⚠ 蓝图流程不足（{short}），已强制启动；账面流程数请用全量剪贴板导入矫正"
            log.warning("强制启动计划 %s：%s", plan_id, short)
        assigned_bp = bound_ids[0]
    elif plan_parallels > 1 and not allow_bp_short:
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
    # 启动单价快照必须在两个「之前」：
    #   ① 在 `deduct_item` 之前 —— 扣减把余量清到 0 时会删掉该物品行，扣完再取只能得到 0；
    #   ② 在事务**之外** —— `db.connect()` 在同一线程复用同一连接，嵌套 with 退出时会
    #      提前 `commit()`，把下面的状态 UPDATE 也一并提交掉，外层「失败整体回滚」就失效了。
    unit_costs = inventory_manager.get_hangar_cost_map(mat_hangar_id) if mat_hangar_id else {}
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
            cost_total = 0.0
            for r in reqs:
                deducted = inventory_manager.deduct_item(mat_hangar_id, r["type_id"], r["need"], conn=conn)
                if deducted > 0:
                    deducted_snapshot[str(r["type_id"])] = deducted
                    cost_total += float(unit_costs.get(int(r["type_id"]), 0.0)) * deducted
            deducted_json = json.dumps(deducted_snapshot, ensure_ascii=False)
            # 启动成本快照：入库/撤销按这一刻的真实成本，不被在产期间的价格重算改写
            cost_snapshot_json = json.dumps(
                {
                    "total": round(cost_total, 2),
                    "unit": {k: round(float(unit_costs.get(int(k), 0.0)), 4) for k in deducted_snapshot},
                },
                ensure_ascii=False,
            )
            conn.execute(
                "UPDATE production_plans SET deducted_materials=?, material_cost_snapshot=? WHERE id=?",
                (deducted_json, cost_snapshot_json, plan_id),
            )

    message = "计划已启动"
    if shortfalls:
        message += f"，材料缺口 {len(shortfalls)} 种已标记待补"
    if auto_bound:
        message += "，已自动绑定蓝图"
    if bp_short_warn:
        message += f"\n{bp_short_warn}"
    return {"ok": True, "code": "ok", "message": message, "shortfalls": shortfalls, "plan_id": plan_id}


# ── 部分启动：按产线条数拆分 ──────────────────────────────


def move_bindings(conn, from_plan_id: int, to_plan_id: int, blueprint_ids: list[int]) -> int:
    """把蓝图绑定关系从一条计划**挪到**另一条（不是复制）。

    不走 `bind_blueprints`：那条路径对「被其它活跃计划占用的非 BPO」整批拒绝，
    且只返回 False 不抛异常 —— 而余量行正是活跃计划，用它必然静默失败。
    必须「移动」而非「复制」：复制会让同一张 BPC 同时挂在两条活跃计划上，
    破坏「一张 BPC 只服务一条产线」的不变式，下线时会双倍消耗流程。
    """
    if not blueprint_ids:
        return 0  # `IN ()` 是语法错误，空集必须早退
    ph = ",".join("?" * len(blueprint_ids))
    cur = conn.execute(
        f"UPDATE plan_blueprint_bindings SET plan_id=? WHERE plan_id=? AND blueprint_id IN ({ph})",
        [to_plan_id, from_plan_id, *blueprint_ids],
    )
    return int(cur.rowcount)


def existing_blueprint_ids(conn, bp_ids: list[int]) -> set[int]:
    """过滤出确实存在于 `user_blueprints` 的绑定 id。

    逐线计算只认存在的蓝图（`plan_service._line_levels` 的 `b in bp_level`），
    切分绑定前必须用同一口径，否则悬空绑定会让「前 N 条」与实际参与计算的线错位。
    """
    if not bp_ids:
        return set()
    ph = ",".join("?" * len(bp_ids))
    return {int(r[0]) for r in conn.execute(f"SELECT id FROM user_blueprints WHERE id IN ({ph})", list(bp_ids))}


def _has_pending_children(conn, plan: dict) -> bool:
    """母项是否还有未完成子项（部分启动的守门条件）。"""
    gid = int(plan.get("group_number") or 0)
    if not gid:
        return False
    row = conn.execute(
        "SELECT COUNT(*) FROM production_plans WHERE group_number=? AND sub_level>0 "
        "AND status IN ('pending','in_progress','running')",
        (gid,),
    ).fetchone()
    return bool(row and row[0])


def preview_partial_start(plan_id: int, lines: int, mat_hangar_id: int | None) -> dict:
    """拆行前预览「只启动 N 条」的材料缺口与蓝图短板。

    **必须按 N 条口径算**：直接用计划字典会按整条线数报缺口，用户看到虚高的缺料，
    或在确认框里被不存在的阻塞拦下。这里把 `parallels` 与 `line_levels` 一起截到 N 条。
    """
    from services import plan_service

    fresh = plan_service.load_plan(plan_id)
    if not fresh:
        return {"ok": False, "code": "no_id", "message": "计划不存在", "shortfalls": [], "bp_short": None}
    total = max(int(fresh.get("parallels") or 1), 1)
    lines = max(min(int(lines), total - 1), 1) if total > 1 else 0
    preview = {**fresh, "parallels": lines, "line_levels": list(fresh.get("line_levels") or [])[:lines]}
    shortfalls = [r for r in check_materials(preview, mat_hangar_id) if (r.get("missing") or 0) > 0]

    conn = _container().db.direct_connect("user")
    try:
        bound = list(fresh.get("bound_blueprint_ids") or [])
        existing = existing_blueprint_ids(conn, bound)
        keep = [b for b in bound if b in existing][:lines]
        bp_short = _binding_shortfall(conn, keep, lines, max(int(fresh.get("runs") or 1), 1)) if lines else None
    finally:
        conn.close()
    return {"ok": True, "shortfalls": shortfalls, "bp_short": bp_short}


def _rollback_split(plan_id: int, rem_id: int, total: int, src: dict, moved: list[int]) -> None:
    """部分启动失败 → 把拆出的两行并回一条（**单事务**）。

    只在原行仍是 pending 时才动：`start_plan` 若已生效（正常路径不会），
    抹掉状态会丢真实数据。回滚只涉及绑定表 plan_id / 余量行 / parallels 三处 ——
    `started_at`、`deducted_materials` 等在失败路径上根本没被写过。
    """
    if not rem_id:
        return
    conn = _container().db.direct_connect("user")
    try:
        try:
            move_bindings(conn, rem_id, plan_id, moved)
            conn.execute("DELETE FROM production_plans WHERE id=? AND status='pending'", (rem_id,))
            conn.execute(
                "UPDATE production_plans SET parallels=?, assigned_blueprint_id=? WHERE id=? AND status='pending'",
                (total, src.get("assigned_blueprint_id"), plan_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("部分启动回滚失败 plan_id=%s remainder=%s", plan_id, rem_id)
    finally:
        conn.close()


def _no_other_active_mother(conn, plan_id: int, group_number: int) -> bool:
    """同组是否已没有别的活跃 level-0 行（本行刚置为 completed，自然不计入）。

    部分启动会把一条母项拆成「已启动 / 未启动」两半（同组两条 `sub_level=0`）。
    只清一次会让仍在跑的那半失去「子项制造价」的成本口径（见
    `services.plan_metrics.mother_subitem_cost_map`），故必须等两半都结束。
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM production_plans WHERE group_number=? AND sub_level=0 "
        "AND id<>? AND status NOT IN ('completed','done')",
        (group_number, plan_id),
    ).fetchone()
    return not (row and row[0])


def remove_completed_children(group_number: int, *, conn=None) -> int:
    """清理「已无归属」的已完成子项行，返回删除数（母项结束时调用）。

    「已无归属」的判据（**全局扫，不只按组**）：
    - 行有 `source_mother_ids` → 引用它的母项**全部**结束才删。跨组共享件靠这条兜住：
      它在 A 组、被 B 组的母项引用，B 最后结束时也能清到；只按组过滤会让它永远清不掉。
    - 行没有来源记录 → 只在 `group_number` 命中触发组时删（来源不明的行不跨组误伤）。

    conn: 传入时复用调用方事务且**不提交**（`complete_plan` 在它的写事务里调用）；
    None 时自开连接并提交（UI 的删母项路径用）。

    ⚠️ 绑定清理必须用**同一条 conn**：不得调 `release_blueprint` —— 后者自开一条缓存
    连接并独立提交，在 `complete_plan` 的未提交写事务内会卡满 `busy_timeout` 后抛
    `database is locked`（母项下线直接失败），且独立提交会破坏「清理与置 completed
    同生共死」的原子性。
    （`plan_rebuild.py` 那段「先 release 再 delete」的范式安全，是因为那里没有外层事务。）
    """

    def _do(c) -> int:
        rows = c.execute(
            "SELECT id, group_number, source_mother_ids FROM production_plans "
            "WHERE sub_level>0 AND status IN ('completed','done')"
        ).fetchall()
        if not rows:
            return 0
        active_mothers = {
            int(r[0])
            for r in c.execute(
                "SELECT id FROM production_plans WHERE sub_level=0 AND status NOT IN ('completed','done')"
            ).fetchall()
        }
        to_delete: list[int] = []
        for pid, gnum, raw in rows:
            sources = {int(x) for x in str(raw or "").split(",") if x.strip().isdigit()}
            if sources:
                if sources & active_mothers:
                    continue  # 还有母项在用它 → 留着
            elif int(gnum or 0) != int(group_number):
                continue  # 无来源记录：只在触发组内清
            to_delete.append(int(pid))
        if not to_delete:
            return 0
        for pid in to_delete:
            _clear_plan_bindings(c, pid)
        ph = ",".join("?" * len(to_delete))
        return int(c.execute(f"DELETE FROM production_plans WHERE id IN ({ph})", to_delete).rowcount)

    if conn is not None:
        return _do(conn)
    with _container().db.connect("user") as c:
        return _do(c)


def start_plan_partial(
    plan_id: int,
    lines: int,
    *,
    mat_hangar_id: int | None,
    char_name: str | None = None,
    facility: str | None = None,
    allow_short: bool = False,
    allow_bp_short: bool = False,
) -> dict:
    """部分启动：把计划拆成「已启动 lines 条」+「未启动 P−lines 条」两行，并启动前者。

    **时序必须是先拆行、后启动**：`complete_plan` 按每条绑定消耗该计划 `runs` 轮流程，
    若先启动再切走多余绑定、中途异常，就会留下「parallels=N 却挂 P 张绑定」的行，
    下线时超扣流程。先拆的最坏结果只是两条 pending 行，且有 `_rollback_split` 兜底。

    仅供**独立计划**与**子项全部完成的母项**使用（子项行由母项需求驱动，拆了会被重放改写）。

    Returns: {"ok", "code", "message", "started_lines", "remainder_plan_id", ...}
    """
    repo = _container().plan_repo
    src = repo.get_by_id(plan_id)
    if not src:
        return {"ok": False, "code": "no_id", "message": "计划不存在", "started_lines": 0}
    total = max(int(src.get("parallels") or 1), 1)
    status = str(src.get("status") or "").lower()
    if status != "pending":
        return {"ok": False, "code": "not_pending", "message": "只有待生产计划可以部分启动", "started_lines": 0}
    if int(src.get("sub_level") or 0) != 0:
        return {
            "ok": False,
            "code": "child_row",
            "message": "子项产线由母项需求驱动，不支持部分启动",
            "started_lines": 0,
        }
    try:
        lines = int(lines)
    except (TypeError, ValueError):
        lines = 0
    if not 1 <= lines < total:
        return {"ok": False, "code": "bad_lines", "message": f"启动条数需在 1..{total - 1} 之间", "started_lines": 0}

    gate = _container().db.direct_connect("user")
    try:
        if _has_pending_children(gate, src):
            return {
                "ok": False,
                "code": "children_pending",
                "message": "母项还有未完成子项，暂不能启动",
                "started_lines": 0,
            }
    finally:
        gate.close()

    bound = list(get_plan_binding_state(plan_id).get("bound") or [])
    remainder_lines = total - lines

    conn = _container().db.direct_connect("user")
    try:
        existing = existing_blueprint_ids(conn, bound)
        keep = [b for b in bound if b in existing][:lines]
        keep_set = set(keep)
        moved = [b for b in bound if b not in keep_set]
        first_kept = keep[0] if keep else src.get("assigned_blueprint_id")
        try:
            conn.execute(
                "UPDATE production_plans SET parallels=?, assigned_blueprint_id=? WHERE id=?",
                (lines, first_kept, plan_id),
            )
            rem_id = repo.insert_split_remainder(
                plan_id,
                parallels=remainder_lines,
                assigned_blueprint_id=(moved[0] if moved else None),
                conn=conn,
            )
            move_bindings(conn, plan_id, rem_id, moved)
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("部分启动拆分失败 plan_id=%s", plan_id)
            return {"ok": False, "code": "split_failed", "message": "拆分计划失败，见日志", "started_lines": 0}
    finally:
        conn.close()

    # ⚠️ 拆行事务必须已提交才取数：`_fetch_rows` 走 `connect("user","bp")`，
    # 与上面那个连接不是同一个 cache key，未提交时只会读到旧的 P 条绑定 → 按 P 条扣料。
    from services import plan_service

    fresh = plan_service.load_plan(plan_id)
    if not fresh:
        _rollback_split(plan_id, rem_id, total, src, moved)
        return {"ok": False, "code": "no_id", "message": "拆分后计划丢失", "started_lines": 0}

    try:
        res = start_plan(
            fresh,
            mat_hangar_id=mat_hangar_id,
            char_name=char_name,
            facility=facility,
            allow_short=allow_short,
            allow_bp_short=allow_bp_short,
            # 见本函数 docstring：自动绑定走自己的连接**立即提交**，是拆行事务之外的
            # 副作用，回滚看不见它 —— 关掉后无绑定的情形会干净失败。
            auto_bind=False,
        )
    except Exception:
        log.exception("部分启动失败 plan_id=%s", plan_id)
        res = {"ok": False, "code": "error", "message": "启动失败，见日志"}

    if not res.get("ok"):
        _rollback_split(plan_id, rem_id, total, src, moved)
        out = dict(res)
        out["started_lines"] = 0
        out.setdefault("message", "启动失败")
        return out

    out = dict(res)
    out["started_lines"] = lines
    out["remainder_plan_id"] = rem_id
    detail = str(res.get("message") or "").strip("；")
    out["message"] = f"已启动 {lines} 条，剩余 {remainder_lines} 条待生产" + (f"；{detail}" if detail else "")
    return out


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


def _deposit_research_output(
    conn,
    *,
    plan_id: int,
    activity: str,
    product_type_id: int | None,
    deposit_hangar_id: int | None,
    runs: int,
    parallels: int,
    actual_output_runs: int | None,
    actual_bpc_count: int | None = None,
    decryptor_type_id: int | None,
    messages: list[str],
) -> int:
    """把科研作业的产出（BPC）写入 user_blueprints。返回 1=有入库，0=跳过。

    - 拷贝：产出 parallels 份 BPC，每份 runs 流程；ME/TE 继承输入原图（游戏口径）。
    - 发明：产出 **成功产线数** 份 T2 BPC，每份流程数 = `actual_output_runs ÷ 张数`
      （NULL=未回填不写；0=失败不产出），ME/TE 由解码器决定（见 domain.research）。

    同机库 + 同蓝图 + 同 ME/TE + 同 runs 的已有 BPC → 累加 quantity，不新增行。
    """
    from domain.research import get_decryptor, invention_output_me_te
    from services import inventory_manager

    if not product_type_id:
        messages.append("计划无产物 type_id，跳过产出蓝图入库")
        return 0
    if not deposit_hangar_id or deposit_hangar_id <= 0:
        messages.append("未设置产出机库，跳过产出蓝图入库")
        return 0

    if activity == "invention":
        if actual_output_runs is None:
            messages.append("发明未回填实际产出，跳过入库")
            return 0
        if actual_output_runs <= 0:
            messages.append("发明失败，无产出蓝图入库")
            return 0
        out_runs = int(actual_output_runs)
        me, te = invention_output_me_te(get_decryptor(decryptor_type_id))
        # 成功几条产线就产几张 BPC（每张 out_runs 流程）。未传张数时退化为 1 张，
        # 兼容旧调用方（它们只给总流程数）。
        out_qty = max(1, int(actual_bpc_count or 1))
    else:  # copying
        out_runs = max(1, int(runs))
        me, te = _input_blueprint_me_te(conn, plan_id)
        out_qty = max(1, int(parallels))

    existing = conn.execute(
        "SELECT id, quantity FROM user_blueprints "
        "WHERE hangar_id=? AND blueprint_type_id=? AND is_bpo=0 AND me_level=? AND te_level=? "
        "AND runs=? AND COALESCE(notes,'')='' LIMIT 1",
        (deposit_hangar_id, product_type_id, me, te, out_runs),
    ).fetchone()
    specs = f"{out_qty} 份 × {out_runs} 流程，ME{me}/TE{te}"
    if existing:
        conn.execute("UPDATE user_blueprints SET quantity = quantity + ? WHERE id=?", (out_qty, existing[0]))
        messages.append(f"产出蓝图已并入库存同规格 BPC（{specs}）")
    else:
        inventory_manager.add_blueprint(
            deposit_hangar_id,
            product_type_id,
            is_bpo=False,
            me_level=me,
            te_level=te,
            runs=out_runs,
            quantity=out_qty,
            conn=conn,
        )
        messages.append(f"产出蓝图已入库（{specs}）")
    return 1


def _improve_bound_bpo_level(
    conn,
    *,
    plan_id: int,
    activity: str,
    target_level: int,
    messages: list[str],
) -> int:
    """ME/TE 研究完成：把绑定**蓝图原本**的等级提到目标等级（只升不降）。返回 1=改了。

    游戏规则（`docs/eve_wiki_knowledge_base.md`「材料效率研究」「时间效率研究」）：
    研究只能作用于蓝图原本（BPO）—— 基于蓝图拷贝不能再研究；作用对象是原本本身，
    上限 ME 10 / TE 20（`create_research_plan` 侧已夹紧）。

    以前这条分支缺失（`OUTPUT_IMPROVED_BPO` 零消费方），研究行会掉进「普通成品入库」
    分支，把蓝图当物品塞进 `inventory_items`：等级不提升、还多出幻影库存。
    """
    from services.plan_job_kinds import ACTIVITY_RESEARCH_ME, ACTIVITY_RESEARCH_TE

    # 列名不能进 f-string 拼 SQL（CLAUDE.md 代码规则），写成字面量三件套
    sql = {
        ACTIVITY_RESEARCH_ME: (
            "ME",
            "SELECT is_bpo, me_level FROM user_blueprints WHERE id=?",
            "UPDATE user_blueprints SET me_level=? WHERE id=?",
        ),
        ACTIVITY_RESEARCH_TE: (
            "TE",
            "SELECT is_bpo, te_level FROM user_blueprints WHERE id=?",
            "UPDATE user_blueprints SET te_level=? WHERE id=?",
        ),
    }.get(activity)
    if sql is None:
        return 0
    label, select_sql, update_sql = sql

    bound = get_plan_blueprints(plan_id)
    if not bound:
        messages.append("研究计划未绑定蓝图原本，跳过等级提升")
        return 0
    target = max(0, int(target_level or 0))
    if target <= 0:
        messages.append("研究计划没记目标等级，跳过等级提升（可在编辑计划里补上）")
        return 0

    changed = 0
    for blueprint_id in bound:
        row = conn.execute(select_sql, (blueprint_id,)).fetchone()
        if row is None or not bool(row[0]):
            messages.append("绑定的不是蓝图原本，等级不生效（游戏规则：拷贝不能再研究）")
            continue
        current = int(row[1] or 0)
        if current >= target:
            messages.append(f"蓝图原本 {label} 已是 {current} 级，无需提升（目标 {target}）")
            continue
        conn.execute(update_sql, (target, blueprint_id))
        messages.append(f"蓝图原本 {label} {current} → {target}")
        changed = 1
    return changed


def _input_blueprint_me_te(conn, plan_id: int) -> tuple[int, int]:
    """取计划绑定输入蓝图的 ME/TE（拷贝产出的 BPC 继承原图等级）。缺失 → (0, 0)。"""
    row = conn.execute(
        "SELECT ub.me_level, ub.te_level FROM user_blueprints ub "
        "JOIN plan_blueprint_bindings b ON b.blueprint_id = ub.id "
        "WHERE b.plan_id = ? ORDER BY b.blueprint_id LIMIT 1",
        (plan_id,),
    ).fetchone()
    if row is None:
        return (0, 0)
    return (int(row[0] or 0), int(row[1] or 0))


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


def _plan_activity(conn, plan_id: int, fallback: str = "") -> str:
    """计划的活动类型，**以库为准**。

    调用方可能只传 `{"id": …}`（部分启动、批量路径就是这样），拿不到 activity 就会让
    蓝图类型规则静默失效 —— 游戏规则不能取决于入参完整度。
    """
    row = conn.execute("SELECT COALESCE(activity,'') FROM production_plans WHERE id=?", (plan_id,)).fetchone()
    return str(row[0]) if row and row[0] else fallback


def _blueprint_kind_violation(conn, activity: str, bound_ids: list[int]) -> str:
    """绑定蓝图与活动规则不符时返回可读原因；合规 → 空串。

    游戏规则（`docs/eve_wiki_knowledge_base.md`「拷贝」）：
      - 拷贝 / 研究 → 必须绑**蓝图原本（BPO）**：基于蓝图拷贝不能再拷贝、也不能再研究；
      - 发明       → 必须绑**蓝图拷贝（BPC）**：发明只吃拷贝（BPO 不可用于发明）。
    规则表见 `services.plan_job_kinds.INPUT_BLUEPRINT_RULE`。
    """
    from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY, input_blueprint_rule

    rule = input_blueprint_rule(activity)
    if rule not in (RULE_BPO_ONLY, RULE_BPC_RUNS):
        return ""
    want_bpo = rule == RULE_BPO_ONLY
    for bid in bound_ids:
        row = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (bid,)).fetchone()
        if row is None:
            continue
        is_bpo = bool(row[0])
        if want_bpo and not is_bpo:
            return "选的是蓝图拷贝（BPC）：拷贝不能再拷贝、也不能再研究，请改用蓝图原本（BPO）"
        if not want_bpo and is_bpo:
            return "选的是蓝图原本（BPO）：发明只能用蓝图拷贝（BPC），请先拷贝出 BPC"
    return ""


def plan_blueprint_ready(plan: dict) -> bool:
    """该计划的输入蓝图是否已就绪（按活动规则判定，取代旧的 has_image 口径）。

    规则见 services.plan_job_kinds：
      - 制造/反应：BPO，或流程够本计划跑的 BPC（现状语义，绑定过即算就绪）；
      - 拷贝/研究：必须是 BPO；
      - 发明：必须是 BPC，且剩余流程 ≥ 本计划要跑的流程。

    绑定集合优先取关联表（get_plan_blueprints），回退单值列。
    """
    from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY, input_blueprint_rule

    rule = input_blueprint_rule(plan.get("activity"))
    plan_id = plan.get("id")
    bound: list[int] = []
    if plan_id:
        try:
            bound = get_plan_blueprints(int(plan_id))
        except Exception:
            log.debug("读取计划 %s 蓝图绑定失败", plan_id, exc_info=True)
    if not bound and plan.get("assigned_blueprint_id"):
        bound = [int(plan["assigned_blueprint_id"])]
    if not bound:
        # 尚未绑定：只有「制造/反应 且 并行=1」沿用旧的「不绑也能启动」宽松语义
        return rule not in (RULE_BPO_ONLY, RULE_BPC_RUNS)

    runs = max(int(plan.get("runs") or 1), 1)
    parallels = max(int(plan.get("parallels") or 1), 1)
    capacity = 0
    try:
        with _container().db.connect("user") as conn:
            # 类型规则与 `start_plan` 共用同一个函数，避免两处规则漂移
            if _blueprint_kind_violation(conn, str(plan.get("activity") or ""), bound):
                return False
            if rule == RULE_BPC_RUNS:
                for bid in bound:
                    row = conn.execute("SELECT is_bpo FROM user_blueprints WHERE id=?", (bid,)).fetchone()
                    if row is not None and not bool(row[0]) and _bp_available_runs(conn, bid) < runs:
                        return False
            capacity = sum(min(_binding_line_capacity(conn, bid), parallels) for bid in bound)
    except Exception:
        log.debug("校验计划 %s 输入蓝图失败", plan_id, exc_info=True)
        return True  # 读不到时不拦（与旧宽松语义一致）
    # 覆盖条数沿用 `_binding_shortfall` 的口径（按容量：BPO 顶全部、BPC 行按份数），
    # 只有拷贝/研究这类单作业活动只要一张
    return capacity >= parallels or rule == RULE_BPO_ONLY


def complete_plan(
    plan: dict,
    *,
    conn=None,
    actual_output_runs: int | None = None,
    actual_bpc_count: int | None = None,
    allow_bp_short: bool = False,
) -> dict:
    """ready/pending/in_progress → completed：入库产出 + 消耗绑定 BPC。

    按 activity 分派产出口径（见 services.plan_job_kinds.output_kind）：
      - manufacturing / reaction → 物品入 inventory_items；
      - copying                  → 产出的 BPC 入 user_blueprints（不消耗原图流程）；
      - invention                → **必须先回填 actual_output_runs**（成功流程数 / 0=失败），
                                   成功的 T2 BPC 入 user_blueprints，并消耗 T1 BPC 流程；
      - researching_*_efficiency → 只提升蓝图等级（等级仍由用户手动维护，本轮不回写）。

    conn: 可选注入的用户库连接（UI 已持有事务时传入）；None 时自开。
    产出入库 / BPC 消耗 / 状态更新在同一连接同一事务内完成，失败整体回滚；
    已 completed 的计划幂等返回（不重复入库）。
    allow_bp_short: 蓝图流程不足时是否放行（与 `start_plan` 成对使用 ——
    只放开启动的话，强制启动的计划将永远无法下线）。
    **母项结束时顺带清理其名下已无归属的已完成子项行**（同事务，见
    `remove_completed_children`）—— 子项自身完成不删自己，因为母项的「市场」口径成本
    依赖同组子项行存在（见 `services.plan_metrics.mother_subitem_cost_map`）。
    Returns: {"ok": bool, "message": str, "deposited": int, "removed": int, "code"?: str}
    removed = 本次清理掉的子项行数（非母项恒为 0）
    code 取值: need_outcome（发明未回填产出）
    """
    plan_id = plan.get("id")
    if not plan_id:
        return {"ok": False, "message": "计划无 id", "deposited": 0}
    from services import inventory_manager
    from services.plan_job_kinds import OUTPUT_BPC, OUTPUT_IMPROVED_BPO, is_science, output_kind

    own_conn = conn is None
    if own_conn:
        conn = _container().db.direct_connect("user")
    messages: list[str] = []
    deposited = 0
    try:
        # 以 DB 权威值为准（调用方传入的 plan dict 可能是完成前的旧值）+ 幂等
        row = conn.execute(
            "SELECT status, product_type_id, deposit_hangar_id, runs, parallels, material_cost, "
            "assigned_blueprint_id, material_cost_snapshot, activity, actual_output_runs, "
            "decryptor_type_id, group_number, sub_level, research_target_level "
            "FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            # 母项结束时子项行会被清理；从调用方视角「从未存在」与「刚被清掉」不可区分
            return {"ok": False, "message": "计划不存在或已完成", "deposited": 0}
        (
            db_status,
            product_type_id,
            deposit_hangar_id,
            runs,
            parallels,
            mat_cost,
            assigned_bp,
            cost_snap,
            activity,
            actual_output_runs_db,
            decryptor_type_id,
            group_number,
            sub_level,
            target_level,
        ) = row
        if db_status in ("completed", "done"):
            return {"ok": True, "message": "计划已完成", "deposited": 0}

        effective_actual = actual_output_runs if actual_output_runs is not None else actual_output_runs_db

        # 发明是概率作业：产出必须由用户按游戏实际结果回填后才算完成，
        # 否则产出记不准、后续成本与库存全错（见 docs/dev/flows.md「科研计划」）。
        if is_science(activity) and activity == "invention" and effective_actual is None:
            return {
                "ok": False,
                "code": "need_outcome",
                "message": "发明作业需要先填写实际产出流程数（成功）或标记发明失败",
                "deposited": 0,
            }

        # 0. 蓝图绑定校验：一条产线一张蓝图，每张流程 ≥ runs；不足拒绝完成（防 BPC 缺流程仍照常完成）
        plan_parallels = max(int(parallels or 1), 1)
        plan_runs = max(int(runs or 1), 1)
        bound_ids = get_plan_blueprints(plan_id)
        if not bound_ids and assigned_bp:
            bound_ids = [assigned_bp]
        if bound_ids:
            short = _binding_shortfall(conn, bound_ids, plan_parallels, plan_runs)
            if short and not allow_bp_short and not is_science(activity):
                # 科研作业不吃「一条产线一张图」的张数规则（发明一次尝试只耗 1 流程）
                return {
                    "ok": False,
                    "message": f"蓝图绑定不满足完成条件：{short}。请先在蓝图列补绑蓝图后重试。",
                    "deposited": 0,
                }
            if short:
                # 强制完成：货已经造出来了，不该因为账面流程不足而拒绝记录现实。
                # 消耗仍走 consume_bpc_runs（按实际可用尽力扣、耗尽删行）。
                messages.append(f"⚠ 蓝图流程不足（{short}），已强制下线；请用全量剪贴板导入矫正账面")
                log.warning("强制完成计划 %s：%s", plan_id, short)
        elif is_science(activity):
            return {
                "ok": False,
                "code": "need_blueprint",
                "message": "科研作业需要先绑定输入蓝图才能完成",
                "deposited": 0,
            }

        # 0.5 发明回填：先把用户填的实际产出落库，后续入库/成本口径都用它
        if actual_output_runs is not None and is_science(activity):
            conn.execute(
                "UPDATE production_plans SET actual_output_runs=? WHERE id=?",
                (int(actual_output_runs), plan_id),
            )

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

        kind = output_kind(activity)

        # 2. 产出入库（同一连接同一事务；deposit_hangar_id 为 -1/None 表示「不自动入库」跳过）
        if kind == OUTPUT_BPC:
            deposited = _deposit_research_output(
                conn,
                plan_id=plan_id,
                activity=activity,
                product_type_id=product_type_id,
                deposit_hangar_id=deposit_hangar_id,
                runs=plan_runs,
                parallels=plan_parallels,
                actual_output_runs=effective_actual,
                actual_bpc_count=actual_bpc_count,
                decryptor_type_id=decryptor_type_id,
                messages=messages,
            )
        elif kind == OUTPUT_IMPROVED_BPO:
            # ME/TE 研究：把绑定**蓝图原本**的等级提上去，不是入库物品
            deposited = _improve_bound_bpo_level(
                conn,
                plan_id=plan_id,
                activity=activity,
                target_level=int(target_level or 0),
                messages=messages,
            )
        elif deposit_hangar_id and deposit_hangar_id > 0 and product_type_id:
            total_mult = max(int(runs or 1), 1) * max(int(parallels or 1), 1)
            total_qty = total_mult * output_per_run(product_type_id)
            # 成本口径：优先用**启动时**的快照（不受在产期间价格重算影响）；
            # 旧计划无快照 → 回退 material_cost（最后一次重算的口径）
            snap_total = _snapshot_total(cost_snap)
            cost_basis = snap_total if snap_total is not None else (mat_cost or 0)
            cost_price = cost_basis / max(total_qty, 1)
            inventory_manager.add_item(deposit_hangar_id, product_type_id, total_qty, round(cost_price, 2), conn=conn)
            deposited = 1
            messages.append(f"成品 {total_qty} 件已入库")
            if not cost_basis:
                source = "启动快照" if snap_total is not None else "material_cost"
                messages.append(f"⚠ {source} 成本为 0（可能未成功估值），入库成本价为 0")
        else:
            messages.append("未设置产出机库，跳过入库")

        # 3. 消耗绑定 BPC：
        #    - 制造/反应：一条产线一张蓝图，每张消耗该产线的 runs 流程；
        #    - 发明：每次尝试消耗输入 T1 BPC 的 1 个流程（本计划 attempts 轮）；
        #    - 拷贝/研究：**不消耗**输入蓝图流程（拷贝不消耗原图流程；研究只提升等级）。
        if kind == OUTPUT_BPC and activity == "invention":
            # 总消耗 = 每线 runs 流程 × 产线条数 = 本计划的总尝试数（每次尝试消耗 1 流程）。
            # 按各绑定行的**容量**分摊：BPO 顶任意条数、BPC 行按份数顶。
            remaining_lines = plan_parallels
            for bid in bound_ids:
                lines = min(_binding_line_capacity(conn, bid), remaining_lines)
                if lines <= 0:
                    continue
                remaining_lines -= lines
                res = consume_bpc_runs(conn, bid, plan_runs * lines)
                if res.get("skipped"):
                    continue
                if res.get("deleted"):
                    messages.append("输入蓝图已耗尽并移除")
                else:
                    messages.append(f"输入蓝图剩余 {res.get('new_quantity')}×{res.get('new_runs')} 流程")
            if remaining_lines > 0:
                messages.append(f"⚠ 绑定蓝图只够 {plan_parallels - remaining_lines} 条产线，消耗已按实际可用量计")
        elif not is_science(activity):
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
        else:
            messages.append("科研作业不消耗输入蓝图流程")

        # 完成：清理关联表绑定
        _clear_plan_bindings(conn, plan_id)

        # 4. 回写实际入库标记
        if deposited:
            conn.execute("UPDATE production_plans SET deposited=? WHERE id=?", (deposited, plan_id))

        # 5. 母项结束时清理「已无归属」的已完成子项行（**同一事务**，与置 completed 同生共死）
        removed = 0
        if (
            int(sub_level or 0) == 0
            and int(group_number or 0) > 0
            and _no_other_active_mother(conn, plan_id, int(group_number))
        ):
            removed = remove_completed_children(int(group_number), conn=conn)
            if removed:
                messages.append(f"已清理 {removed} 条已完成的子项产线")

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

    return {"ok": True, "message": "；".join(messages), "deposited": deposited, "removed": removed}


def cancel_plan(plan: dict) -> dict:
    """撤销启动：in_progress → pending，并返还已扣减材料到材料机库。

    以 DB 权威值为准（调用方传入的 plan dict 可能是启动前的旧值）：
    返还机库取 production_plans.mat_hangar_id（start_plan 已持久化生效机库）；
    返还数量 = start_plan 持久化的 deducted_materials 快照（精确还原），
    旧计划无快照时回退「需求 − 缺口」（material_short）推导。
    返还**成本**优先取 material_cost_snapshot 的启动单价（与扣减时一致）；
    无快照时回退机库现有单位成本（避免加权平均成本被稀释）。
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
            "SELECT status, mat_hangar_id, material_short, deducted_materials, material_cost_snapshot "
            "FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "计划不存在", "returned": 0, "returned_list": []}
        db_status, mat_hangar_id, material_short, deducted_materials, cost_snap = row
        if db_status not in ("in_progress", "running"):
            return {"ok": False, "message": "仅生产中计划可撤销", "returned": 0, "returned_list": []}

        # 已扣减量优先取启动时持久化的快照（精确还原，不依赖评分重算——评分失败不再丢材料）；
        # 旧计划无快照 → 回退「需求 − 缺口」推导（material_short JSON {type_id: missing_qty}）
        if mat_hangar_id:
            # 返还单价优先取启动快照（与扣减时同一口径）；旧计划无快照 → 机库当前加权成本
            snap_unit = parse_cost_snapshot(cost_snap).get("unit") or {}
            cost_map = snap_unit if snap_unit else inventory_manager.get_hangar_cost_map(mat_hangar_id)
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
            "deducted_materials='', material_cost_snapshot='', assigned_blueprint_id=NULL "
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

    清除 started_at / completed_at / deposited / material_short / 启动成本快照与蓝图占用、
    以及**发明实际产出回填**（`actual_output_runs`）—— 不清它，「待下线」判定
    （`_is_pending_invention` 靠它是否为 NULL）会认为已回填过，复用的第二轮不再弹回填窗，
    产出/成本还会沿用上一轮的旧值。
    置回 pending 供再次启动。不触碰库存（成品已入库、材料不退回）。
    快照必须清掉：否则「复用后未重新启动就再次下线」会误用上一轮的启动成本。

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
            "deposited=0, material_short='', deducted_materials='', material_cost_snapshot='', "
            "actual_output_runs=NULL, "
            "assigned_blueprint_id=NULL WHERE id=?",
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
        capacity = sum(min(_binding_line_capacity(conn, bid), parallels) for bid in bound)
    return {"bound": bound, "need": parallels, "runs": runs, "capacity": capacity}


def blueprint_line_capacity(quantity: int | None) -> int:
    """一条蓝图记录能覆盖**几条并行产线** = 该行**份数**（quantity）。

    游戏规则：一张蓝图（BPO 还是 BPC 都一样）同一时刻只能进**一个**作业，所以并行 N 条线
    就要 N 张蓝图。导入路径每张蓝图写一行、quantity=1；而发明/拷贝产出的 BPC 会按同规格
    **合并成一行**（quantity=N）—— 那种堆必须能供 N 条线，否则「用发明出来的 T2 BPC 并行
    造 T2 物品」会被误判成蓝图不足。

    与 `_bp_available_runs` 的区别：那个算「还能喂多少**流程**」（BPO 视为无限，因为 BPO
    不会被消耗）；这里算的是「能顶几条**产线**」。
    """
    return max(0, int(quantity or 0))


def _binding_line_capacity(conn, bp_id: int) -> int:
    """库存行版：读 `user_blueprints` 后按 `blueprint_line_capacity` 算覆盖条数。"""
    row = conn.execute("SELECT quantity FROM user_blueprints WHERE id=?", (bp_id,)).fetchone()
    if not row:
        return 0
    return blueprint_line_capacity(row[0])


def _bp_available_runs(conn, bp_id: int) -> int | float:
    """连接内查 BPC 可用流程 = quantity×runs；BPO 返回大数（视为无限）。"""
    row = conn.execute("SELECT is_bpo, runs, quantity FROM user_blueprints WHERE id=?", (bp_id,)).fetchone()
    if not row:
        return 0
    if row[0]:
        return 10**15
    # 负数归零：v16 迁移已把原图归一到 is_bpo=1/runs=0，正常不存在负 runs；
    # 这里保留夹取，作为「迁移尚未跑到」的历史库防线——否则 quantity×runs
    # 会给出负的「可用流程」，让「不足」的判定依赖负数的巧合。
    return max(0, int(row[2] or 0) * int(row[1] or 0))


def _binding_shortfall(conn, bound_ids: list[int], parallels: int, runs: int) -> str | None:
    """校验绑定能否覆盖 parallels 条产线、且每条的流程数 ≥ runs；不足返回原因，满足 None。

    **覆盖条数按容量算，不按行数**：BPO 一条顶全部、BPC 行按份数顶（见
    `blueprint_line_capacity`）—— 这样「一张图纸合成一行、份数=3」也能供 3 条线。
    """
    capacity = 0
    for bid in bound_ids:
        capacity += min(_binding_line_capacity(conn, bid), parallels)
    if capacity < parallels:
        return f"绑定蓝图可覆盖 {capacity} 条产线，不足 {parallels} 条（还差 {parallels - capacity} 张）"
    for i, bid in enumerate(bound_ids, 1):
        if _bp_available_runs(conn, bid) < runs:
            return f"第 {i} 张绑定蓝图流程不足（需 ≥ {runs} 流程，当前产线每条要跑 {runs} 轮）"
    return None


def binding_shortfall(plan_id: int) -> str | None:
    """预检该计划的蓝图绑定是否满足「一条产线一张、每张流程 ≥ runs」。

    供 UI 在**调用 `start_plan` 之前**判断要不要弹「强制启动」确认 ——
    与 `plan_start_block_reason` 的注入式判定同思路，DB 访问收敛在服务层。
    不足返回原因文本；满足 / 一张未绑 / 计划不存在返回 None
    （「没绑」由 `plan_start_block_reason` 的 has_image 分支负责）。
    """
    if not plan_id:
        return None
    state = get_plan_binding_state(plan_id)
    if not state["bound"]:
        return None
    with _container().db.connect("user") as conn:
        return _binding_shortfall(conn, state["bound"], int(state["need"]), int(state["runs"]))


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


def get_occupied_blueprint_ids(db=None, *, exclude_plan_id: int | None = None) -> set[int]:
    """返回被活跃计划（非 completed/done）占用的 user_blueprints.id 集合。

    兼容多蓝图关联表（plan_blueprint_bindings）与旧单值列（assigned_blueprint_id）。
    exclude_plan_id: 传入计划 id 时排除其自身占用（查询本计划可选项时不把自己算作已占用）。
    """
    db_mgr = db or _container().db
    occupied: set[int] = set()
    with db_mgr.connect("user") as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT b.blueprint_id FROM plan_blueprint_bindings b "
                "JOIN production_plans pp ON pp.id=b.plan_id "
                "WHERE pp.status NOT IN ('completed','done')"
                + (" AND b.plan_id<>?" if exclude_plan_id is not None else ""),
                (exclude_plan_id,) if exclude_plan_id is not None else (),
            ).fetchall()
            occupied = {r[0] for r in rows}
        except Exception:
            log.debug("旧库无 plan_blueprint_bindings 表，回退单值列", exc_info=True)
        try:
            rows = conn.execute(
                "SELECT DISTINCT assigned_blueprint_id FROM production_plans "
                "WHERE assigned_blueprint_id IS NOT NULL AND status NOT IN ('completed','done')"
                + (" AND id<>?" if exclude_plan_id is not None else ""),
                (exclude_plan_id,) if exclude_plan_id is not None else (),
            ).fetchall()
            occupied.update(r[0] for r in rows if r[0] is not None)
        except Exception:
            # 蓝图导入等路径也会调用本函数，缺表不得让调用方整体失败
            log.debug("旧库无 production_plans 表，跳过单值列占用", exc_info=True)
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
                "available_runs": float("inf") if is_bpo else max(0, int(r[6] or 0) * int(r[5] or 0)),
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


def _available_blueprint_options(product_type_id: int | None, blueprint_type_id: int | None) -> list[dict]:
    """该计划产品的库存蓝图（**不过滤占用**，每条带 `occupied` / `available_runs`）。

    制造按产物反查制造蓝图；科研行直接用 `blueprint_type_id`（发明 = 被发明的 T2 蓝图，
    拷贝/研究 = 被操作的 BPO）。

    **占用过滤留给调用方**：`_auto_bind_blueprints` 只挑没被占的；而「按当前绑定重新对齐」
    （`resync_plan_bindings`）必须连**本计划自己绑的那张**也看得见 —— 那种行也带
    `occupied`，滤掉就会把现有绑定当成「不可用」而误判成需要重挑。
    """
    target_bp = int(blueprint_type_id or 0)
    with _container().db.connect("user", "bp", "ref") as conn:
        if not target_bp:
            row = conn.execute(
                "SELECT blueprint_type_id FROM blueprint_products "
                "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                (product_type_id,),
            ).fetchone()
            if not row:
                return []
            target_bp = int(row[0])
        return find_available_blueprints(conn, target_bp)


def _blueprint_capable(option: dict, rule: str, runs: int) -> bool:
    """这张蓝图是否满足活动的类型规则与流程要求（规则见 services.plan_job_kinds）。"""
    from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY

    if rule == RULE_BPO_ONLY:
        return bool(option.get("is_bpo"))
    if rule == RULE_BPC_RUNS:
        return not option.get("is_bpo") and (option.get("available_runs") or 0) >= runs
    return bool(option.get("is_bpo")) or (option.get("available_runs") or 0) >= runs


def _auto_bind_blueprints(plan: dict) -> list[int]:
    """自动选最优库存蓝图。返回应绑定的库存蓝图 id 清单（按活动规则）。

    活动规则（services.plan_job_kinds）：
      - 制造/反应：BPO 优先，其次 ME 最高的够用 BPC；并行几条线绑几张，每张流程 ≥ runs。
      - 拷贝/研究：**只挑 BPO**（BPC 不可再拷贝或研究）。
      - 发明：**只挑 BPC**（且流程 ≥ runs），BPO 不能用于发明。

    只选未被其他活跃计划占用的蓝图；库存不足时返回已凑到的张数，
    由调用方经 _binding_shortfall / plan_blueprint_ready 提示补绑。
    """
    from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY, input_blueprint_rule

    product_type_id = plan.get("product_type_id")
    blueprint_type_id = plan.get("blueprint_type_id")
    if not product_type_id and not blueprint_type_id:
        return []
    runs = max(int(plan.get("runs", 1)), 1)
    parallels = max(int(plan.get("parallels", 1)), 1)
    rule = input_blueprint_rule(plan.get("activity"))

    options = [o for o in _available_blueprint_options(product_type_id, blueprint_type_id) if not o.get("occupied")]
    if not options:
        return []

    if rule == RULE_BPO_ONLY:
        picks = [o for o in options if o.get("is_bpo")]
    elif rule == RULE_BPC_RUNS:
        capable = [o for o in options if not o.get("is_bpo") and (o.get("available_runs") or 0) >= runs]
        capable.sort(key=lambda b: (b.get("me_level", 0), b.get("te_level", 0)), reverse=True)
        picks = capable
    else:
        picks = [o for o in options if o.get("is_bpo")]
        if len(picks) < parallels:
            capable = [o for o in options if not o.get("is_bpo") and (o.get("available_runs") or 0) >= runs]
            capable.sort(key=lambda b: (b.get("me_level", 0), b.get("te_level", 0)), reverse=True)
            picks.extend(capable)
    # 拷贝/研究是「一个作业」（拷贝的 parallels 是**产出份数**、研究的并行恒为 1）→ 一张。
    # 制造/反应/发明按**覆盖条数**凑：一张蓝图只能进一个作业，所以并行 N 条线要凑够
    # N 条线的容量（份数），见 `blueprint_line_capacity`。
    if rule == RULE_BPO_ONLY:
        return [int(picks[0]["id"])] if picks else []
    out: list[int] = []
    capacity = 0
    for option in picks:
        out.append(int(option["id"]))
        capacity += min(blueprint_line_capacity(option.get("quantity")), parallels)
        if capacity >= parallels:
            break
    return out


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


def resync_plan_bindings(plan_id: int) -> bool:
    """按计划当前的 runs/parallels **重新对齐**蓝图绑定；返回是否改动了绑定。

    与 `ensure_plan_auto_bind` 的分工：那个只在**零绑定**时动手（建计划用），所以
    「原来绑 1 张、并行改成 3 条」或「流程改成 20、绑的那张只有 10 流程」都不会补 ——
    要等启动时才报蓝图不足。**改流程 / 改并行后就该调本函数**。

    现有绑定仍然合规且够用 → 一根不动（不打扰用户的手工选择，也避免来回抢图）；
    不够或多余 → 以「够用的现有绑定优先」重挑，补位沿用 `_auto_bind_blueprints` 的规则。
    """
    from services.plan_job_kinds import RULE_BPO_ONLY, input_blueprint_rule

    if not plan_id or plan_id <= 0:
        return False
    with _container().db.connect("user") as conn:
        row = conn.execute(
            "SELECT product_type_id, blueprint_type_id, COALESCE(runs,1), COALESCE(parallels,1), COALESCE(activity,'') "
            "FROM production_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
    if row is None:
        return False
    product_type_id, blueprint_type_id, runs, parallels, activity = row
    runs = max(int(runs), 1)
    parallels = max(int(parallels), 1)
    rule = input_blueprint_rule(activity)
    # 拷贝/研究是单作业（拷贝的 parallels 是**产出份数**）→ 只要能覆盖 1 条线；
    # 其余按**覆盖条数**凑够 parallels（BPO 一条顶全部、BPC 行按份数顶）。
    target_lines = 1 if rule == RULE_BPO_ONLY else parallels
    current = get_plan_binding_state(plan_id)["bound"]

    options = _available_blueprint_options(product_type_id, blueprint_type_id)
    by_id = {int(o["id"]): o for o in options}

    def _capacity_of(blueprint_id: int) -> int:
        option = by_id.get(blueprint_id)
        if option is None:
            return 0
        return min(blueprint_line_capacity(option.get("quantity")), target_lines)

    keep: list[int] = []
    covered = 0
    for bid in current:
        option = by_id.get(bid)
        if option is None or not _blueprint_capable(option, rule, runs):
            continue
        keep.append(bid)
        covered += _capacity_of(bid)
        if covered >= target_lines:
            break
    if covered >= target_lines and len(keep) == len(current):
        return False  # 现有绑定正好覆盖全部产线、也没有多余的 → 不动

    plan = {
        "product_type_id": product_type_id,
        "blueprint_type_id": blueprint_type_id,
        "runs": runs,
        "parallels": parallels,
        "activity": activity,
    }
    final: list[int] = []
    capacity = 0
    for bid in keep + [b for b in _auto_bind_blueprints(plan) if b not in keep]:
        lines = _capacity_of(bid)
        if lines <= 0:
            continue
        final.append(bid)
        capacity += lines
        if capacity >= target_lines:
            break
    if set(final) == set(current):
        return False
    bind_blueprints(plan_id, final)
    return True

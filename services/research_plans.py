"""科研计划的蓝图选型与落库 — 拷贝/发明/研究建计划行的唯一入口。

UI（蓝图库右键、全物品页右键）与「研究分析」对话框都调这里，
SQL 不散落到各处。

关键概念（语义契约见 services.plan_job_kinds）：
    product_type_id    本计划的产物。科研行恒为**蓝图 type_id**
                       （发明 = 产出的 T2 蓝图；拷贝/研究 = 被操作的蓝图）。
    blueprint_type_id  同 product_type_id（科研行的输入蓝图与产物是同一张）。
    runs               拷贝 = 每份拷贝的授权流程；发明 = 尝试次数；研究 = 目标等级。
    parallels          拷贝 = 产出份数；其余按 1 计。
"""

from __future__ import annotations

from typing import Any

from core.logger import log

# blueprint_activities 里研究活动的名字（活动表用 -ing 后缀，材料表不用）
_ACT_COPYING = "copying"
_ACT_INVENTION = "invention"


def resolve_invention_source(conn, blueprint_type_id: int) -> dict[str, Any] | None:
    """给定 T2/T3 蓝图，反查它的发明来源与全部可能的产物。

    返回 {t1_blueprint_type_id, t1_name, outcomes: [{blueprint_type_id, name, base_probability}],
          max_production_limit}；该蓝图不是发明产物 → None。
    """
    t1 = conn.execute(
        "SELECT bp.blueprint_type_id FROM blueprint_products bp "
        "JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id "
        "AND ba.activity = bp.activity "
        "WHERE bp.activity = 'invention' AND bp.product_type_id = ? LIMIT 1",
        (blueprint_type_id,),
    ).fetchone()
    if not t1:
        return None
    t1_bp = int(t1[0])
    outcome_rows = conn.execute(
        "SELECT product_type_id, probability FROM blueprint_products "
        "WHERE activity = 'invention' AND blueprint_type_id = ? ORDER BY product_type_id",
        (t1_bp,),
    ).fetchall()
    t1_row = conn.execute("SELECT zh_name FROM item WHERE type_id = ?", (t1_bp,)).fetchone()
    t1_name = (t1_row[0] if t1_row else None) or str(t1_bp)
    outcomes: list[dict[str, Any]] = []
    for _bp, prob in outcome_rows:
        bp_id = int(_bp)
        row = conn.execute("SELECT zh_name FROM item WHERE type_id = ?", (bp_id,)).fetchone()
        outcomes.append(
            {
                "blueprint_type_id": bp_id,
                "name": (row[0] if row else None) or str(bp_id),
                "base_probability": float(prob or 0.0),
            }
        )
    limit = conn.execute(
        "SELECT max_production_limit FROM blueprint_activities "
        "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
        (t1_bp,),
    ).fetchone()
    return {
        "t1_blueprint_type_id": t1_bp,
        "t1_name": t1_name,
        "outcomes": outcomes,
        "t1_copy_limit": int(limit[0] or 0) if limit else 0,
    }


def invention_base_runs(conn, t2_blueprint_type_id: int, t1_blueprint_type_id: int) -> int:
    """发明产出的 T2 BPC 基础流程数 = min(T1 拷贝上限, T2 制造上限)。

    SDE 实测（1125 条发明路径可校验）：这是唯一稳定的来源——
    按「舰船 1 / 其余 10」硬编码会错（部分组件是 1、改装件是 5/20/300）。
    任一上限缺失时回退 10。
    """
    row = conn.execute(
        "SELECT max_production_limit FROM blueprint_activities "
        "WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
        (t2_blueprint_type_id,),
    ).fetchone()
    t2_limit = int(row[0] or 0) if row else 0
    t1_limit = int(
        (
            conn.execute(
                "SELECT max_production_limit FROM blueprint_activities "
                "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
                (t1_blueprint_type_id,),
            ).fetchone()
            or [0]
        )[0]
        or 0
    )
    caps = [c for c in (t1_limit, t2_limit) if c > 0]
    return min(caps) if caps else 10


def research_cost_per_run(
    db,
    blueprint_type_id: int,
    *,
    solar_system_id: int | None = None,
    char_config: dict | None = None,
) -> dict[str, Any] | None:
    """「该蓝图每流程的研究成本」——供蓝图库「自动填写每流程成本」与「研究分析」使用。

    两种情形：
      - T2/T3 蓝图（由发明产出）→ 发明期望成本 ÷ 期望产出的流程数；
      - 其余蓝图 → 拷贝成本 ÷ 每份拷贝流程数。

    返回 {kind, cost_per_run, outcomes: [{blueprint_type_id, name, cost_per_run, success_rate}]}；
    无拷贝/发明路径 → None。
    """
    from services.plan_metrics import copying_plan_cost, invention_plan_cost
    from services.scoring_service import get_system_cost_index

    skills = (char_config or {}).get("skills", {}) or {}

    with db.connect("bp", "ref", "mkt") as conn:
        src = resolve_invention_source(conn, blueprint_type_id)
        if src is not None:
            sci = float(get_system_cost_index(solar_system_id, _ACT_INVENTION, _db=db) or 0.0)
            t1_bp = int(src["t1_blueprint_type_id"])
            # 材料/单次价格/技能对同一张 T1 蓝图的各产物都一样，循环外取一次
            mats = _materials(conn, t1_bp, _ACT_INVENTION)
            prices = _prices(conn, [m for m, _q in mats])
            science_1, science_2, enc = _skill_levels(conn, t1_bp, _ACT_INVENTION, skills)
            outcomes: list[dict[str, Any]] = []
            for oc in src["outcomes"]:
                bp_id = int(oc["blueprint_type_id"])
                base_runs = invention_base_runs(conn, bp_id, t1_bp)
                cost = invention_plan_cost(
                    base_probability=float(oc["base_probability"]),
                    materials=mats,
                    prices=prices,
                    sci=sci,
                    science_skill_1=science_1,
                    science_skill_2=science_2,
                    encryption_skill=enc,
                    base_runs=base_runs,
                    output_runs_needed=base_runs,  # 单次尝试的产出即基准
                )
                outcomes.append(
                    {
                        "blueprint_type_id": bp_id,
                        "name": oc["name"],
                        "cost_per_run": round(cost["bpc_unit_cost"], 2),
                        "success_rate": cost["success_rate"],
                        "runs_per_bpc": cost["runs_per_bpc"],
                    }
                )
            best = min(outcomes, key=lambda o: o["cost_per_run"]) if outcomes else None
            return {
                "kind": "invention",
                "t1_blueprint_type_id": src["t1_blueprint_type_id"],
                "t1_name": src["t1_name"],
                "outcomes": outcomes,
                "best": best,
                "cost_per_run": best["cost_per_run"] if best else 0.0,
                "sci": sci,
            }

        # 非发明产物 → 拷贝成本
        act = conn.execute(
            "SELECT max_production_limit FROM blueprint_activities "
            "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
            (blueprint_type_id,),
        ).fetchone()
        if not act:
            return None
        limit = max(1, int(act[0] or 1))
        mats = _materials(conn, blueprint_type_id, _ACT_COPYING)
        prices = _prices(conn, [m for m, _q in mats])
        sci = float(get_system_cost_index(solar_system_id, _ACT_COPYING, _db=db) or 0.0)
        cost = copying_plan_cost(
            materials=mats,
            prices=prices,
            sci=sci,
            total_copy_runs=limit,
            copies=1,
        )
        return {
            "kind": "copying",
            "max_production_limit": limit,
            "cost_per_run": round(cost["total_cost"] / limit, 2),
            "sci": sci,
        }


def _materials(conn, blueprint_type_id: int, activity: str) -> list[tuple[int, int]]:
    """蓝图某活动的材料清单 [(type_id, qty)]。"""
    from services.plan_job_kinds import material_activity

    mat_act = material_activity(activity)
    return [
        (int(r[0]), int(r[1] or 0))
        for r in conn.execute(
            "SELECT material_type_id, quantity FROM blueprint_materials "
            "WHERE blueprint_type_id = ? AND activity = ?",
            (blueprint_type_id, mat_act),
        ).fetchall()
    ]


def _prices(conn, type_ids: list[int]) -> dict[int, float]:
    """adjusted_price 优先（0/缺失 → sell_price → buy_price）。"""
    prices: dict[int, float] = {}
    for tid in {t for t in type_ids if t}:
        row = conn.execute(
            "SELECT adjusted_price, sell_price, buy_price FROM market_prices "
            "WHERE type_id = ? ORDER BY (adjusted_price > 0) DESC, fetch_time DESC LIMIT 1",
            (tid,),
        ).fetchone()
        if row:
            prices[tid] = float(row[0] or 0) or float(row[1] or 0) or float(row[2] or 0)
    return prices


def _skill_levels(conn, blueprint_type_id: int, activity: str, skills: dict) -> tuple[int, int, int]:
    """该活动要求的两个科学技能 + 加密技术原理的等级。"""
    rows = conn.execute(
        "SELECT bs.skill_type_id, i.zh_name, i.en_name FROM blueprint_skills bs "
        "LEFT JOIN ref.item i ON i.type_id = bs.skill_type_id "
        "WHERE bs.blueprint_type_id = ? AND bs.activity = ? ORDER BY bs.skill_type_id",
        (blueprint_type_id, activity),
    ).fetchall()
    science: list[str] = []
    encryption = ""
    for _sid, zh, en in rows:
        name = zh or en or ""
        if "加密技术原理" in name or "Encryption" in (en or ""):
            if not encryption:
                encryption = name
        elif name:
            science.append(name)
    lv = lambda n: int(skills.get(n, 0) or 0)  # noqa: E731
    return (
        lv(science[0]) if len(science) > 0 else 0,
        lv(science[1]) if len(science) > 1 else 0,
        lv(encryption) if encryption else 0,
    )


def plan_type_name(plan: dict) -> str:
    """给计划表「产品」列展示的研究产物名（拷贝/发明/研究各有说法）。"""
    from services.plan_job_kinds import normalize

    name = plan.get("product_name") or ""
    act = normalize(plan.get("activity"))
    if act == "copying":
        return f"{name}（拷贝）"
    if act == "invention":
        return f"{name}（发明）"
    if act == "researching_material_efficiency":
        return f"{name}（ME 研究）"
    if act == "researching_time_efficiency":
        return f"{name}（TE 研究）"
    return name


def create_research_plan(
    blueprint_type_id: int,
    *,
    activity: str,
    blueprint_name: str,
    runs: int = 1,
    parallels: int = 1,
    mat_hangar_id: int | None = None,
    deposit_hangar_id: int | None = None,
    solar_system_id: int | None = None,
    char_name: str = "",
    facility: str = "",
    decryptor_type_id: int | None = None,
    success_rate: float | None = None,
    research_target_level: int = 0,
    mat_hub: str = "Jita",
    sell_hub: str = "Jita",
) -> int:
    """建一条科研计划行（pending，含科研专属列），返回 plan_id；失败 → -1。

    单次 INSERT：科研专属列与指标一起写，避免「先建行再补字段」的两步写入。
    不做蓝图绑定——由调用方经 ensure_plan_auto_bind 或显式绑定。
    """
    from core.container import get_container
    from services.plan_service import calculate_plan_metrics, datetime_now_str

    plan_input = {
        "product_type_id": blueprint_type_id,
        "blueprint_type_id": blueprint_type_id,
        "product_name": blueprint_name,
        "activity": activity,
        "runs": max(1, int(runs)),
        "parallels": max(1, int(parallels)),
        "me_level": 0,
        "te_level": 0,
        "mat_hub": mat_hub,
        "sell_hub": sell_hub,
        "char_name": char_name,
        "facility": facility,
        "solar_system_id": solar_system_id,
        "decryptor_type_id": decryptor_type_id,
        "success_rate": success_rate,
        "research_target_level": research_target_level,
    }
    try:
        metrics = calculate_plan_metrics(plan_input, char_name=char_name)
    except Exception:
        log.exception("科研计划指标计算失败 bp=%s activity=%s", blueprint_type_id, activity)
        metrics = {}

    try:
        with get_container().db.connect("user") as conn:
            cur = conn.execute(
                "INSERT INTO production_plans "
                "(product_type_id, product_name, blueprint_type_id, runs, parallels, me_level, te_level, "
                "mat_hub, sell_hub, facility, char_name, status, "
                "profit, margin, score, iskph, material_cost, calculated_time, daily_output, created_at, "
                "deposit_hangar_id, mat_hangar_id, solar_system_id, materials_ready, "
                "activity, decryptor_type_id, success_rate, research_target_level) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
                (
                    blueprint_type_id,
                    blueprint_name,
                    blueprint_type_id,
                    plan_input["runs"],
                    plan_input["parallels"],
                    0,
                    0,
                    mat_hub,
                    sell_hub,
                    facility,
                    char_name,
                    metrics.get("profit", 0),
                    metrics.get("margin", 0),
                    metrics.get("score", 0),
                    metrics.get("iskph", 0),
                    metrics.get("material_cost", 0),
                    metrics.get("calculated_time", 0),
                    metrics.get("daily_output", 0),
                    datetime_now_str(),
                    deposit_hangar_id,
                    mat_hangar_id,
                    solar_system_id,
                    activity,
                    decryptor_type_id,
                    success_rate,
                    int(research_target_level or 0),
                ),
            )
            plan_id = int(cur.lastrowid or -1)
        if plan_id > 0:
            from services.plan_execution import ensure_plan_auto_bind

            try:
                ensure_plan_auto_bind(plan_id)
            except Exception:
                log.warning("科研计划 %s 自动绑定失败", plan_id, exc_info=True)
        return plan_id
    except Exception:
        log.exception("科研计划落库失败 bp=%s activity=%s", blueprint_type_id, activity)
        return -1

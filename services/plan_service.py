"""生产计划共享落库 — 统一「加入制造规划」的检查/落库/重算。

把 industry_view._on_plan_add 的完整流程抽为共享函数，供仓库右键、查询页复用。
评分（ScoreWorker）与 AddPlanDialog 是 UI 层组件，编排由调用方（plan_service_add_flow）完成。
"""

from __future__ import annotations

from core.container import get_container
from services.char_config_resolver import resolve_char_config


def calculate_plan_metrics(
    plan_input: dict,
    *,
    char_name: str = "",
    mat_price_type: str = "buy",
    prod_price_type: str = "sell",
) -> dict:
    """用统一方法计算派生指标（profit/margin/score/iskph/material_cost/calculated_time/daily_output）。"""
    actual_char_name = (plan_input.get("char_name") or "").strip() or char_name
    actual_config = resolve_char_config(char_name=actual_char_name)
    return dict(
        get_container()
        .scoring_service()
        .calculate_plan_metrics(
            plan_input,
            actual_config,
            price_type_mat=mat_price_type,
            price_type_prod=prod_price_type,
        )
    )


def insert_plan(
    type_id: int,
    product_name: str,
    data: dict,
    *,
    mat_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility: str = "",
    solar_system_id: int | None = None,
    mat_hangar_id: int | None = None,
    deposit_hangar_id: int | None = None,
    metrics: dict | None = None,
) -> int:
    """INSERT 一条 pending 制造计划（24 列，含派生指标），返回 plan_id。"""
    metrics = metrics or {}
    with get_container().db.connect("user") as conn:
        cur = conn.execute(
            "INSERT INTO production_plans "
            "(product_type_id, product_name, runs, parallels, me_level, te_level, "
            "mat_hub, sell_hub, facility, char_name, status, "
            "profit, margin, score, iskph, material_cost, "
            "calculated_time, daily_output, created_at, deposit_hangar_id, mat_hangar_id, solar_system_id, "
            "materials_ready) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                type_id,
                product_name,
                data.get("runs", 1),
                data.get("parallels", 1),
                data.get("me", 0),
                data.get("te", 0),
                mat_hub,
                sell_hub,
                facility,
                data.get("char", ""),
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
            ),
        )
        rowid = cur.lastrowid
        return int(rowid) if rowid is not None else -1


def insert_plans_batch(rows: list[dict]) -> list[int]:
    """批量 INSERT 多条 pending 制造计划（一次连接/事务），返回 plan_id 列表。

    rows: 与 insert_plan 参数同构的 dict，含 type_id/product_name/data/metrics 及可选字段。
    """
    if not rows:
        return []
    ids: list[int] = []
    with get_container().db.connect("user") as conn:
        for r in rows:
            metrics = r.get("metrics") or {}
            data = r.get("data", {})
            cur = conn.execute(
                "INSERT INTO production_plans "
                "(product_type_id, product_name, runs, parallels, me_level, te_level, "
                "mat_hub, sell_hub, facility, char_name, status, "
                "profit, margin, score, iskph, material_cost, "
                "calculated_time, daily_output, created_at, deposit_hangar_id, mat_hangar_id, solar_system_id, "
                "materials_ready) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    r["type_id"],
                    r.get("product_name", ""),
                    data.get("runs", 1),
                    data.get("parallels", 1),
                    data.get("me", 0),
                    data.get("te", 0),
                    r.get("mat_hub", "Jita"),
                    r.get("sell_hub", "Jita"),
                    r.get("facility", ""),
                    data.get("char", ""),
                    metrics.get("profit", 0),
                    metrics.get("margin", 0),
                    metrics.get("score", 0),
                    metrics.get("iskph", 0),
                    metrics.get("material_cost", 0),
                    metrics.get("calculated_time", 0),
                    metrics.get("daily_output", 0),
                    datetime_now_str(),
                    r.get("deposit_hangar_id"),
                    r.get("mat_hangar_id"),
                    r.get("solar_system_id"),
                ),
            )
            rowid = cur.lastrowid
            ids.append(int(rowid) if rowid is not None else -1)
    return ids


def datetime_now_str() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def enrich_plan_hangar_names(rows: list[dict], hangar_names: dict[int, str]) -> list[dict]:
    """为计划行补派生显示字段（内存，不落库）。

    - ``facility`` 为空且有材料机库 → 显示材料机库名称；
    - ``output_hangar`` = 输出机库（deposit_hangar_id）名称，无则空串。
    """
    for row in rows:
        hid = row.get("mat_hangar_id")
        if not row.get("facility") and hid in hangar_names:
            row["facility"] = hangar_names[hid]
        deposit = row.get("deposit_hangar_id")
        row["output_hangar"] = hangar_names.get(deposit, "") if deposit else ""
    return rows


def load_plans(filter_key: str) -> list[dict]:
    """加载生产计划列表，并补全蓝图可用标记/类别/机库名称。"""
    with get_container().db.connect("user", "bp") as conn:
        sql = "SELECT * FROM production_plans"
        if filter_key == "待排":
            sql += " WHERE status = 'pending'"
        elif filter_key == "运行中":
            sql += " WHERE status IN ('in_progress','running')"
        elif filter_key == "待下线":
            sql += " WHERE status = 'ready'"
        elif filter_key == "已完成":
            sql += " WHERE status IN ('completed','done')"
        sql += " ORDER BY created_at DESC"
        c = conn.cursor()
        c.execute(sql)
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r, strict=False)) for r in c.fetchall()]

        owned_bp = {r[0] for r in conn.execute("SELECT DISTINCT blueprint_type_id FROM user_blueprints").fetchall()}
        prod_to_bp: dict[int, list[int]] = {}
        for tid, bpid in conn.execute(
            "SELECT product_type_id, blueprint_type_id FROM bp.blueprint_products WHERE activity='manufacturing'"
        ).fetchall():
            prod_to_bp.setdefault(tid, []).append(bpid)
        hangar_names = dict(conn.execute("SELECT id, name FROM hangars").fetchall())

    for row in rows:
        ptid = row.get("product_type_id")
        has_bp = bool(row.get("assigned_blueprint_id")) or any(b in owned_bp for b in prod_to_bp.get(ptid, []))
        row["has_image"] = has_bp
        row["group_id"] = row.get("group_number", 0)
        row["child_level"] = row.get("sub_level", 0)

    from services.plan_category import load_category_map

    bp_ids = [r.get("blueprint_type_id") for r in rows if r.get("blueprint_type_id")]
    cat_map: dict[int, str] = {}
    if bp_ids:
        with get_container().db.connect("bp") as bp_conn:
            cat_map = load_category_map(bp_conn, bp_ids)
    for row in rows:
        row["category"] = cat_map.get(row.get("blueprint_type_id"), "manufacturing")

    enrich_plan_hangar_names(rows, hangar_names)
    return rows


def collect_refresh_type_ids() -> tuple[set[int], int]:
    """收集工业页定向刷新所需的 type_id 集合，并返回其中 5 分钟内已缓存的条数。"""
    with get_container().db.connect("user") as conn:
        rows = conn.execute(
            "SELECT id, product_type_id FROM production_plans "
            "WHERE status IN ('pending','in_progress','running','ready')"
        ).fetchall()
        product_ids = {r[1] for r in rows}

    material_ids: set[int] = set()
    if product_ids:
        with get_container().db.connect("bp") as conn:
            placeholders = ",".join("?" for _ in product_ids)
            material_rows = conn.execute(
                "SELECT DISTINCT bm.material_type_id "
                "FROM blueprint_products bp "
                "JOIN blueprint_materials bm ON bm.blueprint_type_id=bp.blueprint_type_id "
                "AND bm.activity=bp.activity "
                f"WHERE bp.product_type_id IN ({placeholders}) AND bp.activity='manufacturing'",
                list(product_ids),
            ).fetchall()
            material_ids = {r[0] for r in material_rows}

    all_ids = product_ids | material_ids
    is_cached = 0
    if all_ids:
        with get_container().db.connect("mkt") as conn:
            ph = ",".join("?" for _ in all_ids)
            row = conn.execute(
                f"SELECT COUNT(*) FROM market_prices WHERE type_id IN ({ph}) "
                "AND region_id=10000002 "
                "AND fetch_time > datetime('now', '-5 minutes', 'utc')",
                list(all_ids),
            ).fetchone()
            is_cached = int(row[0]) if row else 0
    return all_ids, is_cached


def save_price_snapshots() -> int:
    """为活跃计划及其物料保存当前 Jita 价格快照，返回保存条数。"""
    with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
        c = conn.cursor()
        c.execute("SELECT product_type_id FROM production_plans WHERE status IN ('pending','in_progress','running')")
        plan_pids = [r[0] for r in c.fetchall()]
        if not plan_pids:
            return 0
        placeholders = ",".join("?" for _ in plan_pids)
        c.execute(
            "SELECT DISTINCT bm.material_type_id "
            "FROM bp.blueprint_products bp "
            "JOIN bp.blueprint_materials bm "
            "ON bm.blueprint_type_id=bp.blueprint_type_id "
            "AND bm.activity=bp.activity "
            f"WHERE bp.product_type_id IN ({placeholders}) "
            "AND bp.activity='manufacturing'",
            plan_pids,
        )
        type_ids = {r[0] for r in c.fetchall()}
        type_ids.update(plan_pids)
        count = 0
        for tid in type_ids:
            row = c.execute(
                "SELECT sell_price, buy_price FROM mkt.market_prices "
                "WHERE type_id=? AND region_id=10000002 LIMIT 1",
                (tid,),
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO price_snapshots(type_id,region_id,sell_price,buy_price) "
                    "VALUES (?,10000002,?,?)",
                    (tid, row[0] or 0, row[1] or 0),
                )
                count += 1
        return count


def load_active_plans_for_procurement() -> list[dict]:
    """加载采购对话框所需的活跃计划列表。"""
    plans: list[dict] = []
    with get_container().db.connect("user", "ref", "mkt") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, product_type_id, product_name, runs, parallels, me_level, mat_hub, sell_hub, "
            "materials_ready, status, deposit_hangar_id, deposited, material_cost, "
            "assigned_blueprint_id, mat_hangar_id, material_short, group_number, sub_level "
            "FROM production_plans WHERE status IN ('pending', 'in_progress', 'running', 'ready')"
        )
        for pr in c.fetchall():
            plans.append(
                {
                    "id": pr[0],
                    "product_type_id": pr[1],
                    "product_name": pr[2],
                    "runs": pr[3],
                    "parallels": pr[4],
                    "me_level": pr[5],
                    "mat_hub": pr[6],
                    "sell_hub": pr[7],
                    "materials_ready": pr[8],
                    "status": pr[9],
                    "deposit_hangar_id": pr[10],
                    "deposited": pr[11],
                    "material_cost": pr[12],
                    "assigned_blueprint_id": pr[13],
                    "mat_hangar_id": pr[14],
                    "material_short": pr[15],
                    "group_id": pr[16],
                    "child_level": pr[17],
                }
            )
    return plans

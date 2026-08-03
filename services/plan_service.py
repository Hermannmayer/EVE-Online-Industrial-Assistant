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

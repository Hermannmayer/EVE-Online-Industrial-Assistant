"""研究成本计算 — 拷贝(copying) / 发明(invention) 成本。

- T1 物品：拷贝成本 = Σ(拷贝材料×单价) + 安装费（EIV × SCI(copying) × 结构 + 税 + SCC）。
- T2/T3 物品：发明成本 = Σ(数据核心 invention 材料×单价) + 安装费（SCI(invention)）÷ 成功率。
- 蓝图原图 / 无制造蓝图：返回 None（不写成本）。

蓝图数据经传入的 conn（ref/bp 主库）；物品价格（adjusted_price）从 mkt 库独立查询。
"""

from __future__ import annotations

from sqlite3 import Connection

from core.constants import DEFAULT_SYSTEM_COST_INDEX
from core.container import get_container
from services import user_settings
from services.manufacturing_calculator import calc_job_cost_fees

# 默认参数：Jita 标准结构（Upwell 默认 1.0）、NPC 设施税率、Omega（无 Alpha 税）
_STRUCTURE_MULT = 1.0
_FACILITY_TAX = 0.0025
_JITA_SYSTEM_ID = 30000142


def _default_research_system_id() -> int:
    """默认科研机库所在星系；未配置 → 默认制造材料机库 → Jita。

    星系在「机库设置」对话框配置（hangars.solar_system_id），研究/制造设施跟随该星系 SCI。
    """
    try:
        settings = user_settings.load_settings()
    except Exception:
        settings = {}
    for key in ("default_research_hangar_id", "default_mat_hangar_id"):
        hid = settings.get(key)
        if not hid:
            continue
        try:
            with get_container().db.connect("user") as conn:
                row = conn.execute("SELECT solar_system_id FROM hangars WHERE id=?", (hid,)).fetchone()
            if row and row[0]:
                return int(row[0])
        except Exception:
            continue
    return _JITA_SYSTEM_ID


def _installation_fee(activity: str, eiv: float, solar_system_id: int | None) -> float:
    """研究活动安装费（EIV × SCI(活动, 设施星系) × 结构 + 税 + SCC）。

    SCI 从 reference.db 按设施星系查询；未提供星系时回退默认科研机库星系。
    """
    sci = DEFAULT_SYSTEM_COST_INDEX
    sid = int(solar_system_id) if solar_system_id else _default_research_system_id()
    try:
        with get_container().db.connect("ref") as conn:
            row = conn.execute(
                "SELECT cost_index FROM industry_system_costs WHERE solar_system_id=? AND activity=? LIMIT 1",
                (sid, activity),
            ).fetchone()
        if row and row[0]:
            sci = float(row[0])
    except Exception:
        pass
    fees = calc_job_cost_fees(eiv, sci, _STRUCTURE_MULT, _FACILITY_TAX)
    return float(fees["total_fee"])


def _prices(type_ids: list[int]) -> dict[int, float]:
    """批量取 adjusted_price（mkt 库）；缺失按 0。"""
    ids = [t for t in type_ids if t]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    with get_container().db.connect("mkt") as conn:
        rows = conn.execute(
            f"SELECT type_id, adjusted_price FROM market_prices WHERE type_id IN ({ph}) AND adjusted_price > 0",
            ids,
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def _material_cost(conn: Connection, prices: dict[int, float], blueprint_type_id: int, activity: str) -> float:
    """蓝图某活动的材料总价（调整价 × 数量）。"""
    rows = conn.execute(
        "SELECT material_type_id, quantity FROM blueprint_materials WHERE blueprint_type_id=? AND activity=?",
        (blueprint_type_id, activity),
    ).fetchall()
    total = 0.0
    for mat_id, qty in rows:
        total += prices.get(mat_id, 0.0) * float(qty or 0)
    return total


def research_cost_for_item(bp_conn: Connection, type_id: int, *, solar_system_id: int | None = None) -> float | None:
    """单个物品的研究成本（拷贝或发明）；原图/无蓝图 → None。"""
    return research_costs_batch(bp_conn, [type_id], solar_system_id=solar_system_id).get(type_id)


def research_costs_batch(
    bp_conn: Connection,
    type_ids: list[int],
    *,
    solar_system_id: int | None = None,
) -> dict[int, float | None]:
    """批量计算物品研究成本 {type_id: cost|None}（避免 N+1）。

    Args:
        bp_conn: blueprint.db 连接（blueprint_products/activities/materials 表）
        type_ids: 物品 type_id 列表
        solar_system_id: 设施所在星系（SCI 依据）；None → 默认科研机库星系 → Jita

    规则:
        - 物品是蓝图原图（自身在 blueprint_activities）→ None。
        - 无制造蓝图 → None。
        - T1（制造蓝图非发明产物）→ 拷贝成本。
        - T2/T3（制造蓝图是 invention 产物）→ 发明成本。
    """
    ids = [t for t in type_ids if t]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    # 物品 → 制造蓝图
    prod_bp = bp_conn.execute(
        f"SELECT product_type_id, blueprint_type_id FROM blueprint_products "
        f"WHERE activity='manufacturing' AND product_type_id IN ({ph})",
        ids,
    ).fetchall()
    # 物品自身是否蓝图原图
    bp_self = {
        r[0]
        for r in bp_conn.execute(
            f"SELECT blueprint_type_id FROM blueprint_activities WHERE blueprint_type_id IN ({ph})", ids
        ).fetchall()
    }
    # 发明产物集合（T2/T3 判定）
    inv_products = {
        r[0]
        for r in bp_conn.execute(
            f"SELECT product_type_id FROM blueprint_products WHERE activity='invention' AND product_type_id IN ({ph})",
            ids,
        ).fetchall()
    }
    # 材料 id（拷贝/发明活动）一并取价；按制造蓝图 id 与 T1 发明蓝图 id 查
    inv_t1_ids = {
        r[0]
        for r in bp_conn.execute(
            f"SELECT blueprint_type_id FROM blueprint_products WHERE activity='invention' AND product_type_id IN ({ph})",
            ids,
        ).fetchall()
    }
    mat_bp_ids = {b for _p, b in prod_bp} | inv_t1_ids
    if mat_bp_ids:
        mat_ph = ",".join("?" * len(mat_bp_ids))
        mat_ids = {
            r[0]
            for r in bp_conn.execute(
                f"SELECT material_type_id FROM blueprint_materials "
                f"WHERE activity IN ('copying','invention') AND blueprint_type_id IN ({mat_ph})",
                tuple(mat_bp_ids),
            ).fetchall()
        }
    else:
        mat_ids = set()
    prices = _prices(list(set(ids) | mat_ids))
    result: dict[int, float | None] = {}
    for tid in ids:
        if tid in bp_self:
            result[tid] = None  # 蓝图原图不写成本
            continue
        bp_id = next((b for p, b in prod_bp if p == tid), None)
        if not bp_id:
            result[tid] = None  # 无制造蓝图
            continue
        if tid in inv_products:
            # T2/T3 → 发明成本：T1 蓝图的 invention 行（材料+成功率），产出即本物品
            t1_row = bp_conn.execute(
                "SELECT blueprint_type_id, probability FROM blueprint_products "
                "WHERE activity='invention' AND product_type_id=? LIMIT 1",
                (tid,),
            ).fetchone()
            probability = float(t1_row[1]) if t1_row and t1_row[1] else 1.0
            mat = _material_cost(bp_conn, prices, t1_row[0], "invention") if t1_row else 0.0
            fee = _installation_fee("invention", mat, solar_system_id)
            result[tid] = round((mat + fee) / max(probability, 0.01), 2)
        else:
            # T1 → 拷贝成本 = 拷贝材料 + 安装费
            mat = _material_cost(bp_conn, prices, bp_id, "copying")
            fee = _installation_fee("copying", mat, solar_system_id)
            result[tid] = round(mat + fee, 2)
    return result

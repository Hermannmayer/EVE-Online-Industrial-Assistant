"""UI 层常用数据库查询/写入的小型服务函数。

这些函数把 UI 文件中曾经直接通过 ``get_container().db.connect(...)`` 执行的
SQL/事务收敛到 services 层。UI 调用方仍可传入 ``db`` 以便测试注入和保持
原调用线程（不会把 DB 访问移到别的线程）。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.container import get_container
from services import inventory_manager
from services.name_resolver import resolve_system_name
from services.plan_aggregator import aggregate_procurement
from services.terminology import term


def _resolve_db(db):
    """返回调用方传入的 DatabaseManager；未传时使用容器中的全局实例。"""
    return db if db is not None else get_container().db


# ── 物品搜索（估价 Worker）──────────────────────────────────────


def search_item_by_name(name: str, db=None) -> dict | None:
    """按中文/英文名搜索物品，返回 {type_id, zh_name, en_name, iconID, volume} 或 None。"""
    fuzzy_name = re.sub(r"[\"\"'']+", "%", name)
    with _resolve_db(db).connect("ref") as conn:
        c = conn.cursor()
        # 精确匹配（原始名）
        c.execute(
            "SELECT type_id, zh_name, en_name, iconID, volume FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1",
            (name, name),
        )
        row = c.fetchone()
        if row:
            return {"type_id": row[0], "zh_name": row[1], "en_name": row[2], "iconID": row[3], "volume": row[4] or 0}
        # 模糊匹配（原始名）
        c.execute(
            "SELECT type_id, zh_name, en_name, iconID, volume FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
            (f"%{name}%", f"%{name}%"),
        )
        row = c.fetchone()
        if row:
            return {"type_id": row[0], "zh_name": row[1], "en_name": row[2], "iconID": row[3], "volume": row[4] or 0}
        # 引号归一化模糊匹配（引号 → % 通配符）
        if fuzzy_name != name:
            c.execute(
                "SELECT type_id, zh_name, en_name, iconID, volume FROM item"
                " WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
                (f"%{fuzzy_name}%", f"%{fuzzy_name}%"),
            )
            row = c.fetchone()
            if row:
                return {
                    "type_id": row[0],
                    "zh_name": row[1],
                    "en_name": row[2],
                    "iconID": row[3],
                    "volume": row[4] or 0,
                }
    return None


# ── 查询页搜索 Worker ──────────────────────────────────────────


def query_search_items(query: str, all_groups: list, region_id: int = 10000002, db=None) -> list[Any]:
    """查询页完整搜索：item + market_prices，返回原始行。"""
    with _resolve_db(db).connect("ref", "mkt") as conn:
        c = conn.cursor()
        like = f"%{query}%"
        group_match = None
        for gid, en, zh in all_groups:
            if (zh and query in zh) or (en and query in en):
                group_match = gid
                break

        if query.isdigit():
            c.execute(
                """
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                       mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM item i
                LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id AND mp.region_id = ?
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id AND region_id = ?)
                WHERE i.type_id = ? OR i.en_name LIKE ? OR i.zh_name LIKE ?
                ORDER BY i.type_id LIMIT 300
            """,
                (region_id, region_id, int(query), like, like),
            )
        elif group_match is not None:
            c.execute(
                """
                SELECT sub.type_id, sub.zh_name, sub.en_name, sub.en_group_name, sub.zh_group_name, sub.volume,
                       mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM (
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                    FROM item i WHERE i.group_id = ?
                    UNION
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                    FROM item i WHERE (i.en_name LIKE ? OR i.zh_name LIKE ?)
                ) sub
                LEFT JOIN mkt.market_prices mp ON sub.type_id = mp.type_id AND mp.region_id = ?
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = sub.type_id AND region_id = ?)
                ORDER BY sub.type_id LIMIT 300
            """,
                (region_id, region_id, group_match, like, like),
            )
        else:
            c.execute(
                """
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                       mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM item i
                LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id AND mp.region_id = ?
                    AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id AND region_id = ?)
                WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
                ORDER BY i.type_id LIMIT 300
            """,
                (region_id, region_id, like, like),
            )
        return c.fetchall()


def query_search_items_basic(query: str, db=None) -> list[Any]:
    """查询页降级搜索：只查 reference.item，返回原始行。"""
    with _resolve_db(db).connect("ref") as conn:
        c = conn.cursor()
        if query.isdigit():
            c.execute(
                "SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume"
                " FROM item WHERE type_id = ?",
                (int(query),),
            )
        else:
            c.execute(
                "SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume"
                " FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 100",
                (f"%{query}%", f"%{query}%"),
            )
        return c.fetchall()


def query_suggest_items(query: str, db=None) -> list[Any]:
    """候选搜索：返回 item 表原始行 (type_id, en_name, zh_name)。"""
    with _resolve_db(db).connect("ref") as conn:
        c = conn.cursor()
        q = query
        if q.isdigit():
            c.execute(
                "SELECT type_id, en_name, zh_name FROM item "
                "WHERE type_id = ? OR en_name LIKE ? OR zh_name LIKE ? "
                "ORDER BY CASE WHEN type_id = ? THEN 0 ELSE 1 END, LENGTH(en_name), type_id LIMIT 10",
                (int(q), f"%{q}%", f"%{q}%", int(q)),
            )
        else:
            c.execute(
                "SELECT type_id, en_name, zh_name FROM item "
                "WHERE en_name LIKE ? OR zh_name LIKE ? "
                "ORDER BY CASE WHEN en_name LIKE ? THEN 0"
                " WHEN zh_name LIKE ? THEN 1 ELSE 2 END,"
                " LENGTH(en_name), type_id LIMIT 10",
                (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"),
            )
        return c.fetchall()


def load_item_groups(db=None) -> list[Any]:
    """加载查询页类别列表。"""
    with _resolve_db(db).connect("ref") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name"
            " FROM item e WHERE e.group_id IS NOT NULL"
            " ORDER BY e.zh_group_name, e.en_group_name"
        )
        return c.fetchall()


# ── 星系搜索对话框 ─────────────────────────────────────────────


def has_solar_system_data(db=None) -> bool:
    """reference.solar_system 表是否已有数据。"""
    try:
        with _resolve_db(db).connect("ref") as conn:
            row = conn.execute("SELECT COUNT(*) FROM solar_system").fetchone()
            return bool(row and row[0] > 0)
    except Exception:
        return False


def search_solar_systems(query: str, db=None) -> list[tuple[int, str, float]]:
    """按名称搜索星系，返回 [(solar_system_id, display_name, security), ...]。"""
    q = (query or "").strip()
    with _resolve_db(db).connect("ref") as conn:
        if q:
            zh_ens = term.search_system_names(q)
            en_sql = "solar_system_name LIKE ?"
            params: list[Any] = [f"%{q}%"]
            if zh_ens:
                placeholders = ",".join("?" * len(zh_ens))
                en_sql += f" OR solar_system_name IN ({placeholders})"
                params.extend(zh_ens)
            cur = conn.execute(
                "SELECT solar_system_id, solar_system_name, security FROM solar_system"
                f" WHERE {en_sql} ORDER BY solar_system_name LIMIT 30",
                params,
            )
        else:
            cur = conn.execute(
                "SELECT solar_system_id, solar_system_name, security FROM solar_system "
                "ORDER BY solar_system_name LIMIT 30"
            )
        result: list[tuple[int, str, float]] = []
        for sid, _en, sec in cur.fetchall():
            display = resolve_system_name(conn, int(sid))
            result.append((int(sid), display, float(sec or 0)))
        return result


# ── 产线小助手 ─────────────────────────────────────────────────


def get_item_names_batch(type_ids: list[int], db=None) -> dict[int, str]:
    """批量查询 item 名称，返回 {type_id: zh_name or en_name or str(type_id)}。"""
    ids = list(dict.fromkeys(type_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    with _resolve_db(db).connect("ref") as conn:
        rows = conn.execute(
            f"SELECT type_id, zh_name, en_name FROM item WHERE type_id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
    return {int(tid): zh or en or str(tid) for tid, zh, en in rows}


# ── 蓝图导入 Worker ────────────────────────────────────────────


def parse_blueprint_clipboard(raw: str, conn) -> list[dict]:
    """解析 EVE 蓝图剪贴板 → [{blueprint_type_id, name, is_bpo, me, te, runs}]。

    纯函数（依赖传入的 ref/bp 连接做名称→蓝图 ID 解析）。
    行格式（Tab 分隔，与游戏全选复制一致）:
        <蓝图名或产物名>\t<ME>\t<TE>\t<流程数>\t<原图/拷贝>
    """
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    seen: Counter = Counter()  # (bpid, is_bpo, me, te, runs) → 数量（同属性多张）
    names: dict[int, str] = {}
    for line in lines:
        cols = line.split("\t")
        if len(cols) < 5:
            continue
        name_part = cols[0].strip().rstrip("*")
        if not name_part:
            continue
        try:
            me = int(cols[1].strip())
            te = int(cols[2].strip())
            runs = int(cols[3].strip())
        except ValueError:
            continue
        is_bpo = "原图" in cols[4].strip() or "原本" in cols[4].strip()
        bpid = _lookup_bpid(conn, name_part)
        if not bpid:
            continue
        key = (bpid, is_bpo, me, te, runs)
        seen[key] += 1
        if bpid not in names:
            names[bpid] = _lookup_name(conn, bpid, name_part)
    return [
        {
            "blueprint_type_id": k[0],
            "is_bpo": k[1],
            "me": k[2],
            "te": k[3],
            "runs": k[4],
            "qty": q,
            "name": names.get(k[0], ""),
        }
        for k, q in seen.items()
    ]


def parse_blueprint_clipboard_text(raw: str, db=None) -> list[dict]:
    """打开 ref/bp 连接并解析剪贴板蓝图。"""
    with _resolve_db(db).connect("ref", "bp") as conn:
        return parse_blueprint_clipboard(raw, conn.cursor())


def _lookup_bpid(c, name_part):
    """蓝图名/产物名 → blueprint_type_id（先精确匹配蓝图，再产物反查）"""
    # 1. 精确匹配 item 表，且必须是制造蓝图
    c.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name_part, name_part))
    r = c.fetchone()
    if r:
        tid = r[0]
        c.execute(
            "SELECT 1 FROM blueprint_products WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (tid,),
        )
        if c.fetchone():
            return tid
        # 命中的是产品行 → 从产品反查制造蓝图
        c.execute(
            "SELECT blueprint_type_id FROM blueprint_products"
            " WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (tid,),
        )
        r2 = c.fetchone()
        if r2:
            return r2[0]
    # 2. 产物反查：蓝图名替换 "蓝图 X" → " X" → 产物名 → 制造蓝图
    for suffix in ("蓝图 II", "蓝图 I", "蓝图 III"):
        if suffix in name_part:
            prod_name = name_part.replace(suffix, suffix.replace("蓝图", ""))
            c.execute("SELECT type_id FROM item WHERE zh_name = ? LIMIT 1", (prod_name,))
            r = c.fetchone()
            if r:
                c.execute(
                    "SELECT blueprint_type_id FROM blueprint_products"
                    " WHERE product_type_id = ?"
                    " AND activity = 'manufacturing' LIMIT 1",
                    (r[0],),
                )
                r2 = c.fetchone()
                if r2:
                    return r2[0]
            break  # 只尝试第一个匹配的后缀
    return None


def _lookup_name(c, bpid: int, fallback: str) -> str:
    """蓝图类型 ID → 显示名（找不到用剪贴板名兜底）"""
    c.execute("SELECT zh_name FROM item WHERE type_id = ?", (bpid,))
    r = c.fetchone()
    return (r[0] or fallback) if r else fallback


def apply_blueprint_diff(
    diff_rows: list[dict],
    hangar_id: int,
    mode: str = "full",
    *,
    db=None,
) -> tuple[int, int]:
    """按勾选行应用增删，返回 (added, removed)。

    Args:
        diff_rows: [{blueprint_type_id, is_bpo, me, te, runs, target_qty, row_ids}]
        mode: "full" 全量同步（target_qty 为最终目标，增删按差额）
              "incremental" 增量累加（target_qty = 现有+剪贴板，只增不减）
    """
    added = 0
    removed = 0
    with _resolve_db(db).connect("user") as uc:
        for row in diff_rows:
            key = (row["blueprint_type_id"], int(row["is_bpo"]), int(row["me"]), int(row["te"]), int(row["runs"]))
            target = int(row.get("target_qty", 0))
            row_ids = list(row.get("row_ids", []))
            if mode == "incremental":
                # 增量只加不减：目标 = 现有 + 剪贴板
                target = len(row_ids) + int(row.get("qty", 0))
            existing_cnt = len(row_ids)
            if target > existing_cnt:
                for _ in range(target - existing_cnt):
                    inventory_manager.add_blueprint(
                        hangar_id,
                        key[0],
                        is_bpo=bool(key[1]),
                        me_level=key[2],
                        te_level=key[3],
                        runs=key[4],
                        quantity=1,
                        conn=uc,
                    )
                    added += 1
            elif target < existing_cnt:
                # 删除多余（保留 row_ids 尾部，删前面多余的）
                for rid in row_ids[target - existing_cnt :]:
                    inventory_manager.delete_blueprint(rid, conn=uc)
                    removed += 1
        uc.commit()
    return added, removed


# ── 工业制造 Worker 搜索/排名 ─────────────────────────────────


def search_manufacturable_items(query: str, db=None) -> list[dict]:
    """搜索可制造物品（item 表），返回 [{type_id, zh_name, en_name}, ...]。"""
    with _resolve_db(db).connect("ref") as conn:
        c = conn.cursor()
        like = f"%{query}%"
        c.execute(
            """
            SELECT type_id, zh_name, en_name FROM item
            WHERE en_name LIKE ? OR zh_name LIKE ?
            ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                     LENGTH(en_name), type_id
            LIMIT 30
        """,
            (like, like, f"{query}%", f"{query}%"),
        )
        return [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]


def get_all_manufacturable_product_ids(db=None) -> list[int]:
    """获取所有制造活动蓝图的产品 type_id。"""
    with _resolve_db(db).connect("bp") as conn:
        rows = conn.execute(
            "SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity = 'manufacturing'"
        ).fetchall()
        return [r[0] for r in rows]


# ── 备料中采购汇总 Worker ─────────────────────────────────────


def aggregate_procurement_summary(
    plans: list[dict],
    *,
    default_mat_hangar_id: int | None = None,
    region_id: int = 10000002,
    price_type: str = "sell",
    db=None,
) -> tuple[float, float]:
    """按统计条模式聚合备料中计划的采购金额/体积。"""
    with _resolve_db(db).connect("user", "ref", "bp", "mkt") as conn:
        _rows, cost, vol = aggregate_procurement(
            conn,
            plans,
            hangar_id=None,
            default_hangar_id=default_mat_hangar_id,
            region_id=region_id,
            price_type=price_type,
        )
    return cost, vol

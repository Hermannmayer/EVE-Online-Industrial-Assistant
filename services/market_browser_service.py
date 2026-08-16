"""全物品市场浏览器数据访问 — 供 UI Worker 调用的只读查询。"""

from __future__ import annotations

from core.container import get_container

_SQL = (
    "SELECT i.market_group_id,i.type_id,i.zh_name,i.en_name,i.volume,"
    "mp.buy_price,mp.sell_price,mp.buy_volume,mp.sell_volume "
    "FROM item i "
    "LEFT JOIN mkt.market_prices mp ON mp.type_id=i.type_id "
    "AND mp.region_id=? AND mp.fetch_time=(SELECT MAX(fetch_time) "
    "FROM mkt.market_prices WHERE type_id=i.type_id AND region_id=?) "
)


def _rows_to_dicts(rows) -> list[dict]:
    r = []
    for row in rows:
        mg, tid, zh, en, vol, bp, sp, bv, sv = row
        ap = ((bp or 0) + (sp or 0)) / 2 if bp and sp else (bp or sp)
        r.append(
            {
                "mg": mg,
                "id": tid,
                "z": zh or "",
                "e": en or "",
                "v": vol or 0,
                "bp": bp,
                "sp": sp,
                "ap": ap,
                "bv": bv or 0,
                "sv": sv or 0,
            }
        )
    return r


def fetch_market_tree() -> list[dict]:
    with get_container().db.connect("ref", "bp") as conn:
        c = conn.cursor()
        c.execute("SELECT market_group_id,parent_group_id,zh_name FROM market_tree ORDER BY zh_name")
        return [{"id": i, "p": p, "n": z or f"G{i}"} for i, p, z in c.fetchall()]


def fetch_items(ids: list[int] | None, rid: int) -> list[dict]:
    with get_container().db.connect("ref", "mkt") as conn:
        c = conn.cursor()
        if ids:
            ph = ",".join("?" * len(ids))
            c.execute(_SQL + f"WHERE i.market_group_id IN ({ph}) ORDER BY i.zh_name LIMIT 2000", (rid, rid, *ids))
        else:
            c.execute(_SQL + "ORDER BY i.zh_name LIMIT 2000", (rid, rid))
        return _rows_to_dicts(c.fetchall())


def search_items(query: str, rid: int) -> list[dict]:
    q = query.strip()
    if not q:
        return []
    with get_container().db.connect("ref", "mkt", "bp") as conn:
        c = conn.cursor()
        like = f"%{q}%"
        if q.isdigit():
            sql = _SQL + "WHERE (i.type_id=? OR i.zh_name LIKE ? OR i.en_name LIKE ?)"
            sql += " ORDER BY i.zh_name LIMIT 500"
            c.execute(sql, (rid, rid, int(q), like, like))
        else:
            sql = _SQL + "WHERE (i.zh_name LIKE ? OR i.en_name LIKE ?)"
            sql += " ORDER BY CASE WHEN i.en_name LIKE ? THEN 0"
            sql += " WHEN i.zh_name LIKE ? THEN 1 ELSE 2 END, i.zh_name LIMIT 500"
            c.execute(sql, (rid, rid, like, like, f"{q}%", f"{q}%"))
        return _rows_to_dicts(c.fetchall())

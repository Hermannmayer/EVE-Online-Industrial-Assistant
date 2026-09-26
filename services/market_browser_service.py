"""全物品市场浏览器数据访问 — 供 UI Worker 调用的只读查询。"""

from __future__ import annotations

from datetime import date

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


# ══════════════════════════════════════════════════════════════
#  跨区域价差排行（贸易页「开始计算」）
# ══════════════════════════════════════════════════════════════

#: 价格类型 → `market_prices` 列名。**闭集白名单**：列名只从这里取、不碰用户输入，
#: 所以下面的 SQL 用 `format()` 填列名是安全的（值仍全部参数化）。
_PRICE_COLS = {"buy": "buy_price", "sell": "sell_price"}
#: 与价格列配套的**对手盘挂单量**列（有价格不等于有对手盘，见 `fetch_cross_region_spread`）。
_VOL_COLS = {"buy": "buy_volume", "sell": "sell_volume"}

#: INNER JOIN 保证两侧都挂过这个 type；`COALESCE > 0` 滤掉 0 与 NULL
#: （价格列可空，单侧缺价的行不该进排行）。
_SPREAD_SELECT = (
    "SELECT i.type_id, i.zh_name, i.en_name, i.volume, "
    "a.{ca} AS price_a, b.{cb} AS price_b, "
    "a.{va} AS vol_a, b.{vb} AS vol_b "
)
_SPREAD_TAIL = (
    "JOIN mkt.market_prices a ON a.type_id = i.type_id AND a.region_id = ? "
    "JOIN mkt.market_prices b ON b.type_id = i.type_id AND b.region_id = ? "
    "WHERE COALESCE(a.{ca}, 0) > 0 AND COALESCE(b.{cb}, 0) > 0"
)
#: 「全部品类」走这条：不带 CTE。写成 `(:g IS NULL OR …)` 会让 SQLite 放弃索引。
_SPREAD_SQL_ALL = _SPREAD_SELECT + "FROM item i " + _SPREAD_TAIL
#: 按市场分类筛：递归 CTE 展开子树（选中的是顶层分类，要连它全部子节点）。
_SPREAD_SQL_GROUP = (
    "WITH RECURSIVE grp(id) AS ("
    "  SELECT market_group_id FROM market_tree WHERE market_group_id IN ({ph}) "
    "  UNION "
    "  SELECT m.market_group_id FROM market_tree m JOIN grp ON m.parent_group_id = grp.id"
    ") " + _SPREAD_SELECT + "FROM item i JOIN grp ON grp.id = i.market_group_id " + _SPREAD_TAIL
)


def _spread_row(row) -> dict:
    """把 SQL 行算成排行行。**体积 ≤ 0 时每方利润为 None，不做除零。**

    `va` / `vb` 是两侧**在所选价位上的对手盘挂单量**：为 0 说明那一侧压根没有真实
    报价 —— `importers/getprices.save_prices` 会把 ESI `/markets/prices/` 的全局均价
    作为兜底混进 `market_prices`，那种行的 volume 是 0，价格看着很高却无人成交。
    界面据此提供「只看有对手盘的」筛选。
    """
    tid, zh, en, vol, pa, pb, va, vb = row
    price_a = float(pa or 0)
    price_b = float(pb or 0)
    volume = float(vol or 0)
    spread = price_b - price_a
    return {
        "id": int(tid),
        "z": zh or "",
        "e": en or "",
        "v": volume,
        "pa": price_a,
        "pb": price_b,
        "spread": spread,
        "pm3": (spread / volume) if volume > 0 else None,
        "va": int(va or 0),
        "vb": int(vb or 0),
    }


def fetch_cross_region_spread(
    region_a: int,
    region_b: int,
    side_a: str = "sell",
    side_b: str = "buy",
    group_ids: list[int] | None = None,
) -> list[dict]:
    """A → B 全品类价差排行。

    `side_*` 取 `"buy"` / `"sell"`，决定该侧用买单价还是卖单价。默认「从 A 的卖单
    买入、卖到 B 的买单」—— 与 `scoring_service` 的 buy/sell price_type 口径一致。
    `group_ids` 是 `reference.db.market_tree` 的顶层分类 id，空/None 表示全部品类。
    """
    col_a = _PRICE_COLS[side_a]
    col_b = _PRICE_COLS[side_b]
    fmt = {"ca": col_a, "cb": col_b, "va": _VOL_COLS[side_a], "vb": _VOL_COLS[side_b]}
    with get_container().db.connect("ref", "mkt") as conn:
        c = conn.cursor()
        if group_ids:
            ph = ",".join("?" * len(group_ids))
            c.execute(
                _SPREAD_SQL_GROUP.format(**fmt, ph=ph),
                (*group_ids, region_a, region_b),
            )
        else:
            c.execute(_SPREAD_SQL_ALL.format(**fmt), (region_a, region_b))
        return [_spread_row(r) for r in c.fetchall()]


def fetch_hub_fetch_time(region_ids: list[int]) -> dict[int, str]:
    """各贸易中心最新价格的抓取时间 → `{region_id: "YYYY-MM-DD HH:MM:SS"}`。

    用来在界面上如实标出「这份价差是拿什么时候的价算的」—— 5 个中心的刷新节奏
    并不一致，混着新旧价看排行会误判。
    """
    if not region_ids:
        return {}
    ph = ",".join("?" * len(region_ids))
    with get_container().db.connect("mkt") as conn:
        c = conn.cursor()
        c.execute(
            f"SELECT region_id, MAX(fetch_time) FROM market_prices WHERE region_id IN ({ph}) GROUP BY region_id",
            tuple(int(r) for r in region_ids),
        )
        return {int(rid): str(ts) for rid, ts in c.fetchall() if ts}


def _day_span(d0: str, d1: str) -> int:
    """两个 `YYYY-MM-DD` 之间的天数差。"""
    return (date.fromisoformat(d1) - date.fromisoformat(d0)).days


def order_change_per_day(
    first_volume: int | None,
    last_volume: int | None,
    first_date: str | None,
    last_date: str | None,
    snapshots: int,
) -> float | None:
    """窗口内挂单量的**日均净变化**。

    正数 = 挂单在减少（有人在吃单，市场在动）；负数 = 挂单在堆积（卖不动）。
    快照不足 2 天、或两次快照落在同一天 → 返回 None（算不出变化）。

    ⚠️ 这是**估算**，不是真实成交量：净减少也可能来自撤单。
    """
    if snapshots < 2 or first_volume is None or last_volume is None:
        return None
    if not first_date or not last_date:
        return None
    span = _day_span(first_date, last_date)
    if span <= 0:
        return None
    return (int(first_volume) - int(last_volume)) / span


#: 每个 type_id 一行：首末两天的卖单量、首末日期、快照条数。
#:
#: 先用一次 GROUP BY 取 MIN(date)/MAX(date)/COUNT(*)，再按 (type_id, date) 等值 JOIN 回快照表
#: 取首末挂单量。旧写法的三个窗口函数（rn/rn_desc/cnt）会让 SQLite 对同一分区跑三趟
#: co-routine、建三个临时 B 树；首末两天各只有一行，两个 JOIN 不会放大行数。
_ORDER_CHANGE_SQL = (
    "WITH b AS ("
    "  SELECT type_id, MIN(date) AS d0, MAX(date) AS d1, COUNT(*) AS cnt"
    "  FROM market_volume_snapshots"
    "  WHERE region_id = ? AND date >= date('now', ?)"
    "  GROUP BY type_id"
    ") "
    "SELECT b.type_id, f.sell_volume, l.sell_volume, b.d0, b.d1, b.cnt"
    " FROM b"
    " JOIN market_volume_snapshots f ON f.type_id = b.type_id AND f.region_id = ? AND f.date = b.d0"
    " JOIN market_volume_snapshots l ON l.type_id = b.type_id AND l.region_id = ? AND l.date = b.d1"
)


def fetch_hub_order_change(region_id: int, days: int = 7) -> dict[int, dict]:
    """目的贸易中心 B 侧卖单挂单量的近日变化 → `{type_id: {"per_day": …, "days": …}}`。

    数据来自 `market_volume_snapshots`（每次「更新价格」写一条当日快照），
    **零网络请求**；快照不足 2 天的物品不下发 `per_day`（调用方显示占位）。

    ⚠️ 只算卖单侧：要回答的是「挂上去之后卖不卖得动」，与买单侧无关。
    """
    with get_container().db.connect("mkt") as conn:
        c = conn.cursor()
        # 4 个占位符：窗口谓词一次 + 两个等值 JOIN 各带上 region_id（不能省，否则会串中心）
        since = f"-{max(1, int(days))} day"
        c.execute(_ORDER_CHANGE_SQL, (region_id, since, region_id, region_id))
        rows = c.fetchall()
    out: dict[int, dict] = {}
    for tid, first_v, last_v, d0, d1, cnt in rows:
        n = int(cnt or 0)
        out[int(tid)] = {
            "per_day": order_change_per_day(first_v, last_v, d0, d1, n),
            "days": n,
        }
    return out

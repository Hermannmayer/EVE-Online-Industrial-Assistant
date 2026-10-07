"""BOM 传导链 —— 从某个产物逐级下钻：用量、成本占比、30/90/180 天涨跌、「未跟涨度」。

展开**复用** `services/bom_expander.expand_bom`（不自己重写 BOM 递归）；本模块只补三样它
不管的东西：**原始用量**、**逐级成本占比**、**材料的价格涨幅**。

价格口径（**两种来源，每行都用 `source` 标出来**）：

- `source="history"`：`market.db.price_history` 的**成交均价**（与指数、异动榜同一口径）。
- `source="snapshot"`：`market.db.market_volume_snapshots` 的**挂单卖价**（该日快照的
  `sell_price`）。**口径差异**：挂单价不是成交价，一个人挂/撤就能推动（计划 §2.2 第 2 条），
  所以它只在「该材料本地没有成交历史」时兜底 —— 材料往往只有挂单价，没有 `price_history`。
  另外挂单价**没有成交量**，窗口均价用算术平均（成交均价按成交量加权），两者数值不可直接比较。
- 两者都没有 → `price=None`、`source=None`（不拿 0 冒充「免费」）。

涨幅窗口与异动榜同一套：近 W 个日历天均价 ÷ **前一个等长窗口**均价 − 1；某个窗口没有
记录 → `None`。

DAG（同一材料出现在多条支路）按 `typeId` **合并成一行**并用 `occurs` 记出现次数；展示行取
`(level, parent_type_id)` 最小的一次出现（最浅、最靠前），这样同一次数据下结果稳定。
`not_caught_up` 是**父项级**的残差 = 父项 30 天涨幅 − Σ(子项 cost_share × 子项 30 天涨幅)，
同一个父项下的所有子项行共享同一个值；正数 = 子项还没跟上父项。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from services.bom_expander import expand_bom
from services.database_manager import get_db
from services.name_resolver import resolve_item_names_batch

#: 吉他（The Forge）—— 与 `services.price_history.REGION_ID` 同值
JITA_RID = 10000002

#: 每行给出的涨幅窗口（天）
CHG_WINDOWS = (30, 90, 180)

#: `IN (...)` 分批上限（SQLite 变量上限的保守取值，与 blueprint_repository 同口径）
_SQL_PARAM_CHUNK = 900

#: 价格序列的一个点：(日期, 价格, 加权权重)
_Point = tuple[str, float, float]


def _table_exists(conn, name: str) -> bool:
    """market.db 里有没有这张表。

    必须写 `mkt.sqlite_master`：本服务的连接主库是 `ref`，裸 `sqlite_master` 只会看到
    `reference.db`（踩过：`price_history` 明明有数据，这里却判成没有表，于是全链 `source=None`）。
    """
    return conn.execute("SELECT 1 FROM mkt.sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _chunks(ids: list[int]) -> Iterator[list[int]]:
    for start in range(0, len(ids), _SQL_PARAM_CHUNK):
        yield ids[start : start + _SQL_PARAM_CHUNK]


def _fetch_series(conn, ids: list[int], region_id: int, lookback_start: str) -> dict[int, tuple[str, list[_Point]]]:
    """`{type_id: (source, [(date, price, weight)])}` —— 成交均价优先，挂单价兜底。

    `weight` 是窗口加权用的权重：成交均价用成交量；挂单价没有成交量，权重固定 0（= 算术平均）。
    """
    out: dict[int, tuple[str, list[_Point]]] = {}
    if _table_exists(conn, "price_history"):
        history: dict[int, list[_Point]] = {}
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            for tid, day, avg, vol in conn.execute(
                f"SELECT type_id, date, average, volume FROM price_history "
                f"WHERE region_id = ? AND type_id IN ({ph}) AND date >= ? ORDER BY type_id, date",
                (region_id, *chunk, lookback_start),
            ).fetchall():
                history.setdefault(int(tid), []).append((str(day), float(avg), float(vol or 0)))
        out.update({tid: ("history", rows) for tid, rows in history.items()})

    missing = [tid for tid in ids if tid not in out]
    if missing and _table_exists(conn, "market_volume_snapshots"):
        snapshots: dict[int, list[_Point]] = {}
        for chunk in _chunks(missing):
            ph = ",".join("?" * len(chunk))
            for tid, day, sell in conn.execute(
                f"SELECT type_id, date, sell_price FROM market_volume_snapshots "
                f"WHERE region_id = ? AND type_id IN ({ph}) AND date >= ? AND sell_price > 0 "
                f"ORDER BY type_id, date",
                (region_id, *chunk, lookback_start),
            ).fetchall():
                snapshots.setdefault(int(tid), []).append((str(day), float(sell), 0.0))
        out.update({tid: ("snapshot", rows) for tid, rows in snapshots.items()})
    return out


def _window_price(points: list[_Point], start: str, end: str) -> float | None:
    """窗口均价：有权重就加权，权重全 0（挂单价）就算术平均，窗口内无记录给 None。"""
    selected = [(price, weight) for day, price, weight in points if start <= day <= end]
    if not selected:
        return None
    total_weight = sum(weight for _, weight in selected)
    if total_weight > 0:
        return sum(price * weight for price, weight in selected) / total_weight
    return sum(price for price, _ in selected) / len(selected)


def _change_pct(points: list[_Point], window: int, today: date) -> float | None:
    """近 `window` 天均价 vs 前一个等长窗口均价的涨幅（%）；缺任一窗口给 None。"""
    recent = _window_price(points, (today - timedelta(days=window - 1)).isoformat(), today.isoformat())
    base = _window_price(
        points,
        (today - timedelta(days=2 * window - 1)).isoformat(),
        (today - timedelta(days=window)).isoformat(),
    )
    if recent is None or base is None or base <= 0:
        return None
    return round((recent / base - 1.0) * 100.0, 2)


def get_transmission_chain(
    type_id: int,
    depth: int = 2,
    region_id: int = JITA_RID,
    _db=None,
) -> list[dict]:
    """把 `type_id` 的 BOM 逐级展开成传导链。

    返回 `[{level, parent_type_id, typeId, name, qty, price, cost_share, chg30, chg90,
    chg180, not_caught_up, source, occurs}]`，`level` 从 1（直接材料）开始，只到 `depth` 层：

    - `qty`：该材料在**父项**制造蓝图里的原始用量（`activity='manufacturing'`，取不到退回
      `'reaction'`）；查不到给 `None`（**不是** `expand_bom` 那把已含 ME 损耗的用量）
    - `cost_share`：`qty × 材料价 ÷ 父项材料成本合计`（同级子项之和为 1）；父项任何一个
      子项缺价、或父项成本为 0 → `None`
    - `not_caught_up`：父项 30 天涨幅 − Σ(子项 `cost_share` × 子项 30 天涨幅)；算不出给 `None`

    说明：BOM 展开由 `expand_bom` 完成（它自己从容器取 ref/mkt/bp 库与定价服务），
    `_db` 只影响本模块自己的 SQL —— 测试里要同时 patch `services.bom_expander._default_db`。
    """
    levels = max(1, int(depth))
    root_id = int(type_id)
    tree = expand_bom(root_id, quantity=1, bp_me=0, max_depth=levels)["tree"]
    if tree is None:
        return []

    # 全部父子边（含 depth+1 层：第 depth 层节点的 cost_share 要用到它们的孩子价）
    edges: list[tuple[int, int, int]] = []

    def _walk(node) -> None:
        for child in node.children:
            edges.append((node.type_id, child.type_id, child.depth))
            _walk(child)

    _walk(tree)
    visible = [edge for edge in edges if 1 <= edge[2] <= levels]
    if not visible:
        return []

    today = date.today()
    lookback_start = (today - timedelta(days=2 * max(CHG_WINDOWS) - 1)).isoformat()
    involved = sorted({root_id} | {child for _, child, _ in edges} | {parent for parent, _, _ in edges})

    conn_mgr = _db or get_db()
    with conn_mgr.connect("ref", "mkt", "bp") as conn:
        # 1) 原始用量：manufacturing 优先，取不到（没有该活动的材料行）退回 reaction。
        #    蓝图查找必须走 `blueprint_reader.get_blueprint_products`（`bom_expander` 那条
        #    展开链也走它）：同一个产物可能挂多张蓝图（实测制造 4 个、反应 1 个），
        #    两边查不同的蓝图就会拿到与展开树不一致的用量；而且 SDE 里有两张 CCP **测试蓝图**
        #    （碳化钨 16672 同时挂 45732「Test Reaction Blueprint」20/轮 与 46207 真实配方
        #    10000/轮），手写 `... LIMIT 1` 无排序会命中测试蓝图。
        from services.blueprint_reader import get_blueprint_products

        qty: dict[tuple[int, int], float] = {}
        for parent_id in {parent for parent, _, _ in edges}:
            for activity in ("manufacturing", "reaction"):
                bp_row = get_blueprint_products(conn, parent_id, activity)
                if not bp_row:
                    continue
                materials = conn.execute(
                    "SELECT material_type_id, quantity FROM bp.blueprint_materials "
                    "WHERE blueprint_type_id = ? AND activity = ?",
                    (int(bp_row[0]), activity),
                ).fetchall()
                if materials:
                    for mat_id, quantity in materials:
                        qty[(parent_id, int(mat_id))] = float(quantity)
                    break

        # 2) 价格来源与 30/90/180 天涨幅
        series = _fetch_series(conn, involved, region_id, lookback_start)
        price: dict[int, float | None] = {}
        source: dict[int, str | None] = {}
        change: dict[int, dict[int, float | None]] = {}
        for tid in involved:
            entry = series.get(tid)
            if not entry:
                price[tid], source[tid] = None, None
                change[tid] = dict.fromkeys(CHG_WINDOWS)
                continue
            src, points = entry
            source[tid] = src
            price[tid] = round(points[-1][1], 2)
            change[tid] = {window: _change_pct(points, window, today) for window in CHG_WINDOWS}

        # 3) 每个父项的「子项成本占比」与「未跟涨度」
        children: dict[int, list[tuple[int, float | None]]] = {}
        for parent_id, child_id, _level in edges:
            children.setdefault(parent_id, []).append((child_id, qty.get((parent_id, child_id))))

        shares_of: dict[int, dict[int, float] | None] = {}
        for parent_id, kids in children.items():
            known: list[tuple[int, float, float]] = []
            for child, quantity in kids:
                unit = price.get(child)
                if quantity is None or unit is None:
                    break  # 有一个子项缺价 → 父项成本算不全 → 整组 cost_share 都给 None
                known.append((child, quantity, unit))
            if not known or len(known) != len(kids):
                shares_of[parent_id] = None
                continue
            cost = sum(quantity * unit for _, quantity, unit in known)
            shares_of[parent_id] = (
                {child: quantity * unit / cost for child, quantity, unit in known} if cost > 0 else None
            )

        residual_of: dict[int, float | None] = {}
        for parent_id, kids in children.items():
            shares = shares_of[parent_id]
            parent_chg = change.get(parent_id, {}).get(30)
            child_changes = {child: change.get(child, {}).get(30) for child, _ in kids}
            if shares is None or parent_chg is None or any(value is None for value in child_changes.values()):
                residual_of[parent_id] = None
                continue
            weighted = sum(shares[child] * value for child, value in child_changes.items() if value is not None)
            residual_of[parent_id] = round(parent_chg - weighted, 2)

        # 4) 按 typeId 合并 DAG 重复，`occurs` 记总出现次数
        rows: dict[int, dict] = {}
        occurs: dict[int, int] = {}
        for parent_id, child_id, level in visible:
            occurs[child_id] = occurs.get(child_id, 0) + 1
            previous = rows.get(child_id)
            if previous is not None and (previous["level"], previous["parent_type_id"]) <= (level, parent_id):
                continue  # 已有更浅/更靠前的出现，保留它
            shares = shares_of.get(parent_id)
            rows[child_id] = {
                "level": level,
                "parent_type_id": parent_id,
                "typeId": child_id,
                "name": "",
                "qty": qty.get((parent_id, child_id)),
                "price": price.get(child_id),
                "cost_share": round(shares[child_id], 4) if shares else None,
                "chg30": change.get(child_id, {}).get(30),
                "chg90": change.get(child_id, {}).get(90),
                "chg180": change.get(child_id, {}).get(180),
                "not_caught_up": residual_of.get(parent_id),
                "source": source.get(child_id),
            }

        # 展示顺序：先按 level，再按该 typeId **第一次**出现的位置（DAG 重复时不能取后面的位置，
        # 否则被合并的那一行会被挪到别的支路后面 —— 这里踩过：300 取到第 4 条边的下标，
        # 于是排到了 400 后面）
        rank: dict[int, int] = {}
        for index, (_, child_id, _) in enumerate(visible):
            rank.setdefault(child_id, index)
        out = sorted(rows.values(), key=lambda row: (row["level"], rank[row["typeId"]]))
        for row in out:
            row["occurs"] = occurs[row["typeId"]]
        names = resolve_item_names_batch(conn, [row["typeId"] for row in out])
        for row in out:
            row["name"] = names.get(row["typeId"], str(row["typeId"]))
        return out


__all__ = ["CHG_WINDOWS", "JITA_RID", "get_transmission_chain"]

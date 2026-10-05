"""大盘指数计算服务 —— CCP 四指数（MPI/PPPI/SPPI/CPI 代理）+ PLEX 锚。

口径来源：`docs/dev/market-monitor-plan.md` §2（CCP 2012 价格指数 dev blog + 2019 MER + 薄市场指数方法论）。
本模块只用 **成交均价**（`market.db.price_history.average`），**不用挂单价** —— 一个人挂/撤单就能推动挂单价。

五条线
------
==================  ==========================================================================
``mpi``             固定 8 种矿物（:data:`MPI_TYPES`），与 CCP MPI 一致
``pppi``            初级投入品：被 manufacturing/reaction 当材料，**且它供入的产物本身又被当材料**
                    （用途层级 ≥2，近似 CCP 的 ore/moon/PI/发明用品）
``sppi``            次级投入品：被当材料，但供入的产物**不再被当材料**（直接供给消费品）
``cpi``             消费品（代理）：有成交、不被任何蓝图当材料，按近 30 天成交额取 top-:data:`CPI_TOP_N`
``plex``            固定 44992（ISK 锚）
==================  ==========================================================================

算法（逐条对应计划 §2.2）
--------------------------
1. **准入**：近 :data:`REBALANCE_DAYS` 个日历天成交额 > :data:`MIN_TURNOVER_ISK`（即 >0）
   **且**覆盖天数 ≥ :data:`MIN_COVERED_DAYS`。不满足的成员当日不参与（权重 0）。
2. **单成分日收益**：`当日成交均价 ÷ 该成员此前最近一次成交均价 − 1`；参考价间隔超过
   :data:`RETURN_GAP_DAYS` 天视为「已不是日收益」→ 当日不参与。再按 :data:`RETURN_CLAMP`
   截断 ±20%（超出按 ±20% 计）。
3. **成分内聚合**：参与成员的**加权中位数**（不是均值 —— 抗单笔异常）。权重见第 4 条。
4. **权重**：该成员**当日**往前 :data:`REBALANCE_DAYS` 个日历天的成交额（`volume × average`），
   经 :data:`WEIGHT_CAP`（25%）单成分上限后按合计归一化 —— 30 天滚动再平衡。
5. **逐日累乘**：基期 = 首个可算日 = :data:`BASE_VALUE`（100），之后
   `I_t = I_{t-1} × (1 + 当日加权中位数收益)`。成分换入换出只改变「当日参与集合与权重」，
   **不重设基期**，所以成分变更日天然不跳变（这就是链式拼接，见计划 §2.2.6）。

口径备注（实现时做的取舍，逐条写清）
------------------------------------
- **PPPI 判定方向**：计划 §3 的伪代码 `product_of(mat) ∈ materials` 读作「mat 供入的蓝图产物
  是否还被当材料」，即 `blueprint_materials × blueprint_products` 按 (blueprint_type_id, activity)
  自连接后看 `product_type_id` 是否在材料集合里。这与计划 §2.1 的「它的产物又被当材料（层级 ≥2）」
  一致；不是「mat 自己是否由蓝图产出」（矿物由精炼产出，那样会把三钛合金错误地踢出初级品）。
- **固定指数不因准入阈值掉成员**：MPI/PLEX 的成员表恒为固定集合（不满足准入的权重记 0），
  以守住「MPI = 8 矿固定」；PPPI/SPPI/CPI 的成员表只列当日有正权重的成员。
- **CPI 篮子**：按「最新 30 天」的成交额取 top-:data:`CPI_TOP_N`（当前篮子）；
  篮子内每个历史日的权重仍是各日自己的 30 天滚动权重。
- **`days` 字段** = 该指数已算出的点数（`points` 长度），`base_date` = 首个点日期。
- **数据不足一律 `None`**（不用 0 冒充）：少于 2 个点 → `value`/涨跌全 `None`；
  涨跌窗口没有覆盖到对应日历天 → 该窗口 `None`。

物化缓存
--------
:func:`refresh_index_daily` 把五个指数的逐日点位写进 `market.db.market_index_daily`
（market.db 是可重建缓存，故 DDL 直接建表、不走 `schema_migrations`，同 `price_history` 先例）。
表的 `type_id` 列存的是指数的**保留负数 id**（:data:`INDEX_TYPE_IDS`，真实 EVE type_id 恒为正），
`price` = 指数点位，`volume` = 当日成员成交额；`get_index_cards` / `get_index_series`
优先读这张表，表里没有该指数时退化为实时计算（不写库）。
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import NamedTuple

from services.database_manager import get_db

#: Jita（The Forge）—— 目前唯一历史天数够长的中心（计划 §6 风险表）
JITA_RID = 10000002

INDEX_KEYS: tuple[str, ...] = ("mpi", "pppi", "sppi", "cpi", "plex")

INDEX_LABELS: dict[str, str] = {
    "mpi": "矿物指数 (MPI)",
    "pppi": "初级投入品 (PPPI)",
    "sppi": "次级投入品 (SPPI)",
    "cpi": "消费品 (CPI·代理)",
    "plex": "PLEX (全服统一价)",
}

#: 物化表里「指数本身」用的保留 `type_id`。真实 EVE type_id 恒为正数，这里用负数区分合成行。
INDEX_TYPE_IDS: dict[str, int] = {"mpi": -1, "pppi": -2, "sppi": -3, "cpi": -4, "plex": -5}

#: MPI 固定 8 矿（与 CCP MPI 完全一致）
MPI_TYPES: tuple[int, ...] = (34, 35, 36, 37, 38, 39, 40, 11399)

#: PLEX 锚
PLEX_TYPE_ID = 44992

#: 用途层级判定只看这两个活动（与计划 §3 一致）
BASED_ACTIVITIES: tuple[str, str] = ("manufacturing", "reaction")

#: 成员来源（`get_index_series` 的 `members[].source`）：
#: ``fixed`` 固定篮子 / ``tier`` 蓝图层级推导 / ``liquidity`` 流动性（成交额 top-N）
MEMBER_SOURCES: dict[str, str] = {
    "mpi": "fixed",
    "pppi": "tier",
    "sppi": "tier",
    "cpi": "liquidity",
    "plex": "fixed",
}

#: 基期点位（首个可算日 = 100）
BASE_VALUE = 100.0

#: 权重/准入的滚动窗口（日历天）—— 30 天滚动再平衡
REBALANCE_DAYS = 30

#: 准入阈值 ①：近 REBALANCE_DAYS 天成交额必须 **大于** 该值（0 = 有成交额即可）
MIN_TURNOVER_ISK = 0.0

#: 准入阈值 ②：近 REBALANCE_DAYS 天必须有成交的天数下限（薄市场抗噪，计划 §2.2.1）
MIN_COVERED_DAYS = 5

#: CPI 代理规模（有成交、不被当材料，按近 30 天成交额取前 N）—— 计划 §8.2 拍板默认 300
CPI_TOP_N = 300

#: 单成分权重上限（超过则按上限计，再按合计归一化）—— 计划 §2.2.4
WEIGHT_CAP = 0.25

#: 单成分日收益截断（去极值）—— 计划 §2.2.7
RETURN_CLAMP = 0.20

#: 参考价间隔上限：超过这么多天没成交，价格变化不再是「日收益」（当日不参与）
RETURN_GAP_DAYS = 30

#: 装载窗口：最长卡片窗口 180 天 + 权重窗口 30 天 + 余量，用于控制内存与 SQL 规模
LOAD_WINDOW_DAYS = 220

#: 一次 SQL 里 `IN (...)` 的参数个数上限（SQLite 变量上限的保守取值，与 blueprint_repository 同口径）
_SQL_CHUNK = 900

#: 卡片涨跌窗口：`chg1` 用「上一个点」，其余按日历天回看
CHG_WINDOWS: tuple[tuple[str, int], ...] = (
    ("chg1", 1),
    ("chg7", 7),
    ("chg30", 30),
    ("chg90", 90),
    ("chg180", 180),
)

#: `market_index_daily` 建表语句（market.db 是可重建缓存，不走 schema_migrations）
MARKET_INDEX_DDL = """
    CREATE TABLE IF NOT EXISTS market_index_daily (
        type_id INTEGER NOT NULL,
        region_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        price REAL NOT NULL,
        volume INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (type_id, region_id, date)
    )
"""


class _IndexPoints(NamedTuple):
    """一条指数的计算结果：逐日点位 + 最后一个指数日的成分权重。"""

    points: list[dict]
    weights: dict[int, tuple[float, bool]]


# ════════════════════════════════════════════════════════════════
#  纯计算（可单独测）
# ════════════════════════════════════════════════════════════════


def clamp_return(value: float | None) -> float | None:
    """单成分日收益去极值：超过 :data:`RETURN_CLAMP`（±20%）按 ±20% 计。"""
    if value is None:
        return None
    if value > RETURN_CLAMP:
        return RETURN_CLAMP
    if value < -RETURN_CLAMP:
        return -RETURN_CLAMP
    return value


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """成交量加权中位数（权重非正的样本不参与）。

    - 升序累加权重，取首个「累计权重 ≥ 合计一半」的样本值（统计上的加权中位数）；
    - 累计权重**恰好**落在两样本交界处（偶数个等权时必然如此）→ 取两者算术平均，
      于是等权退化为标准中位数（`[1, 2, 3, 4]` → `2.5`）；
    - 没有正权重样本 → `None`（**不用 0 冒充**）。
    """
    pairs = sorted((float(v), float(w)) for v, w in zip(values, weights, strict=True) if w > 0)
    if not pairs:
        return None
    total = sum(w for _v, w in pairs)
    if total <= 0:  # pragma: no cover - pairs 里 w>0 时不可能为真，留作除零护栏
        return None
    half = total / 2.0
    tolerance = 1e-12 * max(1.0, total)
    cum = 0.0
    for i, (value, weight) in enumerate(pairs):
        cum += weight
        if cum > half + tolerance:
            return value
        if abs(cum - half) <= tolerance:
            nxt = pairs[i + 1][0] if i + 1 < len(pairs) else value
            return (value + nxt) / 2.0
    return pairs[-1][0]


def cap_weights[K: Hashable](raw: Mapping[K, float]) -> dict[K, tuple[float, bool]]:
    """成交额权重：单成分上限 :data:`WEIGHT_CAP`（25%）后按合计归一化。

    返回 `{key: (归一化权重, 是否触顶)}`；上限 = `WEIGHT_CAP × 原始合计`，原始值超过即
    `capped=True`。权重合计 ≤ 0（或没有正权重）→ `{}`（调用方按「当日无可算收益」处理）。

    ⚠️ 触顶成员归一化后可能**再次**超过 25%（上限是「先夹后归一」的一次性口径，不是迭代上限）：
    多成员同时触顶时各自按夹后的合计分摊。只有一个成员时它也必然记为 `capped=True`（原始值
    100% > 25% 的上限），这是该口径的字面结果。
    """
    positive = {key: float(weight) for key, weight in raw.items() if weight > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    cap = WEIGHT_CAP * total
    clipped = {key: min(weight, cap) for key, weight in positive.items()}
    clipped_total = sum(clipped.values())
    if clipped_total <= 0:  # pragma: no cover - 正权重夹后不可能为 0，除零护栏
        return {}
    return {key: (weight / clipped_total, positive[key] > cap) for key, weight in clipped.items()}


def _build_index(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int]) -> _IndexPoints:
    """把「成员 → 逐日 `(date, average, volume)`」链式累乘成指数。

    `obs` 的每个成员序列必须按日期升序。算法见模块 docstring 第 1~5 条；
    只有「当日有成交均价 + 参考价可用 + 通过准入」的成员参与当日加权中位数。
    """
    member_ids = sorted({int(m) for m in members})
    day_rows: dict[str, list[tuple[int, int]]] = {}
    turnovers: dict[int, list[float]] = {}
    returns: dict[int, list[float | None]] = {}
    windows: dict[int, tuple[list[float], list[int]]] = {}
    #: 该成员**完全没有成交量**（全服统一价品种）→ 只按覆盖天数准入、权重等权
    price_only: dict[int, bool] = {}

    for tid in member_ids:
        rows = list(obs.get(tid) or [])
        if len(rows) < 2:
            continue  # 单点算不出收益，也无法构成指数
        ords = [date.fromisoformat(row[0]).toordinal() for row in rows]
        avgs = [float(row[1]) for row in rows]
        turns = [float(row[1]) * float(row[2]) for row in rows]

        member_returns: list[float | None] = [None]
        for i in range(1, len(rows)):
            gap_ok = ords[i] - ords[i - 1] <= RETURN_GAP_DAYS
            base = avgs[i - 1]
            member_returns.append(clamp_return(avgs[i] / base - 1.0) if gap_ok and base > 0 else None)

        # 每行的「往前 REBALANCE_DAYS 个日历天（含当日）」成交额与覆盖天数：双指针 + 前缀和
        prefix = [0.0]
        for turn in turns:
            prefix.append(prefix[-1] + turn)
        win_turn = [0.0] * len(rows)
        win_cov = [0] * len(rows)
        left = 0
        for i in range(len(rows)):
            while ords[i] - ords[left] >= REBALANCE_DAYS:
                left += 1
            win_turn[i] = prefix[i + 1] - prefix[left]
            win_cov[i] = i + 1 - left

        turnovers[tid] = turns
        returns[tid] = member_returns
        windows[tid] = (win_turn, win_cov)
        # 全服统一价品种（PLEX）在我们的数据里**没有成交量**（`/markets/prices/` 只给价），
        # 成交额权重恒为 0 → 会被下面的「成交额门槛」整条筛掉。它本身就是**固定锚**，
        # 不是「按交易活跃度加权」的对象：只按覆盖天数准入、权重按等权给。
        price_only[tid] = not any(turns)
        for i, row in enumerate(rows):
            day_rows.setdefault(row[0], []).append((tid, i))

    points: list[dict] = []
    level: float | None = None
    last_weights: dict[int, tuple[float, bool]] = {}

    for day in sorted(day_rows):
        day_turnover = 0.0
        day_returns: dict[int, float] = {}
        raw_weights: dict[int, float] = {}
        for tid, i in day_rows[day]:
            day_turnover += turnovers[tid][i]
            ret = returns[tid][i]
            if ret is None:
                continue
            win_turn, win_cov = windows[tid]
            if price_only.get(tid):
                if win_cov[i] < MIN_COVERED_DAYS:
                    continue
                day_returns[tid] = ret
                raw_weights[tid] = 1.0
                continue
            if win_turn[i] <= MIN_TURNOVER_ISK or win_cov[i] < MIN_COVERED_DAYS:
                continue
            day_returns[tid] = ret
            raw_weights[tid] = win_turn[i]

        weights = cap_weights(raw_weights)
        if not weights:
            continue
        aggregate = weighted_median(
            [day_returns[tid] for tid in weights],
            [weight for weight, _capped in weights.values()],
        )
        if aggregate is None:
            continue

        # 首个可算日就是基期（100），当日收益从**下一个**指数日开始计入
        level = BASE_VALUE if level is None else level * (1.0 + aggregate)
        points.append({"date": day, "value": level, "volume": int(round(day_turnover))})
        last_weights = dict(weights)

    return _IndexPoints(points=points, weights=last_weights)


def _price_change(rows: Sequence[tuple[str, float, int]], days: int) -> float | None:
    """成员自身近 `days` 个日历天的成交均价涨幅（%）—— 数据不足 → `None`。"""
    if len(rows) < 2:
        return None
    cutoff = date.fromisoformat(rows[-1][0]).toordinal() - days
    base: float | None = None
    for item in rows:
        if date.fromisoformat(item[0]).toordinal() <= cutoff:
            base = float(item[1])
        else:
            break
    if base is None or base <= 0:
        return None
    return (float(rows[-1][1]) / base - 1.0) * 100.0


def _last_price(rows: Sequence[tuple[str, float, int]], anchor: date | None) -> float | None:
    """成员在 `anchor` 日（含）之前**最近一次**成交均价；没有可用观测 → `None`（不用 0 冒充）。"""
    if anchor is None:
        return None
    last: float | None = None
    limit = anchor.toordinal()
    for day, average, _volume in rows:
        if date.fromisoformat(day).toordinal() > limit:
            break
        last = float(average)
    return last


def _weights_at(
    obs: Mapping[int, Sequence[tuple[str, float, int]]],
    members: Iterable[int],
    anchor: date,
) -> dict[int, tuple[float, bool]]:
    """以 `anchor` 为最后一天，算成员表用的 30 天成交额权重（准入 + 25% 上限 + 归一化）。"""
    last = anchor.toordinal()
    first = last - (REBALANCE_DAYS - 1)
    raw: dict[int, float] = {}
    for tid in members:
        covered = 0
        turnover = 0.0
        for day, average, volume in obs.get(tid) or []:
            ordinal = date.fromisoformat(day).toordinal()
            if ordinal < first or ordinal > last:
                continue
            covered += 1
            turnover += float(average) * float(volume)
        if turnover > MIN_TURNOVER_ISK and covered >= MIN_COVERED_DAYS:
            raw[tid] = turnover
    return cap_weights(raw)


# ════════════════════════════════════════════════════════════════
#  数据读取
# ════════════════════════════════════════════════════════════════


def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


#: 尾部「还没补齐的一天」的判定阈值：当天覆盖的 type 数低于窗口常态的这个比例时不算数据日。
#: ESI 的市场历史**按天逐步出**，最新一两天往往只有几百个 type（实测 2026-10-04 只有 434 个，
#: 前一天 2,926 个）—— 把它当锚点，广度与指数会落在残缺的一天上（涨跌家数从 2,300+ 掉到 399）。
COVERAGE_RATIO = 0.5


def _last_history_day(conn_mgr, region_id: int) -> date | None:
    """最新**已补齐**的**成交**数据日（只看 `price_history`，覆盖数达标的那天）。

    广度/成交额这类「当日成交」统计必须用它：全服价表里的日子没有成交量，
    拿来当统计日会得到 0 家涨跌（见 `get_breadth`）。
    """
    best: str | None = None
    with conn_mgr.connect("mkt") as conn:
        if _table_exists(conn, "price_history"):
            rows = conn.execute(
                "SELECT date, COUNT(*) FROM price_history WHERE region_id = ? GROUP BY date ORDER BY date",
                (region_id,),
            ).fetchall()
            if rows:
                typical = max(int(r[1] or 0) for r in rows)
                threshold = typical * COVERAGE_RATIO
                # 从最后往前找第一个「覆盖数达标」的日子（通常就是倒数第二天）
                for day, count in reversed(rows):
                    if int(count or 0) >= threshold:
                        best = str(day)
                        break
    return date.fromisoformat(best) if best else None


def _last_day(conn_mgr, region_id: int) -> date | None:
    """指数计算用的最新数据日：**成交**的已补齐日 与 **全服价**的最新日取较晚者。

    - 只看「MAX(date)」会被 ESI 的尾部残缺日骗到（见 `COVERAGE_RATIO`）；
    - 只看 `price_history` 又会让「只装了全服价」的库算不出 PLEX（它的序列在
      `global_price_daily` 里）。
    """
    best = _last_history_day(conn_mgr, region_id)
    with conn_mgr.connect("mkt") as conn:
        if _table_exists(conn, "global_price_daily"):
            row = conn.execute("SELECT MAX(date) FROM global_price_daily").fetchone()
            if row and row[0]:
                global_day = date.fromisoformat(str(row[0]))
                if best is None or global_day > best:
                    best = global_day
    return best


def _load_observations(
    conn_mgr,
    region_id: int,
    type_ids: Iterable[int],
    start: date,
    end: date,
) -> dict[int, list[tuple[str, float, int]]]:
    """读 `price_history` → `{type_id: [(date, average, volume), ...]}`（按日期升序）。

    **全服统一价的品种（PLEX）改用 `global_price_daily` 覆盖**：它的价格全服一致、没有区域
    划分，ESI 的区块历史对它恒返回空（实测 Jita/Amarr 都是空列表），所以 `price_history`
    里永远不会有它。两种口径不能混在同一条序列里，命中就整段替换。
    """
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, list[tuple[str, float, int]]] = {}
    if not ids:
        return out
    with conn_mgr.connect("mkt") as conn:
        # 两张表各自判断存在性：只装了 `global_price_daily`（还没跑过历史拉取）时，
        # PLEX 也应该有数 —— 早退会让它整条线空掉
        if _table_exists(conn, "price_history"):
            for offset in range(0, len(ids), _SQL_CHUNK):
                chunk = ids[offset : offset + _SQL_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT type_id, date, average, volume FROM price_history "
                    f"WHERE region_id = ? AND date >= ? AND date <= ? AND type_id IN ({placeholders}) "
                    f"ORDER BY type_id, date",
                    (region_id, start.isoformat(), end.isoformat(), *chunk),
                ).fetchall()
                for tid, day, average, volume in rows:
                    out.setdefault(int(tid), []).append((str(day), float(average or 0.0), int(volume or 0)))
        for tid, rows in _load_global_observations(conn, ids, start, end).items():
            # 全服价是**退路，不是覆盖**：只有该品种在窗口里完全没有区域成交序列时才用它。
            # （曾经写成无条件覆盖 —— 那时把 8 种矿物也放进了全服快照表，结果矿物的
            #  398 天成交序列被换成 1 行当日价，MPI 直接整条空掉。）
            if not out.get(tid):
                out[tid] = rows
    return out


def _load_global_observations(
    conn,
    type_ids: Iterable[int],
    start: date,
    end: date,
) -> dict[int, list[tuple[str, float, int]]]:
    """读 `global_price_daily`（全服统一价）→ 与 `price_history` 同形的序列。

    成交量给 0：这张表只有价格，没有成交（PLEX 的成交量 ESI 也不按区块给）。
    """
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, list[tuple[str, float, int]]] = {}
    if not ids or not _table_exists(conn, "global_price_daily"):
        return out
    for offset in range(0, len(ids), _SQL_CHUNK):
        chunk = ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT type_id, date, average_price FROM global_price_daily "
            f"WHERE date >= ? AND date <= ? AND type_id IN ({placeholders}) ORDER BY type_id, date",
            (start.isoformat(), end.isoformat(), *chunk),
        ).fetchall()
        for tid, day, average in rows:
            out.setdefault(int(tid), []).append((str(day), float(average or 0.0), 0))
    return out


def _load_names(conn_mgr, type_ids: Iterable[int]) -> dict[int, str]:
    """`{type_id: 中文名（退回英文名，再退回 #id）}`；reference.db 没表 → `{}`。"""
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, str] = {}
    if not ids:
        return out
    with conn_mgr.connect("ref") as conn:
        if not _table_exists(conn, "item"):
            return out
        for offset in range(0, len(ids), _SQL_CHUNK):
            chunk = ids[offset : offset + _SQL_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT type_id, zh_name, en_name FROM item WHERE type_id IN ({placeholders})", chunk
            ).fetchall()
            for tid, zh, en in rows:
                out[int(tid)] = str(zh or en or f"#{int(tid)}")
    return out


def _blueprint_classes(conn_mgr) -> tuple[set[int], set[int]]:
    """蓝图层级判定 → `(PPPI 候选, SPPI 候选)`（都取自「被 manufacturing/reaction 当材料」的 type）。

    PPPI = 材料 **供入**的蓝图产物本身还是材料（用途层级 ≥2）；SPPI = 余下的材料。
    blueprint.db 缺表 → `(set(), set())`。
    """
    placeholders = ",".join("?" * len(BASED_ACTIVITIES))
    with conn_mgr.connect("bp") as conn:
        if not (_table_exists(conn, "blueprint_materials") and _table_exists(conn, "blueprint_products")):
            return set(), set()
        materials = {
            int(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT material_type_id FROM blueprint_materials WHERE activity IN ({placeholders})",
                BASED_ACTIVITIES,
            )
        }
        pppi = {
            int(row[0])
            for row in conn.execute(
                f"""SELECT DISTINCT bm.material_type_id
                    FROM blueprint_materials bm
                    JOIN blueprint_products bp
                      ON bp.blueprint_type_id = bm.blueprint_type_id AND bp.activity = bm.activity
                    WHERE bm.activity IN ({placeholders})
                      AND bp.product_type_id IN (
                          SELECT material_type_id FROM blueprint_materials WHERE activity IN ({placeholders})
                      )""",
                (*BASED_ACTIVITIES, *BASED_ACTIVITIES),
            )
        }
    pppi &= materials
    return pppi, materials - pppi


def _cpi_candidates(conn_mgr, region_id: int, materials: set[int], anchor: date | None) -> list[int]:
    """CPI 代理篮子：近 30 天成交额 top-:data:`CPI_TOP_N`，排除「被当材料」的 type。"""
    if anchor is None:
        return []
    start = anchor - timedelta(days=REBALANCE_DAYS - 1)
    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "price_history"):
            return []
        rows = conn.execute(
            """SELECT type_id, SUM(volume * average) AS turnover, COUNT(*) AS covered
               FROM price_history
               WHERE region_id = ? AND date >= ? AND date <= ?
               GROUP BY type_id
               HAVING turnover > ? AND covered >= ?
               ORDER BY turnover DESC""",
            (region_id, start.isoformat(), anchor.isoformat(), MIN_TURNOVER_ISK, MIN_COVERED_DAYS),
        ).fetchall()
    out: list[int] = []
    for row in rows:
        tid = int(row[0])
        if tid in materials:
            continue
        out.append(tid)
        if len(out) >= CPI_TOP_N:
            break
    return out


def _member_sets(
    conn_mgr, region_id: int, keys: Sequence[str], anchor: date | None
) -> tuple[dict[str, set[int]], set[int]]:
    """`({key: 候选成分})`, `materials`。候选成分**未**做准入过滤（准入在逐日权重里做）。"""
    pppi, sppi = _blueprint_classes(conn_mgr)
    materials = pppi | sppi
    cpi: list[int] | None = None
    out: dict[str, set[int]] = {}
    for key in keys:
        if key == "mpi":
            out[key] = set(MPI_TYPES)
        elif key == "plex":
            out[key] = {PLEX_TYPE_ID}
        elif key == "pppi":
            out[key] = set(pppi)
        elif key == "sppi":
            out[key] = set(sppi)
        elif key == "cpi":
            if cpi is None:
                cpi = _cpi_candidates(conn_mgr, region_id, materials, anchor)
            out[key] = set(cpi)
    return out, materials


def _build_for(conn_mgr, region_id: int, keys: Sequence[str]) -> dict[str, _IndexPoints]:
    """实时计算若干指数的点位（不写库）。"""
    empty = {key: _IndexPoints(points=[], weights={}) for key in keys}
    anchor = _last_day(conn_mgr, region_id)
    if anchor is None:
        return empty
    sets, _materials = _member_sets(conn_mgr, region_id, keys, anchor)
    union: set[int] = set()
    for members in sets.values():
        union |= members
    obs = _load_observations(conn_mgr, region_id, union, anchor - timedelta(days=LOAD_WINDOW_DAYS - 1), anchor)
    return {key: _build_index(obs, sets[key]) for key in keys}


def _read_materialized(conn_mgr, region_id: int, key: str) -> list[dict]:
    """读物化表里某指数的点位；没有表/没有行 → `[]`。"""
    tid = INDEX_TYPE_IDS.get(key)
    if tid is None:
        return []
    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "market_index_daily"):
            return []
        rows = conn.execute(
            "SELECT date, price, volume FROM market_index_daily WHERE type_id = ? AND region_id = ? ORDER BY date",
            (tid, region_id),
        ).fetchall()
    return [{"date": str(day), "value": float(price), "volume": int(volume or 0)} for day, price, volume in rows]


def _resolve_points(conn_mgr, region_id: int, keys: Sequence[str]) -> dict[str, list[dict]]:
    """点位：优先读物化缓存，缺失的指数实时计算（**不**写库）。"""
    out: dict[str, list[dict]] = {}
    missing: list[str] = []
    for key in keys:
        cached = _read_materialized(conn_mgr, region_id, key)
        out[key] = cached
        if not cached:
            missing.append(key)
    if missing:
        for key, built in _build_for(conn_mgr, region_id, missing).items():
            out[key] = built.points
    return out


# ════════════════════════════════════════════════════════════════
#  公开接口
# ════════════════════════════════════════════════════════════════


def refresh_index_daily(region_id: int = JITA_RID) -> int:
    """重建 `market.db.market_index_daily`（五个指数逐日点位），返回写入行数。"""
    conn_mgr = get_db()
    with conn_mgr.connect("mkt") as conn:
        conn.execute(MARKET_INDEX_DDL)

    built = _build_for(conn_mgr, region_id, INDEX_KEYS)
    rows: list[tuple[int, int, str, float, int]] = []
    for key in INDEX_KEYS:
        tid = INDEX_TYPE_IDS[key]
        for point in built[key].points:
            rows.append((tid, region_id, str(point["date"]), float(point["value"]), int(point["volume"])))

    with conn_mgr.connect("mkt") as conn:
        conn.execute("DELETE FROM market_index_daily WHERE region_id = ?", (region_id,))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO market_index_daily (type_id, region_id, date, price, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    return len(rows)


def _pct(value: float | None, base: float | None) -> float | None:
    """百分比涨幅；基数缺失/为 0 → `None`（不用 0 冒充）。"""
    if value is None or base is None or base <= 0:
        return None
    return (value / base - 1.0) * 100.0


def _value_before(points: Sequence[dict], days: int) -> float | None:
    """最后一个点往前 `days` 个日历天（含）之前最近一个点的点位；不够长 → `None`。"""
    if not points:
        return None
    cutoff = date.fromisoformat(str(points[-1]["date"])).toordinal() - days
    found: float | None = None
    for point in points:
        if date.fromisoformat(str(point["date"])).toordinal() <= cutoff:
            found = float(point["value"])
        else:
            break
    return found


def get_index_cards(region_id: int = JITA_RID, _db=None) -> list[dict]:
    """五张指数卡：`[{key,label,value,chg1,chg7,chg30,chg90,chg180,days,base_date}]`。

    涨跌是百分比（`float`）；数据不足的窗口给 `None`（不用 0 冒充）。
    """
    conn_mgr = _db or get_db()
    points_map = _resolve_points(conn_mgr, region_id, INDEX_KEYS)

    cards: list[dict] = []
    for key in INDEX_KEYS:
        points = points_map.get(key) or []
        card: dict = {
            "key": key,
            "label": INDEX_LABELS[key],
            "value": None,
            "chg1": None,
            "chg7": None,
            "chg30": None,
            "chg90": None,
            "chg180": None,
            "days": len(points),
            "base_date": str(points[0]["date"]) if points else None,
        }
        if len(points) >= 2:
            last = float(points[-1]["value"])
            card["value"] = last
            card["chg1"] = _pct(last, float(points[-2]["value"]))
            for name, days in CHG_WINDOWS[1:]:
                card[name] = _pct(last, _value_before(points, days))
        cards.append(card)
    return cards


def get_index_series(keys: Sequence[str] | None = None, region_id: int = JITA_RID, _db=None) -> list[dict]:
    """指数折线 + 篮子成员表：`[{key,label,points:[{date,value}],members:[...]}]`。

    成员字段：`{typeId,name,weight,capped,price,chg30,source}`；`weight` 是该指数**最后一个指数日**
    的近 30 天成交额权重（准入 + 25% 上限后归一化），`price` = 该成员在同一锚定日（含）之前最近一次
    成交均价（当日没成交则取此前最近一次；完全没有 → `None`）。固定篮子（MPI/PLEX）恒列出全部固定成员
    （不满足准入的权重 0），其余篮子只列当日有正权重的成员。未知 key 直接忽略。
    """
    conn_mgr = _db or get_db()
    wanted = [key for key in (keys if keys is not None else INDEX_KEYS) if key in INDEX_LABELS]
    if not wanted:
        return []
    points_map = _resolve_points(conn_mgr, region_id, wanted)

    member_sets, _materials = _member_sets(conn_mgr, region_id, wanted, _last_day(conn_mgr, region_id))
    anchors: dict[str, date] = {}
    for key in wanted:
        points = points_map.get(key) or []
        if points:
            anchors[key] = date.fromisoformat(str(points[-1]["date"]))

    union: set[int] = set()
    for members in member_sets.values():
        union |= members
    obs: dict[int, list[tuple[str, float, int]]] = {}
    if anchors and union:
        end = max(anchors.values())
        obs = _load_observations(conn_mgr, region_id, union, end - timedelta(days=LOAD_WINDOW_DAYS - 1), end)
    names = _load_names(conn_mgr, union)

    out: list[dict] = []
    for key in wanted:
        members_out: list[dict] = []
        anchor = anchors.get(key)
        weights = _weights_at(obs, member_sets[key], anchor) if anchor is not None else {}
        for tid, (weight, capped) in sorted(weights.items(), key=lambda item: -item[1][0]):
            members_out.append(_member_row(tid, weight, capped, names, obs, key, anchor))
        if MEMBER_SOURCES[key] == "fixed":
            listed = {row["typeId"] for row in members_out}
            for tid in sorted(member_sets[key] - listed):
                members_out.append(_member_row(tid, 0.0, False, names, obs, key, anchor))
        out.append(
            {
                "key": key,
                "label": INDEX_LABELS[key],
                "points": [{"date": str(p["date"]), "value": float(p["value"])} for p in (points_map.get(key) or [])],
                "members": members_out,
            }
        )
    return out


def _member_row(
    tid: int,
    weight: float,
    capped: bool,
    names: Mapping[int, str],
    obs: Mapping[int, Sequence[tuple[str, float, int]]],
    key: str,
    anchor: date | None,
) -> dict:
    rows = obs.get(tid) or []
    return {
        "typeId": tid,
        "name": names.get(tid, f"#{tid}"),
        "weight": weight,
        "capped": capped,
        "price": _last_price(rows, anchor),
        "chg30": _price_change(rows, REBALANCE_DAYS),
        "source": MEMBER_SOURCES[key],
    }


def get_breadth(region_id: int = JITA_RID, _db=None) -> dict:
    """最新交易日的市场广度：`{date,advancers,decliners,unchanged,turnover}`。

    统计口径：当日有成交均价、且此前有过成交的 type；`turnover` = 当日 Σ(volume × average)。
    没有数据 → 所有字段 `None`（不用 0 冒充）。
    """
    empty = {"date": None, "advancers": None, "decliners": None, "unchanged": None, "turnover": None}
    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "price_history"):
            return empty
        rows = conn.execute(
            """WITH ranked AS (
                   SELECT type_id, date, average, volume,
                          ROW_NUMBER() OVER (PARTITION BY type_id ORDER BY date DESC) AS rn
                   FROM price_history WHERE region_id = ?
               )
               SELECT type_id, date, average, volume, rn FROM ranked WHERE rn <= 2""",
            (region_id,),
        ).fetchall()
    if not rows:
        return empty

    newest: dict[int, tuple[str, float]] = {}
    previous: dict[int, tuple[str, float]] = {}
    for tid, day, average, _volume, rn in rows:
        (newest if int(rn) == 1 else previous)[int(tid)] = (str(day), float(average or 0.0))

    # 用**已补齐的成交锚点日**（而不是各 type 自己最新的那天）：ESI 的尾部残缺日只有几百个
    # type 有数据，按它统计会把涨跌家数从 2,300+ 掉到 399，量价背离也跟着假报
    # （见 `COVERAGE_RATIO`）。锚点日在窗口里就统计它，取不到则退回最新日。
    anchor = _last_history_day(conn_mgr, region_id)
    latest = anchor.isoformat() if anchor is not None else max(day for day, _average in newest.values())
    advancers = decliners = unchanged = 0
    turnover = 0.0
    for tid, (day, average) in newest.items():
        if day != latest:
            continue
        prior = previous.get(tid)
        if prior is None:
            continue
        if average > prior[1]:
            advancers += 1
        elif average < prior[1]:
            decliners += 1
        else:
            unchanged += 1
    for _tid, day, average, volume, rn in rows:
        if int(rn) == 1 and str(day) == latest:
            turnover += float(average or 0.0) * float(volume or 0)

    return {
        "date": latest,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "turnover": turnover,
    }

"""大盘指数计算服务 —— CCP 四指数（MPI/PPPI/SPPI/CPI 代理）+ PLEX 锚。

口径来源：`docs/dev/market-monitor-plan.md` §2（CCP 2012 价格指数 dev blog + 2019 MER + 薄市场指数方法论）。
本模块只用 **成交均价**（`market.db.price_history.average`），**不用挂单价** —— 一个人挂/撤单就能推动挂单价。

五条线
------
==================  ==========================================================================
``mpi``             固定 8 种矿物（:data:`MPI_TYPES`），与 CCP MPI 一致
``pppi``            初级投入品：被**有效配方**当材料（:data:`VALID_RECIPE_NOTE`），
                    **且它供入的产物本身又是生产投入品**（用途层级 ≥2，近似 CCP 的 ore/moon/PI/发明用品）
``sppi``            次级投入品：是生产投入品，但供入的产物**不再是生产投入品**（直接供给消费品）
``cpi``             消费品（代理）：有成交、**不是生产投入品**，按近 30 天成交额取 top-:data:`CPI_TOP_N`
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
- **「生产投入品」= 被 ≥ :data:`MIN_VALID_RECIPES` 张**有效配方**当材料**（:data:`VALID_RECIPE_NOTE`）：
  二值判定（「被任何一张蓝图当材料」）会把**成品舰船**算成投入品 —— 因为 CCP 在 SDE 里留着
  **游戏内造不出来**的占位配方（变体版蓝图 `帕拉丁级血袭者版蓝图` 之类），加上「海军型/舰队型」
  这类真实但会拿 T1 舰身当材料的变体配方。实测口径对比见 :data:`MIN_VALID_RECIPES` 的注释：
  两条一起用才把带「级」的成分从 151 个 / 52.4% 压到 7 个 / 5.1%（零舰船）。
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

大盘页要「卡片 + 序列」两样：用 :func:`get_dashboard` 一次算完（成分集 / 观测装载 / 逐日累乘
只跑一遍），不要分别调那两个函数 —— 那会把同一套计算整跑两遍。
"""

from __future__ import annotations

import logging
from collections.abc import Hashable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import NamedTuple

from services.database_manager import get_db

log = logging.getLogger(__name__)

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

#: 「生产投入品」的判据 = 被**有效配方**当材料。有效配方 = 该蓝图在 SDE 里**真的能用**：
#: 产出物在 `ref.item.market_group_id` 上有值（已发布的市场物品）。
#:
#: 为什么需要这条：CCP 在 SDE 里留了一批**游戏内造不出来**的占位配方，典型是「变体版蓝图」
#: （`帕拉丁级血袭者版蓝图`：manufacturing 10s / copying 8s、只有 1 行材料）。它们把**成品舰船**
#: 当材料，于是「被任何蓝图当材料就算投入品」的二值判定会把舰船塞进 SPPI —— 实测 151 个名字带
#: 「级」的成分、权重合计 52.4%。用户口径：「这些船生产出来就能直接开，是消费品」。
#:
#: 为什么用 `market_group_id` 而不是别的：
#: - 「制造时间短」会误杀真货：`碳化晶体附甲` 25s、`米亚莫斯级酷菲特强版` 10s 都有真实挂单；
#: - 「有没有挂单」也会误判（占位配方照样可能有挂单）；
#: - 占位配方的产出物在 SDE 里就是**未发布物品**：`先知级血袭者版`(33875)、`地狱天使级塔什蒙贡版`
#:   (33623) 的 `market_group_id` 均为 NULL；真实市场物品都有值（帕拉丁级 1081、碳化晶体附甲 1888、
#:   三钛合金 1857）。制造产物里市场分类为空的有 610 个（B级克隆、大量「弃用的…」等）。
#:
#: 实测效果：材料集 1646 → **1565**；SPPI 里当投入品的舰船 151 → **17**，且剩下 17 个都是真实配方
#: （`旗舰级核心温度调节器` 被 44 张有效配方用；`乌鸦级`/`狂暴级`/`灾难级` 各 1 张 = 海军型变体，
#: 确实要拿成品舰船去造）。
#: 实测效果（2026-10 真实库，只读对比）：
#: 材料集 1646 → **437**；SPPI 候选 1182 → **227**；SPPI 里名字带「级」的成分
#: **151 个 / 37.4% → 3 个 / 2.1%（零舰船）**，权重前 5 从「帕拉丁级 4.69%、魔像级 3.85%…」
#: 变成「逻辑电路 26.47%、纳米聚合体 7.80%、完好的装甲附甲 7.12%…」。
VALID_RECIPE_NOTE = "产出物在 ref.item.market_group_id 上有值（SDE 里已发布的市场物品）"

#: 被判为「生产投入品」还需要的**最少有效配方数**。
#: 只过滤占位配方还不够：实测材料集仍有 1,565 个，SPPI 里带「级」的成分 142 个 / 权重 27.4%
#: （旧口径 151 个 / 52.4%）—— 因为「海军型/舰队型」这类变体配方是**真实有效**的，
#: 也确实要拿 T1 舰身当材料，但它们不该把整条舰船线拖进「次级投入品」篮子。
#: 真正的投入品（矿物/组件/反应原料）被成百上千张有效配方使用。四口径实测对比：
#:   任意蓝图当材料        材料集 1646，SPPI 带「级」151 个 / 52.4%
#:   ≥4 张蓝图             材料集  452，带「级」17 个 / 14.7%
#:   只过滤占位配方        材料集 1565，带「级」142 个 / 27.4%
#:   **≥4 张有效配方**     材料集  437，带「级」**7 个 / 5.1%（零舰船）** ← 采用
MIN_VALID_RECIPES = 4

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
    """表是否存在。`name` 可以带库前缀（如 `ref.item`）—— 带前缀时查那张库的 `sqlite_master`。

    ⚠️ 不带前缀的查询只看**主库**：`db.connect("bp", "ref")` 之后
    `SELECT ... FROM sqlite_master WHERE name='item'` 是查不到 `ref.item` 的（ATTACH 进来的库
    有自己的 `sqlite_master`），照那样判会把「有效配方过滤」整条静默跳过。
    """
    if "." in name:
        schema, _, table = name.partition(".")
        row = conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    else:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


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
    """蓝图层级判定 → `(PPPI 候选, SPPI 候选)`（都取自**生产投入品**）。

    生产投入品 = 被**有效配方**当材料的 type；有效配方的判据见 :data:`VALID_RECIPE_NOTE`。
    PPPI = 它的**蓝图产物本身也是生产投入品**（层级 ≥2）；SPPI = 余下的生产投入品。
    blueprint.db 缺表 → `(set(), set())`。
    """
    placeholders = ",".join("?" * len(BASED_ACTIVITIES))
    with conn_mgr.connect("bp", "ref") as conn:
        if not (_table_exists(conn, "blueprint_materials") and _table_exists(conn, "blueprint_products")):
            return set(), set()
        if _table_exists(conn, "ref.item"):
            materials = {
                int(row[0])
                for row in conn.execute(
                    f"""SELECT bm.material_type_id
                        FROM blueprint_materials bm
                        WHERE bm.activity IN ({placeholders})
                          AND EXISTS (
                              SELECT 1 FROM blueprint_products vp
                              JOIN ref.item vi ON vi.type_id = vp.product_type_id
                              WHERE vp.blueprint_type_id = bm.blueprint_type_id
                                AND vp.activity = bm.activity
                                AND vi.market_group_id IS NOT NULL
                          )
                        GROUP BY bm.material_type_id
                        HAVING COUNT(DISTINCT bm.blueprint_type_id) >= ?""",
                    (*BASED_ACTIVITIES, MIN_VALID_RECIPES),
                )
            }
        else:
            # reference.db 没导好 → 退化成「所有配方都算」（仍按最少有效配方数卡一道）
            log.warning("reference.db 缺 item 表，占位配方过滤失效（SPPI 可能混入成品舰船）")
            materials = {
                int(row[0])
                for row in conn.execute(
                    f"""SELECT material_type_id FROM blueprint_materials
                        WHERE activity IN ({placeholders})
                        GROUP BY material_type_id
                        HAVING COUNT(DISTINCT blueprint_type_id) >= ?""",
                    (*BASED_ACTIVITIES, MIN_VALID_RECIPES),
                )
            }
        # PPPI = 它的**蓝图产物本身也是生产投入品**（层级 ≥2）。
        # ⚠️ 这里必须用**收紧后**的 `materials`（有效配方 ∧ ≥MIN_VALID_RECIPES）判断产物，
        # 不能再用「被任何蓝图当材料」的全集 —— 否则 code 与上面 docstring/计划 §2.1 的定义不一致，
        # 实测会把 210 个算成 PPPI（收紧后应为 78）。
        product_pairs = conn.execute(
            f"""SELECT DISTINCT bm.material_type_id, bp.product_type_id
                FROM blueprint_materials bm
                JOIN blueprint_products bp
                  ON bp.blueprint_type_id = bm.blueprint_type_id AND bp.activity = bm.activity
                WHERE bm.activity IN ({placeholders})""",
            BASED_ACTIVITIES,
        ).fetchall()
    pppi = {int(mat) for mat, prod in product_pairs if prod is not None and int(prod) in materials}
    pppi &= materials
    return pppi, materials - pppi


def production_input_classes(db=None) -> tuple[set[int], set[int]]:
    """**生产投入品**的 PPPI / SPPI 划分 —— 指数篮子与异动榜共用的唯一口径。

    判据见 :data:`VALID_RECIPE_NOTE` 与 :data:`MIN_VALID_RECIPES`（被 ≥4 张**有效配方**当材料）。
    `db` 传 `services.database_manager` 的 manager（含临时库 fixture），不传则用 `get_db()`。

    异动榜（`services.market_movers_service`）复用本函数、不再自己抄一份 SQL：
    两份口径一旦分叉，用户就会看到「同一件东西在指数篮子里、却在异动榜里标成另一个指数」。
    """
    return _blueprint_classes(db or get_db())


def production_inputs(db=None) -> set[int]:
    """生产投入品 = PPPI ∪ SPPI（见 :func:`production_input_classes`）。"""
    pppi, sppi = production_input_classes(db)
    return pppi | sppi


def _cpi_candidates(conn_mgr, region_id: int, materials: set[int], anchor: date | None) -> list[int]:
    """CPI 代理篮子：近 30 天成交额 top-:data:`CPI_TOP_N`，排除**生产投入品**（`materials`）。

    被少量蓝图（变体版蓝图）当材料的成品舰船/模块不在 `materials` 里 → 回到消费品篮子。
    """
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
    """`({key: 候选成分})`, **生产投入品**集合（= PPPI ∪ SPPI）。候选成分**未**做准入过滤（准入在逐日权重里做）。"""
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


def _build_for(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    anchor: date | None = None,
    sets: Mapping[str, set[int]] | None = None,
) -> dict[str, _IndexPoints]:
    """实时计算若干指数的点位（不写库）。

    `anchor`（最新数据日）与 `sets`（成分集）可传入调用方已算好的结果 —— 见
    :func:`get_dashboard`：它把成分集算一遍后同时喂给卡片与序列两条路。`sets` 里
    多出来的 key 不参与观测装载（只装 `keys` 要用的那部分）。
    """
    empty = {key: _IndexPoints(points=[], weights={}) for key in keys}
    if anchor is None:
        anchor = _last_day(conn_mgr, region_id)
    if anchor is None:
        return empty
    if sets is None:
        sets, _materials = _member_sets(conn_mgr, region_id, keys, anchor)
    union: set[int] = set()
    for key in keys:
        union |= sets[key]
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


def _resolve_points(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    anchor: date | None = None,
    sets: Mapping[str, set[int]] | None = None,
) -> dict[str, list[dict]]:
    """点位：优先读物化缓存，缺失的指数实时计算（**不**写库）。

    `anchor` / `sets` 透传给 :func:`_build_for`（:func:`get_dashboard` 一次算完时用）。
    """
    out: dict[str, list[dict]] = {}
    missing: list[str] = []
    for key in keys:
        cached = _read_materialized(conn_mgr, region_id, key)
        out[key] = cached
        if not cached:
            missing.append(key)
    if missing:
        for key, built in _build_for(conn_mgr, region_id, missing, anchor, sets).items():
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


def _cards_from_points(points_map: Mapping[str, Sequence[dict]]) -> list[dict]:
    """点位表 → 五张指数卡（`get_index_cards` / `get_dashboard` 共用这一份口径）。"""
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


def _series_from_points(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    points_map: Mapping[str, Sequence[dict]],
    member_sets: Mapping[str, set[int]],
) -> list[dict]:
    """点位表 + 成分集 → 折线 + 篮子成员表（`get_index_series` / `get_dashboard` 共用）。

    成员字段与口径见 :func:`get_index_series` 的 docstring；`member_sets` 由调用方传入，
    于是成分集只算一遍。
    """
    anchors: dict[str, date] = {}
    for key in keys:
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
    for key in keys:
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


def get_index_cards(region_id: int = JITA_RID, _db=None) -> list[dict]:
    """五张指数卡：`[{key,label,value,chg1,chg7,chg30,chg90,chg180,days,base_date}]`。

    涨跌是百分比（`float`）；数据不足的窗口给 `None`（不用 0 冒充）。
    """
    conn_mgr = _db or get_db()
    return _cards_from_points(_resolve_points(conn_mgr, region_id, INDEX_KEYS))


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
    return _series_from_points(conn_mgr, region_id, wanted, points_map, member_sets)


def get_dashboard(region_id: int = JITA_RID, _db=None) -> dict:
    """卡片 + 序列**一次算完** → `{"cards": [...], "series": [...]}`。

    形状与值同分别调 :func:`get_index_cards` / :func:`get_index_series` **逐字段一致**，
    区别只在「只算一遍」：成分集（蓝图层级 + CPI 候选）、观测装载、逐日累乘都只跑一次，
    两个返回值从同一份中间结果派生。大盘页原先分别调那两个函数 —— 同一套计算整跑两遍
    （真实库实测合计约 13s，虽在后台线程不卡 UI，但没必要）。
    """
    conn_mgr = _db or get_db()
    anchor = _last_day(conn_mgr, region_id)
    member_sets, _materials = _member_sets(conn_mgr, region_id, INDEX_KEYS, anchor)
    points_map = _resolve_points(conn_mgr, region_id, INDEX_KEYS, anchor, member_sets)
    return {
        "cards": _cards_from_points(points_map),
        "series": _series_from_points(conn_mgr, region_id, INDEX_KEYS, points_map, member_sets),
    }


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
    # 用**已补齐的成交锚点日**（不是各 type 自己最新的那天）：ESI 的尾部残缺日只有几百个
    # type 有数据，按它统计会把涨跌家数从 2,300+ 掉到 399，量价背离也跟着假报
    # （见 `COVERAGE_RATIO`）。
    anchor = _last_history_day(conn_mgr, region_id)
    if anchor is None:
        return empty
    latest = anchor.isoformat()

    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "price_history"):
            return empty
        # ⚠️ 三个坑都踩过（实测真实库 116 万行）：
        # 1. `ROW_NUMBER() OVER (PARTITION BY type_id ...)`：加了 `(region_id, date)` 索引后改走
        #    「扫索引 + 临时 B 树排序」，`get_breadth` 从 2.04s 恶化到 10.16s；
        # 2. 「前一次观测」写成不限期窗口的 `GROUP BY type_id` 子查询：11.8s；
        # 3. 写成 `prev_days ⋈ cur ⋈ prev` 的 join：优化器会拿 `prev` 当驱动表并丢掉日期约束
        #    （`SEARCH prev ... (region_id=?)` = 扫该区域全部 110 万行 + 逐行主键探测），17.4~28.4s，
        #    连 `MATERIALIZED` 也治不住。
        # 正解 = **相关标量子查询**：`cur` 走 (region_id, date) 索引（当日 2,926 行），
        # 每个 type 再用主键 `(type_id, region_id, date)` 做一次倒序范围扫取前一次观测，
        # 并限制在 `RETURN_GAP_DAYS` 天内（日度广度不该拿一个月前的价格比）。实测 **0.05s**。
        rows = conn.execute(
            """SELECT cur.type_id, cur.average, cur.volume,
                      (SELECT p.average FROM price_history p
                        WHERE p.type_id = cur.type_id AND p.region_id = cur.region_id
                          AND p.date < cur.date AND p.date >= date(cur.date, ?)
                        ORDER BY p.date DESC LIMIT 1) AS prev
               FROM price_history cur
               WHERE cur.region_id = ? AND cur.date = ?""",
            (f"-{RETURN_GAP_DAYS} days", region_id, latest),
        ).fetchall()
    if not rows:
        return empty

    advancers = decliners = unchanged = 0
    turnover = 0.0
    for _tid, average, volume, prior in rows:  # 列序与 SELECT 一致：type_id, average, volume, prev
        now = float(average or 0.0)
        turnover += now * float(volume or 0)
        if prior is None:
            continue  # 30 天内没有前一次观测 → 算不出涨跌方向，只计成交额
        before = float(prior or 0.0)
        if now > before:
            advancers += 1
        elif now < before:
            decliners += 1
        else:
            unchanged += 1

    return {
        "date": latest,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "turnover": turnover,
    }

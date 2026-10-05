"""异动榜 —— 近 N 个日历天的成交均价涨幅 / 放量倍数 / 指数准入（只读）。

**只用 `market.db.price_history` 的成交均价**，不碰挂单价（计划 §2.2 第 2 条：
挂单价一个人挂/撤就能推动，不进指数、也不进异动榜）。

口径（与 `services/price_history.get_history_summary` 同一条规矩）：

- 窗口一律按**日历天**取，`近 n 天 = [今天 - n + 1, 今天]`；窗口内**没有记录的日子
  按 0 成交**计入分母，所以「日均」= 窗口内成交量之和 ÷ n，**不是** ÷ 有记录的天数
  （ESI 历史只返回有成交的日子，日期是跳的）。
- 涨跌 `chg` = 近 n 天成交均价 ÷ **前一个等长窗口**（再往前 n 天）的成交均价 − 1，单位 %。
  两个窗口各自取**成交量加权均价** `Σ(average×volume) / Σvolume`；窗口内成交量全为 0
  （脏数据）时退回该窗口的算术均价。
  前窗口没有记录 → 算不出涨幅 → **该物品不进榜**（不拿 0 冒充「没涨」）。
- 放量倍数 `volume_ratio` = 近 n 天日均 ÷ 近 30 天日均；近 30 天成交量合计为 0 → `None`。
- 准入 `qualified`（计划 §2.2 第 1 条）：近 30 天成交额 > 0 **且**有记录天数 ≥ 5。
- `index_keys`：该物品命中的指数（`INDEX_KEYS` 顺序）。分类口径见 `_index_membership`；
  它是「成分身份」，与 `qualified`（准入阈值）是两件事 —— 异动榜分两区靠 `qualified`
  字段表达，不属于任何指数的物品 `index_keys` 为 `[]`。
"""

from __future__ import annotations

from datetime import date, timedelta

from services import market_index_service
from services.database_manager import get_db
from services.name_resolver import resolve_item_names_batch

#: 吉他（The Forge）—— 与 `services.price_history.REGION_ID` 同值
JITA_RID = 10000002

#: 五条指数线（计划 §2.1），**顺序即 `index_keys` 的输出顺序**。
#: 与 `services/market_index_service.INDEX_KEYS` 是同一组字面量：这里各留一份，
#: 便于分析服务独立于指数模块的物化表/建表流程；但**成分口径不重复实现**：PPPI/SPPI
#: 走 `market_index_service.production_input_classes`（见 `_index_membership`）。
INDEX_KEYS = ("mpi", "pppi", "sppi", "cpi", "plex")

#: MPI 的 8 种矿物（CCP 官方口径，type_id 固定）
MPI_TYPE_IDS = frozenset({34, 35, 36, 37, 38, 39, 40, 11399})

#: PLEX —— ISK 锚
PLEX_TYPE_ID = 44992

#: 准入窗口 / 最少覆盖天数（计划 §2.2 第 1 条「覆盖天数 ≥ 阈值」）
ADMISSION_DAYS = 30
ADMISSION_MIN_COVERED_DAYS = 5

#: CPI 代理取「近 30 天成交额 top-N」（计划 §2.1）
CPI_TOP_N = 300

#: 上榜的**最低流动性**（用户口径：「异动榜希望更实用一些，没什么参考性的产品就不要上榜了」）。
#: 实测（2026-10，`days=3`）原来 200 条里 **199 条**都满足 `qualified`（近 30 天成交额 > 0
#: 且覆盖 ≥ 5 天），可前几名是：
#:   · 共和舰队热能涂层 +161843%（窗口里只有 1 笔成交、日均 1 件）
#:   · 旗舰级牵引光束 I +8031%（日均 1 件）
#:   · 基础型电磁电压薄膜 +6944%（日均 0.33 件）
#:   · 聚合高密度厚质凡晶石 +10976%（日均 1 万件，但它是**刚补的历史**，前一个窗口没有成交，
#:     基准价算出来是垃圾）
#: 这些都是「单笔成交」或「没有基准」造成的数字，对判断市场没有任何参考价值。故加三道下限。
MIN_DAILY_VOLUME = 5.0  #: 近窗口内的**日均成交量**（件）
MIN_TRADING_DAYS = 2  #: 近窗口内**有成交的天数**（3 天窗口只有 1 天 → 不上榜）
MIN_BASE_DAYS = 1  #: 前一个等长窗口**至少有 1 天成交**（否则基准价无意义）

#: |涨幅| 达到这个百分比就标 `extreme`：**不做过滤**（可能是真行情），
#: 但要让人一眼看出「这个数字要么是大事件、要么是数据问题」。
EXTREME_CHG_PCT = 200.0

#: 窗口内价格的**最大允许离散度**（成交量加权 `p90/p10`）。超过就打不上榜 ——
#: 价格双峰的物品（既有 1 ISK 甩卖又有上千 ISK 正常成交）「涨幅」是纯噪声。
MAX_WINDOW_SPREAD = 5.0

#: 计算窗口价时忽略「垃圾量日」的比例：当天成交量 < 窗口日中位量 × 本值 → 不参与定价。
JUNK_VOLUME_RATIO = 0.05


def _weighted_quantile(pairs: list[tuple[float, float]], q: float) -> float:
    """按成交量加权的分位数（`pairs` 需按价格升序）。"""
    total = sum(vol for _price, vol in pairs)
    if total <= 0:
        return float(pairs[min(len(pairs) - 1, int(q * len(pairs)))][0])
    target = total * q
    acc = 0.0
    for price, vol in pairs:
        acc += vol
        if acc >= target:
            return float(price)
    return float(pairs[-1][0])


def _window_price(day_rows: list[tuple[str, float, float]]) -> tuple[float, float] | None:
    """`(窗口价, 稳定度)`；稳定度 = 成交量加权 `p90 / p10`。数据不足 → `None`。

    三步（都是实测踩出来的）：

    1. **丢掉垃圾量日**：成交量不到窗口「日中位量」5% 的日子不参与定价 ——
       `碳铅弹 XL` 前窗口有一天「1 件 @4.11」，把窗口均价从 320 拖到 4（报 +7688%）。
    2. **窗口价取成交量加权中位数**（不是 VWAP）：单日异常成交带不偏它。
    3. **算稳定度**：价格双峰的物品（同一天既有 1 ISK 甩卖、又有 ~1400 ISK 正常成交，
       实测 `侍僧EV-300`、`冷藏食品`、`索敌增强器 I` 这类）中位数会在两个峰之间跳，
       「涨幅」纯属噪声 —— 用 `p90/p10` 把它们挡在榜外（阈值 :data:`MAX_WINDOW_SPREAD`）。
    """
    if not day_rows:
        return None
    volumes = sorted(vol for _day, _avg, vol in day_rows)
    median_vol = volumes[len(volumes) // 2]
    floor = max(1.0, median_vol * JUNK_VOLUME_RATIO)
    kept = [(avg, vol) for _day, avg, vol in day_rows if vol >= floor and avg > 0]
    if not kept:
        kept = [(avg, vol) for _day, avg, vol in day_rows if avg > 0]
    if not kept:
        return None
    kept.sort(key=lambda pair: pair[0])
    price = _weighted_quantile(kept, 0.5)
    p10 = _weighted_quantile(kept, 0.1)
    p90 = _weighted_quantile(kept, 0.9)
    spread = (p90 / p10) if p10 > 0 else float("inf")
    return price, spread


def _index_membership(conn_mgr, turnover_30d: dict[int, float]) -> dict[int, list[str]]:
    """`{type_id: 命中的指数 key}`（顺序按 `INDEX_KEYS`）。

    分类口径与**指数篮子同一处实现**（`market_index_service.production_input_classes`）：
    生产投入品 = 被 ≥ `MIN_VALID_RECIPES`（4）张**有效配方**当材料（有效配方 = 产出物在
    `ref.item.market_group_id` 非空；见 `market_index_service.VALID_RECIPE_NOTE`）。

    - `mpi` / `plex`：固定 type 集合。
    - `pppi` / `sppi`：生产投入品里，**其产物仍是生产投入品**的是 PPPI（初级投入品），
      产物不再是生产投入品的是 SPPI（直接供消费品）。
    - `cpi`：有成交、**不是生产投入品**，按近 30 天成交额取 top-N（代理口径）。

    旧口径（「被任何一张制造/反应蓝图当材料」）会把只被少量蓝图用到的成品舰船标成 `sppi` ——
    用户能看见的矛盾：那件东西已不在 SPPI 篮子里，异动榜却还说它是次级投入品。

    近 30 天成交额必须传**全部候选**（CPI 是排名，只看榜上那几条会算错）。
    """
    pppi, sppi = market_index_service.production_input_classes(conn_mgr)
    materials = pppi | sppi
    ranked = sorted(turnover_30d.items(), key=lambda kv: (-kv[1], kv[0]))
    cpi = {tid for tid, turn in ranked[:CPI_TOP_N] if turn > 0 and tid not in materials}

    hit = {
        "mpi": set(MPI_TYPE_IDS),
        "pppi": pppi,
        "sppi": sppi,
        "cpi": cpi,
        "plex": {PLEX_TYPE_ID},
    }
    return {tid: [k for k in INDEX_KEYS if tid in hit[k]] for tid in turnover_30d}


def get_movers(
    days: int = 3,
    limit: int = 50,
    region_id: int = JITA_RID,
    qualified_only: bool = False,
    _db=None,
) -> list[dict]:
    """近 `days` 个日历天的异动榜，按 |涨幅| 降序取前 `limit` 条。

    返回 `[{typeId, name, price, chg, volume, volume_ratio, qualified, index_keys}]`：

    - `price`：近 `days` 天成交均价（成交量加权）
    - `chg`：涨幅 %（近 `days` 天均价 vs 前 `days` 天均价）
    - `volume`：近 `days` 天**日均**成交量
    - `volume_ratio`：近 `days` 天日均 ÷ 近 30 天日均（近 30 天成交量为 0 → `None`）
    - `qualified`：是否通过指数准入（近 30 天成交额 > 0 且覆盖天数 ≥ 5）
    - `index_keys`：命中的指数 key（可能为空列表）

    查不到历史（或算不出涨幅）的 type **不进榜**；`qualified_only=True` 时只留通过准入的。
    """
    window = max(1, int(days))
    top = max(0, int(limit))
    today = date.today()
    recent_start = (today - timedelta(days=window - 1)).isoformat()
    prev_start = (today - timedelta(days=2 * window - 1)).isoformat()
    prev_end = (today - timedelta(days=window)).isoformat()
    w30_start = (today - timedelta(days=ADMISSION_DAYS - 1)).isoformat()
    today_s = today.isoformat()
    scan_start = min(prev_start, w30_start)

    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt", "ref", "bp") as conn:
        # 只读路径不做 DDL：从没拉过历史（也没开过价格走势图）就是没有数据
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_history'").fetchone():
            return []

        # 一次取最近 30 天（覆盖两个 `days` 窗口 + 30 天准入窗口）的**逐日行**：
        # 窗口价必须用「成交量加权中位数」算，聚合 SQL 里的 VWAP 会被个别异常日毁掉 ——
        # 实测（2026-10）：B-66纠缠型GQD 的日成交均价在 1.02 与 ~1450 之间来回跳、
        # 碳铅弹 XL 前窗口有一天「1 件 @4.11」（把基准价从 320 拉到 4）、
        # 模拟面板 有一天 31 万件 @250（把窗口均价从 31 拉到 250）。
        rows = conn.execute(
            """SELECT type_id, date, average, volume FROM price_history
               WHERE region_id = ? AND date BETWEEN ? AND ? ORDER BY type_id, date""",
            (region_id, scan_start, today_s),
        ).fetchall()

        by_type: dict[int, list[tuple[str, float, float]]] = {}
        for type_id, day, average, volume in rows:
            by_type.setdefault(int(type_id), []).append((str(day), float(average or 0.0), float(volume or 0.0)))

        w30_turnover: dict[int, float] = {}
        items: list[dict] = []
        for tid, day_rows in by_type.items():
            recent = [r for r in day_rows if r[0] >= recent_start]
            base_rows = [r for r in day_rows if prev_start <= r[0] <= prev_end]
            turn_w30 = sum(avg * vol for _d, avg, vol in day_rows)
            vol_w30 = sum(vol for _d, _a, vol in day_rows)
            w30_turnover[tid] = turn_w30

            price_info = _window_price(recent)
            base_info = _window_price(base_rows)
            if price_info is None or base_info is None:
                continue  # 算不出涨幅 → 不进榜（不用 0 冒充）
            price, spread_recent = price_info
            base, spread_base = base_info
            if base <= 0:
                continue
            # 窗口内价格必须**稳定**（`p90/p10 ≤ MAX_WINDOW_SPREAD`）：双峰价格的物品
            # （1 ISK 甩卖 + 上千 ISK 正常成交）「涨幅」纯属噪声，不上榜
            if spread_recent > MAX_WINDOW_SPREAD or spread_base > MAX_WINDOW_SPREAD:
                continue

            qualified = turn_w30 > 0 and len(day_rows) >= ADMISSION_MIN_COVERED_DAYS
            if qualified_only and not qualified:
                continue

            volume = sum(vol for _d, _a, vol in recent) / window
            base_volume = sum(vol for _d, _a, vol in base_rows) / window
            volume_ratio = volume / (vol_w30 / ADMISSION_DAYS) if vol_w30 > 0 else None
            # 上榜下限（用户口径：「没什么参考性的产品就不要上榜了」）：两边窗口都要有量、
            # 近期要有 ≥ `MIN_TRADING_DAYS` 天成交 —— 单笔成交/只有一天成交的一律不上榜。
            if (
                volume < MIN_DAILY_VOLUME
                or len(recent) < MIN_TRADING_DAYS
                or len(base_rows) < MIN_BASE_DAYS
                or base_volume < MIN_DAILY_VOLUME
            ):
                continue

            chg = (price / base - 1.0) * 100.0
            items.append(
                {
                    "typeId": tid,
                    "name": str(tid),
                    "price": round(price, 2),
                    "chg": round(chg, 2),
                    "volume": round(volume, 2),
                    "volume_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
                    "qualified": qualified,
                    #: |涨幅| 达到 `EXTREME_CHG_PCT` —— 可能是真实的大行情，也可能是数据问题，
                    #: UI 上单独标一下让用户自己判断，而不是偷偷过滤掉
                    "extreme": abs(chg) >= EXTREME_CHG_PCT,
                    "index_keys": [],
                }
            )

        membership = _index_membership(conn_mgr, w30_turnover)
        # 同 |涨幅| 时按 typeId 升序 —— 保证同一次数据下榜单顺序稳定
        items.sort(key=lambda d: (-abs(d["chg"]), d["typeId"]))
        top_items = items[:top]
        for item in top_items:
            item["index_keys"] = membership.get(item["typeId"], [])
        names = resolve_item_names_batch(conn, [item["typeId"] for item in top_items])
        for item in top_items:
            item["name"] = names.get(item["typeId"], str(item["typeId"]))
        return top_items

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


def _window_price(turnover: float, volume: float, avg_sum: float, covered: int) -> float | None:
    """窗口成交均价：有成交量就按成交量加权，成交量全 0 时退回算术均价，无记录给 None。"""
    if volume > 0:
        return turnover / volume
    if covered > 0:
        return avg_sum / covered
    return None


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

        sql = """
            SELECT type_id,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN volume ELSE 0 END) AS vol_recent,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average * volume ELSE 0 END) AS turn_recent,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average ELSE 0 END) AS avg_recent,
                   COUNT(CASE WHEN date BETWEEN ? AND ? THEN 1 END) AS cnt_recent,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN volume ELSE 0 END) AS vol_prev,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average * volume ELSE 0 END) AS turn_prev,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average ELSE 0 END) AS avg_prev,
                   COUNT(CASE WHEN date BETWEEN ? AND ? THEN 1 END) AS cnt_prev,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN volume ELSE 0 END) AS vol_w30,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average * volume ELSE 0 END) AS turn_w30,
                   SUM(CASE WHEN date BETWEEN ? AND ? THEN average ELSE 0 END) AS avg_w30,
                   COUNT(CASE WHEN date BETWEEN ? AND ? THEN 1 END) AS cnt_w30
            FROM price_history
            WHERE region_id = ? AND date BETWEEN ? AND ?
            GROUP BY type_id
        """
        spans = ((recent_start, today_s), (prev_start, prev_end), (w30_start, today_s))
        params: list[object] = [bound for span in spans for _ in range(4) for bound in span]
        params += [region_id, scan_start, today_s]
        raw = conn.execute(sql, params).fetchall()

        w30_turnover: dict[int, float] = {}
        items: list[dict] = []
        for row in raw:
            tid = int(row["type_id"])
            vol_recent, turn_recent, avg_recent, cnt_recent = (
                float(row["vol_recent"] or 0),
                float(row["turn_recent"] or 0),
                float(row["avg_recent"] or 0),
                int(row["cnt_recent"] or 0),
            )
            vol_prev, turn_prev, avg_prev, cnt_prev = (
                float(row["vol_prev"] or 0),
                float(row["turn_prev"] or 0),
                float(row["avg_prev"] or 0),
                int(row["cnt_prev"] or 0),
            )
            vol_w30 = float(row["vol_w30"] or 0)
            turn_w30 = float(row["turn_w30"] or 0)
            cnt_w30 = int(row["cnt_w30"] or 0)
            w30_turnover[tid] = turn_w30

            price = _window_price(turn_recent, vol_recent, avg_recent, cnt_recent)
            base = _window_price(turn_prev, vol_prev, avg_prev, cnt_prev)
            if price is None or base is None or base <= 0:
                continue  # 算不出涨幅 → 不进榜（不用 0 冒充）
            qualified = turn_w30 > 0 and cnt_w30 >= ADMISSION_MIN_COVERED_DAYS
            if qualified_only and not qualified:
                continue
            volume = vol_recent / window
            volume_ratio = volume / (vol_w30 / ADMISSION_DAYS) if vol_w30 > 0 else None
            items.append(
                {
                    "typeId": tid,
                    "name": str(tid),
                    "price": round(price, 2),
                    "chg": round((price / base - 1.0) * 100.0, 2),
                    "volume": round(volume, 2),
                    "volume_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
                    "qualified": qualified,
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

"""订单簿深度取价 — 纯函数，无 DB/Qt/缓存。

直接取 `min(卖价)` / `max(买价)` 会被「只有一两个单位」的凑数挂单带偏。
实例（大型EMP立体炸弹 I，Jita）：卖单里有一笔 2 个 @543,800，而真实深度是
1,640 个 @995,900 —— 成本核算因此严重偏低。

改为按挂单量累计：卖侧从低价往上累加、买侧从高价往下累加，取「累计量达到阈值」
时的价格，从而跳过明显凑数的薄挂单。

阈值同时受两个上限约束（见 core/constants.py 的 PRICE_DEPTH_* 常量）：

- 该物品该侧总挂单量的 1%
- **该侧挂单量的中位数**

第二个上限是必须的：EVE 里常见「1 ISK × 巨量」的钓鱼挂单（实例物品的买单里
就有一笔 1 ISK × 10,000）。若只按总量比例定阈值，一笔 1 ISK × 1,000,000 的
挂单会把阈值抬到 10,006，超过真实挂单量 → 买价直接跌到 1 ISK。用中位挂单量
封顶后，阈值只与「典型挂单大小」有关，不受单笔巨量离群单影响。

被两处聚合器共用（全量更新 services/importers/getprices.py、
工业页定向刷新 ui_pyside6/workers/industry_page_workers.py）——
只改一处会被另一处打回最低价。
"""

from __future__ import annotations

from statistics import median

from core.constants import PRICE_DEPTH_MIN_BOOK, PRICE_DEPTH_MIN_UNITS, PRICE_DEPTH_VOLUME_PCT

SELL = "sell"
BUY = "buy"


def depth_price(levels: list[tuple[float, int]], side: str) -> float | None:
    """按挂单量累计取价。

    Args:
        levels: `[(price, volume_remain), ...]`，顺序无关。
        side: `SELL`（从低价往上累计）或 `BUY`（从高价往下累计）。

    Returns:
        取到的价格；`levels` 为空时返回 None。

    盘口总量低于 `PRICE_DEPTH_MIN_BOOK` 时直接取极值——整个市场都很薄时，
    薄单就是真实价，没有「凑数单」可剔除。
    """
    if not levels:
        return None

    ordered = sorted(levels, key=lambda lv: lv[0], reverse=side == BUY)
    volumes = [vol for _, vol in ordered]
    total = sum(volumes)

    if total < PRICE_DEPTH_MIN_BOOK:
        return ordered[0][0]

    threshold = max(
        PRICE_DEPTH_MIN_UNITS,
        min(total * PRICE_DEPTH_VOLUME_PCT, median(volumes)),
    )
    cumulative = 0
    for price, vol in ordered:
        cumulative += vol
        if cumulative >= threshold:
            return price
    return ordered[-1][0]  # 兜底：threshold ≤ total，正常不会走到这里

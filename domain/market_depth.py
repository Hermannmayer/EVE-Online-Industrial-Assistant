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
工业页定向刷新 ui_qml/workers/industry_page_workers.py）——
只改一处会被另一处打回最低价。

本模块另外提供 `sell_price_reliable()`：`depth_price()` 解决的是「同一侧内部挑哪一档」，
它解决的是「这一侧的价能不能拿去估值」。仓库/资产估值取的是市场**最低卖单价**，
而极薄的单边品种里一笔离谱卖单就是全市场最低价，估值因此虚高数千倍 ——
判据落在盘口绝对量级上，不看价格倍数（阈值含义与实测证据见 core/constants.py 的
`PRICE_CREDIBLE_*` 注释）。
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import median

from core.constants import (
    PRICE_CREDIBLE_MIN_SELL_VOLUME,
    PRICE_CREDIBLE_SELL_BUY_VOLUME_RATIO,
    PRICE_DEPTH_MIN_BOOK,
    PRICE_DEPTH_MIN_UNITS,
    PRICE_DEPTH_VOLUME_PCT,
)

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


def _book_volume(row: Mapping[str, object], key: str) -> float:
    """盘口量取值：缺失/None/非数值/负数一律按 0。"""
    raw = row.get(key) or 0
    if not isinstance(raw, (int, float, str)):
        return 0.0  # 认不出的类型（dict/list 等）—— 当没量，调用方按 0 处理
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def sell_price_reliable(row: Mapping[str, object]) -> bool | None:
    """卖单价能不能拿去估值 —— 三态判定，纯函数，只读这 4 个键。

    入参 dict 键：``sell_price`` / ``buy_price`` / ``buy_volume`` / ``sell_volume``
    （就是 ``market_prices`` 的同名列；volume 是该侧总挂单量）。

    Returns:
        - `None`：**没有卖单价**（缺/None/0）—— 本来就没价可估，谈不上可不可信。
          调用方据此把这类行不进「不可信」统计，否则没市价的物品（基础矿物等）
          会把「N 项未计入」刷成大数字，失去意义。
        - `False`：有卖单价但**立不住**，其中两种情形：
          1. 卖侧盘口量低于 `PRICE_CREDIBLE_MIN_SELL_VOLUME`，且相对买侧不足
             `PRICE_CREDIBLE_SELL_BUY_VOLUME_RATIO` —— 极薄单边，一笔离谱卖单就是「最低卖价」；
          2. 没有买单价（缺/0）—— 「卖得掉」这件事根本没有对手盘作证。
        - `True`：可信，可以拿去估值。两侧都很薄的品种只要卖侧 ≥ 阈值就放行 ——
          薄但真实的市场不该被误杀（实例：内部隔层卖侧 486 件 / 买侧 85.9 万件）。
    """
    if _book_volume(row, "sell_price") <= 0:
        return None
    if _book_volume(row, "buy_price") <= 0:
        return False
    sell_vol = _book_volume(row, "sell_volume")
    if sell_vol >= PRICE_CREDIBLE_MIN_SELL_VOLUME:
        return True
    return sell_vol >= _book_volume(row, "buy_volume") * PRICE_CREDIBLE_SELL_BUY_VOLUME_RATIO

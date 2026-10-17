"""价格走势图的几何纯函数（原 QML 对话框已删除，仅保留这组纯算法）。

历史：这里原先还有 `PriceChartBridge` / `PriceChartQmlDialog`（QML 版价格走势图对话框）。
该对话框在订单弹窗删除后失去入口、长期无调用方，已随死代码清理删除；**只保留纯函数**，
因为查询页空闲态仪表盘的资产折线（`query_dashboard_bridge`）在复用它们：

    from ui_qml.bridge.price_chart_bridge import axis_values, map_values, nice_range, pick_indices

**几何计算全在本模块的纯函数里**（轴范围、刻度值、点坐标归一化）。抽出来的原因：
nice-number 取整、双轴映射这类算法最容易错，放在 Python 里才能单测；留在 QML 的 JS 里
就只能靠截图肉眼看。用归一化（0..1）而不是像素坐标，是为了不让 Python 去猜画布尺寸 ——
窗口一缩放，像素就会变，归一化不会。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "axis_values",
    "map_values",
    "nice_range",
    "pick_indices",
    "plot_model",
]

#: 数据非法时的兜底轴（下界 / 上界 / 步长）
_DEFAULT_AXIS = (0.0, 1.0, 1.0)

#: 空模型：QML 只看 `isEmpty` 决定画不画
_EMPTY_PLOT: dict = {
    "isEmpty": True,
    "count": 0,
    "series": [],
    "xTicks": [],
    "priceTicks": [],
    "volumeTicks": [],
}


# ════════════════════════════════════════════════════════════
#  纯几何（可脱离 Qt 单测）
# ════════════════════════════════════════════════════════════


def nice_range(lo: float, hi: float, ticks: int = 5) -> tuple[float, float, float]:
    """把 [lo, hi] 扩成「好看」的轴范围 → (下界, 上界, 刻度步长)。

    步长取 1 / 2 / 2.5 / 5 / 10 × 10ⁿ 里第一个 ≥「原始步长」的值（Qt 的
    nice numbers 就是这个口径），上下界再按步长向外取整。
    """
    if ticks < 1:
        ticks = 1
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return _DEFAULT_AXIS
    if hi < lo:
        lo, hi = hi, lo
    if math.isclose(lo, hi):
        # 全平序列（每天都一个价）：给一个居中的窗口，否则轴退化成一个点、下面还要除零
        span = abs(lo) * 0.1 or 1.0
        lo, hi = lo - span, hi + span

    raw = (hi - lo) / ticks
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = magnitude * 10.0
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = factor * magnitude
        if step >= raw:
            break

    # 浮点收尾：0.1 步长算出来的第 15 份是 1.5000000000000002，先按步长量级取整；
    # 取界时的 ±1e-9 也是同一件事 —— 1.5/0.1 是 14.999…，不加它会少取一格
    digits = max(0, -int(math.floor(math.log10(step))) + 1)
    return (
        round(math.floor(lo / step + 1e-9) * step, digits),
        round(math.ceil(hi / step - 1e-9) * step, digits),
        round(step, digits),
    )


def axis_values(lo: float, hi: float, step: float) -> list[float]:
    """[lo, hi] 上按 step 铺刻度值（含两端）。step 非正或范围非法时返回空表。"""
    if step <= 0 or hi < lo:
        return []
    count = int(math.floor((hi - lo) / step + 1e-9))
    return [round(lo + i * step, 10) for i in range(count + 1)]


def map_values(values: Sequence[float], lo: float, hi: float) -> list[float]:
    """数值 → 轴内 0..1 位置（0 = 轴下界，1 = 轴上界）。越界夹住，不画到轴外。"""
    span = hi - lo
    if span <= 0:
        return [0.0 for _ in values]
    return [min(1.0, max(0.0, (float(v) - lo) / span)) for v in values]


def pick_indices(count: int, max_ticks: int) -> list[int]:
    """从 count 个点里挑 ≤ max_ticks 个均匀下标（必含首尾）。

    日期刻度不像数值刻度能算「整点」，只能在已有下标上采样 —— 所以单独一个函数。
    """
    if count <= 0 or max_ticks <= 0:
        return []
    if count <= max_ticks:
        return list(range(count))
    if max_ticks == 1:
        return [0]
    return sorted({round(i * (count - 1) / (max_ticks - 1)) for i in range(max_ticks)})


def _ticks(lo: float, hi: float, step: float) -> list[dict]:
    """数值刻度 → {pos: 0..1, label: 文本}。标签沿用原 `setLabelFormat("%.0f")`。"""
    values = axis_values(lo, hi, step)
    return [
        {"pos": pos, "label": f"{value:,.0f}"} for value, pos in zip(values, map_values(values, lo, hi), strict=True)
    ]


def plot_model(data: Sequence[Mapping[str, Any]], *, max_x_ticks: int = 6, max_y_ticks: int = 5) -> dict:
    """历史数据 → 画布模型（纯函数，保留给复用方与测试）。

    形状：
        {isEmpty, count,
         series: [{label, points: [{x, y}]}],   # 0=日均价(ISK) 1=成交量
         xTicks / priceTicks / volumeTicks: [{pos, label}]}

    x 按**下标**均分而不是按时间戳：ESI 历史是逐日的、无缺口，按日期算还得处理
    「某天缺数据」的空档，收益为零。
    """
    prices: list[float] = []
    volumes: list[float] = []
    dates: list[str] = []
    for entry in data:
        if not entry:
            continue
        try:
            prices.append(float(entry.get("average") or 0.0))
            volumes.append(float(entry.get("volume") or 0.0))
        except (TypeError, ValueError):
            continue
        dates.append(str(entry.get("date", "")))

    count = len(dates)
    if count == 0:
        return dict(_EMPTY_PLOT)

    price_lo, price_hi, price_step = nice_range(min(prices), max(prices), max_y_ticks)
    vol_lo, vol_hi, vol_step = nice_range(min(volumes), max(volumes), max_y_ticks)
    # 价格与成交量没有负数：轴下界贴到 0，免得小幅波动被拉到负半轴、看着像「跌穿」
    if min(prices) >= 0:
        price_lo = max(price_lo, 0.0)
    if min(volumes) >= 0:
        vol_lo = max(vol_lo, 0.0)

    xs = [i / (count - 1) if count > 1 else 0.5 for i in range(count)]
    price_pos = map_values(prices, price_lo, price_hi)
    vol_pos = map_values(volumes, vol_lo, vol_hi)

    return {
        "isEmpty": False,
        "count": count,
        "series": [
            {"label": "日均价 (ISK)", "points": [{"x": x, "y": y} for x, y in zip(xs, price_pos, strict=True)]},
            {"label": "成交量", "points": [{"x": x, "y": y} for x, y in zip(xs, vol_pos, strict=True)]},
        ],
        "xTicks": [{"pos": xs[i], "label": dates[i]} for i in pick_indices(count, max_x_ticks)],
        "priceTicks": _ticks(price_lo, price_hi, price_step),
        "volumeTicks": _ticks(vol_lo, vol_hi, vol_step),
    }

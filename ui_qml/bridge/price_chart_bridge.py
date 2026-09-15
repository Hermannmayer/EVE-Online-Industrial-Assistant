"""价格走势图对话框的桥与 QML 宿主（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/price_chart.py` 的 `PriceChartDialog`（QtCharts 版）：
后台拉某物品的历史价 → 画「日均价 + 成交量」双 Y 轴折线。

**几何计算全在本模块的纯函数里**（轴范围、刻度值、点坐标归一化），QML 那份 `Canvas`
只负责「归一化坐标 × 画布尺寸」的落点。抽出来的原因：nice-number 取整、双轴映射
这类算法最容易错，放在 Python 里才能单测；留在 Canvas 的 JS 里就只能靠截图肉眼看。
用归一化（0..1）而不是像素坐标，是为了不让 Python 去猜画布尺寸 —— 窗口一缩放，
像素就会变，归一化不会。

取数仍是原 `PriceHistoryWorker`（那份实现只留一份）。原版价格轴上没有显式
`setRange`，靠 QChart 附加序列时的自动范围 + nice numbers，这里的 `nice_range`
就是照那个口径重写的。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "PriceChartBridge",
    "PriceChartQmlDialog",
    "axis_values",
    "map_values",
    "nice_range",
    "pick_indices",
    "plot_model",
]

_QML_FILE = "dialogs/PriceChartDialog.qml"

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

#: 已从对话框摘出、还在收尾的取价线程（见 `_detach_worker`）
_DETACHED: set[Any] = set()


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
    """历史数据 → 画布模型（纯函数）。

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


# ════════════════════════════════════════════════════════════
#  桥 / 宿主
# ════════════════════════════════════════════════════════════


def _history_worker(type_id: int, parent: Any) -> Any:
    """取价线程 —— 直接复用原 `PriceHistoryWorker`（区域走它的默认值，与原版一致）。

    单独包一层是为了测试能替换掉它：否则每构造一次对话框就会真去读 market.db、
    打 ESI，测试既慢又不确定。
    """
    from ui_qml.workers.price_history_worker import PriceHistoryWorker

    return PriceHistoryWorker(type_id, parent=parent)


def _detach_worker(worker: Any) -> None:
    """关窗收尾：拉不了断，那就别让它随对话框一起被销毁。

    ESI 请求是阻塞的，`requestInterruption()` 对它无效（原版 `closeEvent` 也只请求中断）。
    而 `QThread` 在运行中被析构时 Qt 直接 `abort()` —— 进程静默死掉、无日志。
    所以：先请求中断并等一小会儿；还没完就把它从桥的子对象里摘出来、挂到模块级集合上
    等它自己结束（同 `npc_seller_bridge` / `blueprint_actions` 的强引用保活做法）。
    """
    is_running = getattr(worker, "isRunning", None)
    if worker is None or not callable(is_running) or not is_running():
        return
    worker.requestInterruption()
    if worker.wait(500):
        return
    _DETACHED.add(worker)
    worker.setParent(None)
    worker.finished.connect(lambda: _DETACHED.discard(worker))


class PriceChartBridge(DialogBridge):
    """价格走势图的 QML 后端。"""

    contentChanged = Signal()

    def __init__(self, type_id: int, name: str) -> None:
        super().__init__()
        self._type_id = int(type_id)
        self._name = str(name)
        self._data: list[dict] = []
        self._plot: dict = dict(_EMPTY_PLOT)
        self._status = "加载中..."
        self._worker: Any = None
        self.set_title(f"价格走势 — {self._name}")

    #: 顶部标题 —— 与原 `_title_label` 文案逐字一致
    headerText = Property(str, lambda self: f"{self._name} (Type ID: {self._type_id})", constant=True)
    #: 状态行：「加载中… / 已加载 N 天数据 / 错误: …」（与原 `_status_label` 同文案）
    statusText = Property(str, lambda self: self._status, notify=contentChanged)
    #: 画布模型，见 `plot_model`
    plot = Property(dict, lambda self: self._plot, notify=contentChanged)

    def day_count(self) -> int:
        """给 Python 侧读的口子（`plot` 是 dict，直接读会拿到 QVariant）。"""
        return int(self._plot.get("count", 0))

    @Slot()
    def reload(self) -> None:
        """起后台线程取历史价（宿主构造时调一次）。"""
        if self._worker is not None and self._worker.isRunning():
            return
        worker = _history_worker(self._type_id, self)
        self._worker = worker
        worker.finished_signal.connect(self._on_data_loaded)
        worker.error_signal.connect(self._on_error)
        worker.start()

    def _on_data_loaded(self, type_id: int, data: list[dict]) -> None:
        # 期间用户可能已经换了物品（原版同样按 type_id 过滤）
        if int(type_id) != self._type_id:
            return
        self._data = list(data or [])
        self._plot = plot_model(self._data)
        self._status = f"已加载 {self.day_count()} 天数据"
        self.contentChanged.emit()

    def _on_error(self, type_id: int, error: str) -> None:
        if int(type_id) != self._type_id:
            return
        self._status = f"错误: {error}"
        self.contentChanged.emit()

    def stop(self) -> None:
        """关窗收尾 —— `QmlDialog.done/closeEvent` 都会调它（名字是基类约定）。"""
        _detach_worker(self._worker)
        self._worker = None


class PriceChartQmlDialog(QmlDialog):
    """QML 版「价格走势图」。`PriceChartDialog(type_id, name, parent)` 的调用方原样可用。"""

    def __init__(self, type_id: int, name: str, parent: Any = None) -> None:
        bridge = PriceChartBridge(type_id, name)
        # 尺寸与原版一致：最小 800×500、初始 900×550
        super().__init__(_QML_FILE, bridge, parent=parent, size=(800, 500))
        self.resize(900, 550)
        self._chart_bridge = bridge
        bridge.reload()

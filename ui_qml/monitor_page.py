"""市场监控页的 QML 组装规格。

「市场监控」（导航键沿用 `watchlist`）是**一个页面两块内容**：

- **大盘**（首页，默认选中）→ `pages/MarketPulsePane.qml` + `ui_qml/bridge/market_pulse_bridge.py`
- **关注物品**（子视图）→ `pages/WatchlistPage.qml` + `ui_qml/bridge/watchlist_bridge.py`

为什么需要页工厂而不是 `QML_BRIDGES` 的单 bridge 形态：QML 只能从 context property 取桥，
这里有两个（与工业页的 `bridge` + `planTableBridge` 同构，见 `ui_qml/industry_page.py`）。

⚠️ **两个 context property 的顺序/命名不能反**：
- `bridge` 给**关注页**（它按 `bridge` 取；外壳的页面钩子与状态栏也走这个桥）
- `pulseBridge` 给大盘（`MarketPulsePane.qml` 优先认它、没有才退回 `bridge`）

外壳按鸭子类型探测页面钩子（`shutdown` / `on_shown` / `save_state` / `restore_state` /
`refresh_display` / `update_status_bar`，见 `ui_qml/shell_window.py`）。这里有两个桥，
所以用一个**转发器**当钩子实现者：默认全部转发给关注桥；`shutdown` / `on_shown` 两个
生命周期钩子**两个桥都调**（大盘桥自己起了 `IndexRefreshWorker` 线程，漏掉就是
「QThread 在运行中被析构」——见 `ui_qml/workers/lifecycle.py` 的告诫）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ui_qml.registry import PageSpec

if TYPE_CHECKING:
    from ui_qml.bridge.market_pulse_bridge import MarketPulseBridge
    from ui_qml.bridge.watchlist_bridge import WatchlistBridge

__all__ = ["MONITOR_QML", "build_monitor_spec", "monitor_spec"]

#: QML 页面路径（相对 ui_qml/qml/）
MONITOR_QML = "pages/MarketMonitorPage.qml"


class _MonitorHooks:
    """两个桥的钩子转发器：默认走关注桥，生命周期钩子两个都调。"""

    def __init__(self, watchlist: Any, pulse: Any) -> None:
        self._watchlist = watchlist
        self._pulse = pulse

    def shutdown(self) -> None:
        for bridge in (self._watchlist, self._pulse):
            stop = getattr(bridge, "shutdown", None)
            if callable(stop):
                stop()

    def on_shown(self) -> None:
        # 大盘页进门要刷新（首屏数据贵，且用户切回来时该看到新的）；关注页保留它自己的行为
        for bridge in (self._watchlist, self._pulse):
            hook = getattr(bridge, "on_shown", None)
            if callable(hook):
                hook()

    def __getattr__(self, name: str) -> Any:
        """其余钩子一律转发给关注桥（它才是这个导航键原来的实现者）。"""
        return getattr(self._watchlist, name)


def monitor_spec(watchlist_bridge: WatchlistBridge, pulse_bridge: MarketPulseBridge) -> PageSpec:
    """市场监控页的组装规格：两个 context property + 钩子转发器。"""
    return PageSpec(
        MONITOR_QML,
        {"bridge": watchlist_bridge, "pulseBridge": pulse_bridge},
        object_name="market_monitor_page_qml",
        hooks=_MonitorHooks(watchlist_bridge, pulse_bridge),
    )


def build_monitor_spec(shell: Any) -> PageSpec:
    """注册表页工厂：造两个桥，返回组装规格 —— **不碰宿主**。"""
    from ui_qml.bridge.market_pulse_bridge import MarketPulseBridge
    from ui_qml.bridge.watchlist_bridge import WatchlistBridge

    return monitor_spec(WatchlistBridge(shell), MarketPulseBridge(shell))

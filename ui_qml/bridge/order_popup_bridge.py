"""订单弹窗的桥与 QML 宿主（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/query/query_order_popup.py` 的 `OrderPopup`：
双击物品行 → 悬浮窗展示该物品买单/卖单各前 5 条 → 右上角「走势图」再弹价格历史
（`PriceChartQmlDialog`，本批同迁 —— 只换中间那层会留下「QML 里弹出 Widgets 窗口」的残留）。

**取数不在这里**：`OrderFetchWorker` / `order_cache` / `get_order_name` 全部沿用原模块那份，
这里只把弹窗换成 QML 宿主。集成时把 `query_bridge` 里那行
`from ui_pyside6.views.query.query_order_popup import do_load_orders` 改成从本模块导入即可，
`OrderPopupHost` 适配壳一行都不用动 —— 它提供的 `_model` / `_region_id` / `_status_label`
`mapToGlobal` / `rect()` 正是本模块 `do_load_orders` 需要的那组名字。
"""

from __future__ import annotations

import time as _time
from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Property, Qt, Signal, Slot

from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "OrderPopupBridge",
    "OrderPopupQmlDialog",
    "do_load_orders",
    "hide_order_popup",
    "order_rows",
    "popup_title",
    "show_order_popup",
]

_QML_FILE = "dialogs/OrderPopupDialog.qml"

#: 缓存有效期，与 Widgets 版同口径（5 分钟内不重新打 ESI）
_CACHE_TTL = 300

#: 列宽口径：空间站那列吃满剩余空间（原版把整行拼成一句文本，这里拆成列更好扫）
_COLUMNS = [
    {"title": "#", "width": 44},
    {"title": "价格 (ISK)", "width": 150},
    {"title": "数量", "width": 90},
    {"title": "空间站", "width": 0},
]


def popup_title(name: str, type_id: int) -> str:
    """弹窗标题 —— 与原 `_title_label` 的文案逐字一致。"""
    return f"{name} (Type ID: {type_id})"


def order_rows(
    orders: Sequence[Mapping[str, Any]],
    token: str,
    station_names: Mapping[int, str] | None = None,
) -> list[dict]:
    """订单列表 → 单元格行（纯函数，便于单测）。

    买入染绿、卖出染红（对齐原 `QListWidgetItem.setForeground`）；
    空间站名取自 ESI 的名字缓存，缓存没命中就退回 location_id —— 原版如此。
    """
    names = station_names or {}
    rows: list[dict] = []
    for i, order in enumerate(orders):
        loc_id = int(order["location_id"])
        station = names.get(loc_id, str(loc_id))
        rows.append(
            {
                "cells": [
                    cell(f"#{i + 1}", token),
                    cell(f"{order['price']:,.2f}", token),
                    cell(f"{order['volume_remain']:,}", token),
                    cell(f"{station} [{loc_id}]", token),
                ]
            }
        )
    return rows


class OrderPopupBridge(DialogBridge):
    """订单弹窗的 QML 后端。"""

    contentChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._type_id: int | None = None
        self._name = ""
        self._buy_rows: list[dict] = []
        self._sell_rows: list[dict] = []

    #: 列定义走同一份常量，QML 不用自己写表头
    columns = Property(list, lambda self: [dict(c) for c in _COLUMNS], constant=True)
    buyRows = Property(list, lambda self: list(self._buy_rows), notify=contentChanged)
    sellRows = Property(list, lambda self: list(self._sell_rows), notify=contentChanged)

    def set_orders(self, type_id: int, name: str, buy_orders: list, sell_orders: list) -> None:
        """填数据 —— 与 `OrderPopup.set_orders` 同名同参，调用方原样可用。

        空列表不是错误（该物品可能没人挂单），由 QML 侧 `FSummaryTable.emptyText`
        给出「无买单数据 / 无卖单数据」，比原来额外塞一行占位项干净。
        """
        from ui_pyside6.views.query.query_order_popup import _station_name_cache

        self._type_id = int(type_id)
        self._name = str(name)
        self.set_title(popup_title(self._name, self._type_id))
        self._buy_rows = order_rows(buy_orders, "GREEN", _station_name_cache)
        self._sell_rows = order_rows(sell_orders, "RED", _station_name_cache)
        self.contentChanged.emit()

    @Slot()
    def openChart(self) -> None:
        """右上角「走势图」—— 弹价格历史（三级链的第三层）。

        parent 走 `DialogBridge.host_widget()`（= 本弹窗那个 QDialog），
        **不自己存 `self.dialog`**：那会形成 Python↔C++ 环，GC 先没掉窗口就是一次崩溃
        （见 `dialog_host.DialogBridge.host_widget` 的说明）。
        """
        if not self._type_id:
            return
        from ui_qml.bridge.price_chart_bridge import PriceChartQmlDialog

        PriceChartQmlDialog(self._type_id, self._name, self.host_widget()).exec()


class OrderPopupQmlDialog(QmlDialog):
    """QML 版「订单弹窗」。`OrderPopup(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        bridge = OrderPopupBridge()
        super().__init__(_QML_FILE, bridge, parent=parent, size=(620, 480))
        self._order_bridge = bridge
        # 与 Widgets 版逐字一致：`Qt.Popup` —— 点窗口外任意处自动关，且不进任务栏。
        # 必须在 QmlDialog 构造完之后设：它建的是普通 QDialog（模态子对话框的宿主），
        # 本弹窗要的是浮层语义，窗口标志按原版在这里覆盖掉。
        self.setWindowFlags(Qt.WindowType.Popup)

    def set_orders(self, type_id: int, name: str, buy_orders: list, sell_orders: list) -> None:
        self._order_bridge.set_orders(type_id, name, buy_orders, sell_orders)


# ── 与旧模块同名的编排函数（集成时整组替换即可）────────────────


def _legacy() -> Any:
    """懒导入旧模块。

    模块级导入会把 QtWidgets / icons / theme 整条链拉进 `ui_qml.bridge` 的导入期，
    而不碰订单弹窗的测试没必要付这个代价（与其余桥的懒导入同因）。
    """
    from ui_pyside6.views.query import query_order_popup

    return query_order_popup


def show_order_popup(page: Any, type_id: int, name: str) -> None:
    """显示订单弹窗（对齐原 `query_order_popup.show_order_popup`，只换弹窗类）。"""
    if page._order_popup:
        page._order_popup.hide()
        page._order_popup.deleteLater()
    page._order_popup = OrderPopupQmlDialog(page)
    page._order_popup.set_orders(type_id, name, [], [])
    center = page.mapToGlobal(page.rect().center())
    page._order_popup.move(center.x() - 275, center.y() - 200)
    page._order_popup.show()


def hide_order_popup(page: Any) -> None:
    """隐藏并销毁订单弹窗（对齐原 `query_order_popup.hide_order_popup`）。"""
    if page._order_popup:
        page._order_popup.hide()
        page._order_popup.deleteLater()
        page._order_popup = None
    page._current_order_type_id = None


def do_load_orders(page: Any, type_id: int) -> None:
    """加载并展示订单 —— 行为与原 `query_order_popup.do_load_orders` 逐项一致。

    只有「弹窗是哪个类」不同：worker、缓存、名称解析等仍调旧模块那份实现，
    不在这里抄第二份取数逻辑（迁移期只留一份业务实现）。
    """
    legacy = _legacy()
    page._current_order_type_id = type_id
    name = legacy.get_order_name(page, type_id)

    show_order_popup(page, type_id, name)

    cached = legacy.order_cache.get(type_id)
    if cached:
        buy_orders, sell_orders, fetch_time = cached
        if _time.time() - fetch_time < _CACHE_TTL:
            page._order_popup.set_orders(type_id, name, buy_orders, sell_orders)
            page._status_label.setText("订单数据已加载（缓存）")
            return

    page._status_label.setText("正在从 ESI 获取实时订单...")
    worker = legacy.OrderFetchWorker(type_id, page._region_id, page)
    worker.finished_signal.connect(lambda tid, buy, sell: legacy._on_orders_fetched(page, tid, buy, sell))
    worker.error_signal.connect(lambda tid, err: legacy._on_order_error(page, tid, err))
    worker.start()

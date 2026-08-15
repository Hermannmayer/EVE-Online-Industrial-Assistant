"""
订单弹窗 — OrderPopup + OrderFetchWorker + 订单管理辅助函数
"""

import asyncio
import time as _time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import ui_pyside6.theme as theme

ESI_BASE_URL = "https://esi.evetech.net/latest"
_station_name_cache: dict[int, str] = {}

# 全局订单缓存 (key: type_id -> (buy_orders, sell_orders, fetch_time))
order_cache: dict[int, tuple] = {}


class OrderFetchWorker(QThread):
    """后台获取 ESI 订单数据"""

    finished_signal = Signal(int, list, list)  # type_id, buy_orders, sell_orders
    error_signal = Signal(int, str)  # type_id, error

    def __init__(self, type_id: int, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._region_id = region_id

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            buy, sell = loop.run_until_complete(self._fetch())
            self.finished_signal.emit(self._type_id, buy, sell)
        except Exception as e:
            self.error_signal.emit(self._type_id, str(e))
        finally:
            if loop is not None:
                loop.close()

    async def _fetch(self):
        from services.client import APIClient

        async with APIClient(timeout=30) as client:
            url = f"{ESI_BASE_URL}/markets/{self._region_id}/orders/"
            buy_data = await client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=buy") or []
            sell_data = await client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=sell") or []

        buy_orders = sorted(buy_data, key=lambda o: o["price"], reverse=True)[:5]
        sell_orders = sorted(sell_data, key=lambda o: o["price"])[:5]

        all_loc_ids = set()
        for o in buy_orders + sell_orders:
            all_loc_ids.add(o["location_id"])

        await self._resolve_names(list(all_loc_ids))
        return buy_orders, sell_orders

    async def _resolve_names(self, location_ids: list[int]):
        need = [lid for lid in location_ids if lid not in _station_name_cache]
        if not need:
            return
        url = f"{ESI_BASE_URL}/universe/names/"
        from services.client import APIClient

        async with APIClient(timeout=30) as client:
            for i in range(0, len(need), 1000):
                chunk = need[i : i + 1000]
                try:
                    data = await client.post(url, json=chunk)
                    if data:
                        for item in data:
                            _station_name_cache[item["id"]] = item.get("name", str(item["id"]))
                    else:
                        for lid in chunk:
                            _station_name_cache.setdefault(lid, str(lid))
                except Exception:
                    for lid in chunk:
                        _station_name_cache.setdefault(lid, str(lid))


class OrderPopup(QDialog):
    """悬浮订单详情 — 双击物品行时弹出，点击外部自动关闭"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setMinimumSize(620, 480)
        self.setObjectName("order_popup")
        self._type_id: int | None = None
        self._name: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Title row with chart button
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel("")
        self._title_label.setObjectName("order_title")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        self._chart_btn = QPushButton("📈 走势图")
        self._chart_btn.setObjectName("order_chart_btn")
        self._chart_btn.clicked.connect(self._on_chart_clicked)
        title_row.addWidget(self._chart_btn)
        layout.addLayout(title_row)

        # 买单 (上半区)
        buy_header = QLabel("买单 (Buy)")
        buy_header.setObjectName("buy_header")
        layout.addWidget(buy_header)
        self._buy_list = QListWidget()
        self._buy_list.setObjectName("buy_list")
        layout.addWidget(self._buy_list)

        # 卖单 (下半区)
        sell_header = QLabel("卖单 (Sell)")
        sell_header.setObjectName("sell_header")
        layout.addWidget(sell_header)
        self._sell_list = QListWidget()
        self._sell_list.setObjectName("sell_list")
        layout.addWidget(self._sell_list)

    def set_orders(self, type_id: int, name: str, buy_orders: list, sell_orders: list):
        self._title_label.setText(f"{name} (Type ID: {type_id})")
        self._type_id = type_id
        self._name = name

        self._buy_list.clear()
        if buy_orders:
            for i, order in enumerate(buy_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station = _station_name_cache.get(loc_id, str(loc_id))
                item = QListWidgetItem(f"#{i + 1}  {price} ISK  ×{vol}   {station} [{loc_id}]")
                item.setForeground(QColor(theme.GREEN))
                self._buy_list.addItem(item)
        else:
            item = QListWidgetItem("无买单数据")
            item.setForeground(QColor(theme.TEXT_SECONDARY))
            self._buy_list.addItem(item)

        self._sell_list.clear()
        if sell_orders:
            for i, order in enumerate(sell_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station = _station_name_cache.get(loc_id, str(loc_id))
                item = QListWidgetItem(f"#{i + 1}  {price} ISK  ×{vol}   {station} [{loc_id}]")
                item.setForeground(QColor(theme.RED))
                self._sell_list.addItem(item)
        else:
            item = QListWidgetItem("无卖单数据")
            item.setForeground(QColor(theme.TEXT_SECONDARY))
            self._sell_list.addItem(item)

    def _on_chart_clicked(self):
        """打开价格走势图"""
        if self._type_id:
            from importlib import import_module

            price_chart = import_module("ui_pyside6.views.price_chart")
            dlg = price_chart.PriceChartDialog(self._type_id, self._name, self.parent())
            dlg.exec()


def get_order_name(page, type_id: int) -> str:
    """根据 type_id 从页面的模型中查找物品名称"""
    name = str(type_id)
    for i in range(page._model.rowCount()):
        row = page._model.get_row(i)
        if row and row["type_id"] == type_id:
            if row["zh"] and row["en"]:
                name = f"{row['zh']} ({row['en']})"
            else:
                name = row["zh"] or row["en"] or str(type_id)
            break
    return name


def do_load_orders(page, type_id: int):
    """执行订单加载逻辑 (替代 QueryPage._load_orders)"""
    page._current_order_type_id = type_id
    name = get_order_name(page, type_id)

    # 显示弹窗并立即展示缓存数据（如有）
    show_order_popup(page, type_id, name)

    cached = order_cache.get(type_id)
    if cached:
        buy_orders, sell_orders, fetch_time = cached
        if _time.time() - fetch_time < 300:
            page._order_popup.set_orders(type_id, name, buy_orders, sell_orders)
            page._status_label.setText("订单数据已加载（缓存）")
            return

    page._status_label.setText("正在从 ESI 获取实时订单...")
    worker = OrderFetchWorker(type_id, page._region_id, page)
    worker.finished_signal.connect(lambda tid, buy, sell: _on_orders_fetched(page, tid, buy, sell))
    worker.error_signal.connect(lambda tid, err: _on_order_error(page, tid, err))
    worker.start()


def show_order_popup(page, type_id: int, name: str):
    """显示订单弹窗 (替代 QueryPage._show_order_popup)"""
    if page._order_popup:
        page._order_popup.hide()
        page._order_popup.deleteLater()
    page._order_popup = OrderPopup(page)
    page._order_popup.set_orders(type_id, name, [], [])
    center = page.mapToGlobal(page.rect().center())
    page._order_popup.move(center.x() - 275, center.y() - 200)
    page._order_popup.show()


def hide_order_popup(page):
    """隐藏订单弹窗 (替代 QueryPage._hide_order_popup)"""
    if page._order_popup:
        page._order_popup.hide()
        page._order_popup.deleteLater()
        page._order_popup = None
    page._current_order_type_id = None


def _on_orders_fetched(page, type_id: int, buy_orders: list, sell_orders: list):
    """订单获取完成后的处理"""
    order_cache[type_id] = (buy_orders, sell_orders, _time.time())
    if type_id == page._current_order_type_id and page._order_popup and page._order_popup.isVisible():
        name = get_order_name(page, type_id)
        page._order_popup.set_orders(type_id, name, buy_orders, sell_orders)
        page._status_label.setText("实时订单数据已加载")


def _on_order_error(page, type_id: int, error: str):
    """订单获取出错处理"""
    if type_id == page._current_order_type_id:
        page._status_label.setText(f"获取订单失败: {error}")

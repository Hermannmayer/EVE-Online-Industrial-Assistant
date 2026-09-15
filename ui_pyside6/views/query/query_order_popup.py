"""
订单弹窗 — OrderPopup + OrderFetchWorker + 订单管理辅助函数
"""

import time as _time

from PySide6.QtCore import Qt
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

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme
from ui_qml.workers.order_workers import (
    OrderFetchWorker,
    _on_order_error,
    _on_orders_fetched,
    _station_name_cache,
    get_order_name,
    order_cache,
)


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
        self._chart_btn = QPushButton()
        icons.set_button_icon(self._chart_btn, "trend-up", text="走势图")
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

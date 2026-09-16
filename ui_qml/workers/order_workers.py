"""订单取数的共享部分：缓存 + ESI 线程。

原先在 `ui_pyside6/views/query/query_order_popup.py`，与 OrderPopup（Widgets 悬浮窗）同处一文件；
QML 版订单弹窗复用同一份缓存与线程，故拆出来。
"""

import asyncio
import time as _time

from PySide6.QtCore import QThread, Signal

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
            # 被请求中断（页面销毁/退出）时**不要**再发信号：那时接收方的 C++ 对象
            # 可能已经析构，`emit` 会踩空。结果本身就是不要了。
            if self.isInterruptionRequested():
                return
            self.finished_signal.emit(self._type_id, buy, sell)
        except Exception as e:
            if self.isInterruptionRequested():
                return
            self.error_signal.emit(self._type_id, str(e))
        finally:
            if loop is not None:
                loop.close()

    async def _fetch(self):
        from services.client import APIClient

        # 两次请求之间留检查点：`requestInterruption()` 之后本线程会尽快收尾，
        # 让 `QueryDetailBridge.shutdown()` 的 `wait()` 能在毫秒级成功 ——
        # 没有检查点就只能等整个 HTTP 超时（30s），而那期间进程退出会崩。
        if self.isInterruptionRequested():
            return [], []

        async with APIClient(timeout=30) as client:
            url = f"{ESI_BASE_URL}/markets/{self._region_id}/orders/"
            buy_data = await client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=buy") or []
            if self.isInterruptionRequested():
                return [], []
            sell_data = await client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=sell") or []

        if self.isInterruptionRequested():
            return [], []
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

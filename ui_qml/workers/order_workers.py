"""订单取数的共享部分：名称缓存 + ESI 线程。

原先是 `ui_pyside6/views/query/query_order_popup.py` 里订单弹窗的配套部分（6.0 拆到这里）。
订单弹窗已删除，本模块仍服务物品查询页的「订单列表」详情面板
（`QueryDetailBridge`）。`order_cache` 的**唯一写入方**是
`QueryDetailBridge._on_orders_fetched`。
"""

import asyncio

from PySide6.QtCore import QThread, Signal

from core.logger import log

ESI_BASE_URL = "https://esi.evetech.net/latest"

#: location_id → 显示名。**只放解析成功的条目**：查不到就不写，下次开窗还能重试。
#: 见 `OrderFetchWorker._resolve_names` 里对「失败也写缓存」为什么是错的说明。
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

    # ── 站名解析 ─────────────────────────────────────────────

    async def _resolve_names(self, location_ids: list[int]) -> None:
        """location_id → 站名：**先查本地 SDE，只有本地没有的才打 ESI**。

        本地 `reference.db.station` 表存着全部 5154 个 NPC 空间站（由 SDE
        `staStations.yaml` 导入），而市场订单的 location 绝大多数就是这些。
        本地查完通常不剩需要联网的，于是「离线也能显示站名」，
        也不再有「网络抖一次就永远显示编号」的问题。

        剩下的只有玩家建筑（structure）：`station` 表里没有，只能问
        `/universe/names/`。
        """
        from services.npc_seller import resolve_stations_by_ids

        need = [lid for lid in location_ids if lid and lid not in _station_name_cache]
        if not need:
            return

        local = resolve_stations_by_ids(set(need))
        for lid in need:
            name = (local.get(lid) or ("", ""))[0]
            if name:
                _station_name_cache[lid] = name

        missing = [lid for lid in need if lid not in _station_name_cache]
        if missing and not self.isInterruptionRequested():
            await self._resolve_names_remote(missing)

    async def _resolve_names_remote(self, ids: list[int]) -> None:
        """ESI `/universe/names/` 兜底（实际只会走到玩家建筑）。

        两条要点，都是踩过的坑：

        1. **整批会因一个坏 ID 全塌**：ESI 对无权访问的建筑返回 400，
           而这一批是一个 POST —— `raise_for_status()` 抛错 → `post()` 返回 `None`
           → 同批里那些**本来查得到的** station id 一起没了。所以整批没解出来时
           退化成逐个重试。
        2. **失败绝不写缓存**：写 `str(lid)` 进去等于把「解析失败」记成解析结果，
           而 `_resolve_names` 开头的 `lid not in _station_name_cache` 过滤之后
           永远跳过它 —— 实测表现就是站名列**永远**是编号，重启前好不了。
        """
        from services.client import APIClient

        url = f"{ESI_BASE_URL}/universe/names/"
        async with APIClient(timeout=30) as client:
            for start in range(0, len(ids), 1000):
                if self.isInterruptionRequested():
                    return
                chunk = ids[start : start + 1000]
                try:
                    data = await client.post(url, json=chunk)
                except Exception:  # 外部 HTTP：任何异常都不该让整次订单取数失败
                    log.exception("ESI /universe/names/ 批量取名失败，转逐个重试")
                    data = None
                if isinstance(data, list):
                    self._absorb(data)
                if any(lid not in _station_name_cache for lid in chunk):
                    await self._resolve_names_one_by_one(client, chunk, url)

    async def _resolve_names_one_by_one(self, client, ids: list[int], url: str) -> None:
        for lid in ids:
            if lid in _station_name_cache:
                continue
            if self.isInterruptionRequested():
                return
            try:
                data = await client.post(url, json=[lid])
            except Exception:  # 同上：外部 HTTP
                log.exception("ESI /universe/names/ 单个取名失败 location_id=%s", lid)
                data = None
            if isinstance(data, list) and data:
                self._absorb(data)
            if lid not in _station_name_cache:
                log.warning("空间站名解析失败，下次开窗会重试 location_id=%s", lid)

    @staticmethod
    def _absorb(payload: list) -> None:
        for item in payload:
            name = str(item.get("name") or "")
            if name:
                _station_name_cache[int(item["id"])] = name

"""订单取数的共享部分：名称缓存 + ESI 线程。

原先是 Widgets 版订单弹窗的配套部分，QML 迁移时拆到这里。
订单弹窗已删除，本模块仍服务物品查询页的「订单列表」详情面板
（`QueryDetailBridge`）。`order_cache` 的**唯一写入方**是
`QueryDetailBridge._on_orders_fetched`。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread, Signal

from core.logger import log

if TYPE_CHECKING:
    from services.client import APIClient

ESI_BASE_URL = "https://esi.evetech.net/latest"

#: location_id → 显示名。**只放解析成功的条目**：查不到就不写，下次开窗还能重试。
#: 见 `OrderFetchWorker._resolve_names` 里对「失败也写缓存」为什么是错的说明。
_station_name_cache: dict[int, str] = {}

#: 详情面板「订单列表」买卖两侧**各展示多少条最优挂单**（用户要求：从 5 提到 10）。
#: 纯展示上限，与接口/库里的条数没有耦合 —— 取数仍是该 type 的全部在售订单
#: （实测三钛合金一次返回 75/76 条），只是排序后只把前 N 条交给表格。
_ORDER_BOOK_ROWS = 10

#: 等待常驻循环返回结果的轮询间隔（秒）。**不能**用无超时的 `future.result()`：
#: 页面销毁时 `QueryDetailBridge.shutdown()` 会 `requestInterruption()` + `wait()`，
#: 这条线程必须能自己收尾。
_POLL_S = 0.1

# 全局订单缓存 (key: type_id -> (buy_orders, sell_orders, fetch_time))
order_cache: dict[int, tuple] = {}


# ════════════════════════════════════════════════════════════
#  常驻事件循环 + 共享 APIClient（把 TCP+TLS 握手从每次摊到一次）
# ════════════════════════════════════════════════════════════
#
# 为什么需要它：aiohttp 的 `ClientSession` **绑事件循环**，而原先 `run()` 每次
# `new_event_loop()` → 新建 session → **每次取数都重付一次 TCP+TLS**（实测冷单 GET
# 中位 767.8ms，占一次「买+卖」取数的大部分）。把 session 活在一个**不随取数结束
# 而关闭**的循环里，握手就只付一次：稳态从 ~790ms 降到 ~180ms。
#
# 线程是 **daemon**：进程退出时随进程一起消失，**不加**应用退出钩子（实测退出码 0、
# 无 aiohttp「Unclosed client session」噪音、无卡顿）。

_LOOP_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_SHARED_CLIENT: APIClient | None = None


def _shared_loop() -> asyncio.AbstractEventLoop:
    """常驻事件循环（懒建，daemon 线程里 `run_forever()`）。"""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            loop = asyncio.new_event_loop()
            running = threading.Event()
            threading.Thread(
                target=_run_loop_forever, args=(loop, running), daemon=True, name="orders-esi-loop"
            ).start()
            # 等循环真的跑起来再交出去：`call_soon_threadsafe` 在未运行的循环上虽然会
            # 排队，但等一下就绪能让「提交 → 立刻有结果」的路径没有边角情况。
            running.wait(timeout=5.0)
            _LOOP = loop
        return _LOOP


def _run_loop_forever(loop: asyncio.AbstractEventLoop, running: threading.Event) -> None:
    asyncio.set_event_loop(loop)
    loop.call_soon(running.set)
    loop.run_forever()


async def _shared_client() -> APIClient:
    """**只在常驻循环里调用**：懒建并进入共享 `APIClient`（session 保持打开）。"""
    global _SHARED_CLIENT
    from services.client import APIClient

    client = _SHARED_CLIENT
    if client is None or client.session is None or client.session.closed:
        client = APIClient(timeout=30)
        await client.__aenter__()
        _SHARED_CLIENT = client
    return client


class OrderFetchWorker(QThread):
    """后台获取 ESI 订单数据"""

    finished_signal = Signal(int, list, list)  # type_id, buy_orders, sell_orders
    error_signal = Signal(int, str)  # type_id, error

    def __init__(self, type_id: int, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._region_id = region_id

    def run(self):
        """把取数交给常驻循环（共享 session），**边等边轮询中断**。"""
        try:
            loop = _shared_loop()
            future = asyncio.run_coroutine_threadsafe(self._fetch_shared(), loop)
            outcome = self._await_interruptible(future)
            # 被请求中断（页面销毁/退出）时**不要**再发信号：那时接收方的 C++ 对象
            # 可能已经析构，`emit` 会踩空。结果本身就是不要了。
            if outcome is None or self.isInterruptionRequested():
                return
            buy, sell = outcome
            self.finished_signal.emit(self._type_id, buy, sell)
        except Exception as e:
            if self.isInterruptionRequested():
                return
            self.error_signal.emit(self._type_id, str(e))

    def _await_interruptible(
        self, future: concurrent.futures.Future[tuple[list[Any], list[Any]]]
    ) -> tuple[list[Any], list[Any]] | None:
        """轮询等结果；期间 `requestInterruption()` 就取消并返回 None。

        **不能**写成无超时的 `future.result()`：`QueryDetailBridge.shutdown()` 会
        `requestInterruption()` + `wait()`，页面销毁时这条线程必须能自己收尾。
        """
        while True:
            try:
                return future.result(timeout=_POLL_S)
            except concurrent.futures.TimeoutError:
                if self.isInterruptionRequested():
                    future.cancel()
                    return None

    async def _fetch_shared(self) -> tuple[list, list]:
        """常驻循环里跑：拿共享 client（懒建）→ 取数。session 不随本次取数关闭。"""
        return await self._fetch(await _shared_client())

    async def _fetch(self, client: APIClient | None = None) -> tuple[list, list]:
        """取买单 / 卖单。

        `client` 由常驻循环注入（共享 session → TCP+TLS 只付一次）；**不传**时自己建一个
        临时的（测试直调 `_fetch()` 的路径与改动前一致：用完即关）。
        """
        if client is not None:
            return await self._fetch_orders(client)
        from services.client import APIClient as _Client

        async with _Client(timeout=30) as owned:
            return await self._fetch_orders(owned)

    async def _fetch_orders(self, client: APIClient) -> tuple[list, list]:
        if self.isInterruptionRequested():
            return [], []

        url = f"{ESI_BASE_URL}/markets/{self._region_id}/orders/"
        # 买 / 卖**并发**取：两个 order_type 互不依赖（各自一次 GET）。
        # 串行 vs 并发在**共享 session**（本模块的常驻循环路径）下实测，每次都取「买+卖」：
        #   串行：第 1 次 905~1197ms，稳态(第 2..4 次) 440~488ms
        #   并发：第 1 次 492~662ms，稳态(第 2..4 次) **166~221ms**
        # 并发稳态仍快约 2.3×（第一条连接握手之后两条连接都在池里），所以保留并发。
        # ⚠️ 这跟「每次新建 session」的旧条件不同：那时并发要新开连接、TLS 另算，收益很小。
        buy_data, sell_data = await asyncio.gather(
            client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=buy"),
            client.fetch_raw(f"{url}?type_id={self._type_id}&order_type=sell"),
        )

        if self.isInterruptionRequested():
            return [], []
        buy_orders = sorted(buy_data or [], key=lambda o: o["price"], reverse=True)[:_ORDER_BOOK_ROWS]
        sell_orders = sorted(sell_data or [], key=lambda o: o["price"])[:_ORDER_BOOK_ROWS]

        all_loc_ids = set()
        for o in buy_orders + sell_orders:
            all_loc_ids.add(o["location_id"])

        await self._resolve_names(list(all_loc_ids), client)
        return buy_orders, sell_orders

    # ── 站名解析 ─────────────────────────────────────────────

    async def _resolve_names(self, location_ids: list[int], client: APIClient | None = None) -> None:
        """location_id → 站名：**先查本地 SDE，只有本地没有的才打 ESI**。

        本地 `reference.db.station` 表存着全部 5154 个 NPC 空间站（由 SDE
        `staStations.yaml` 导入），而市场订单的 location 绝大多数就是这些。
        本地查完通常不剩需要联网的，于是「离线也能显示站名」，
        也不再有「网络抖一次就永远显示编号」的问题。

        剩下的只有玩家建筑（structure）：`station` 表里没有，只能问
        `/universe/names/`。`client` 传进来就用它（共享 session，不再开第二条连接）；
        不传就临时建一个（测试直调路径）。
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
        if not missing or self.isInterruptionRequested():
            return
        if client is not None:
            await self._resolve_names_remote(client, missing)
            return
        from services.client import APIClient as _Client

        async with _Client(timeout=30) as owned:
            await self._resolve_names_remote(owned, missing)

    async def _resolve_names_remote(self, client: APIClient, ids: list[int]) -> None:
        """ESI `/universe/names/` 兜底（实际只会走到玩家建筑）。

        `client` 由调用方给（共享 session，见 `_resolve_names`）—— 原先这里**又**新建一个
        `APIClient`，等于为极少数玩家建筑再付一次 TCP+TLS。

        两条要点，都是踩过的坑：

        1. **整批会因一个坏 ID 全塌**：ESI 对无权访问的建筑返回 400，
           而这一批是一个 POST —— `raise_for_status()` 抛错 → `post()` 返回 `None`
           → 同批里那些**本来查得到的** station id 一起没了。所以整批没解出来时
           退化成逐个重试。
        2. **失败绝不写缓存**：写 `str(lid)` 进去等于把「解析失败」记成解析结果，
           而 `_resolve_names` 开头的 `lid not in _station_name_cache` 过滤之后
           永远跳过它 —— 实测表现就是站名列**永远**是编号，重启前好不了。
        """
        url = f"{ESI_BASE_URL}/universe/names/"
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

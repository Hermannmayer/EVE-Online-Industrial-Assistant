"""`ui_qml/workers/order_workers.py` 的站名解析口径 + 共享 session 编排测试。

守的是**三条**曾经出过问题的规则：

1. NPC 空间站走本地 SDE，不该白跑一趟 ESI；
2. **解析失败绝不写缓存** —— 写进去等于把「没解析出来」记成解析结果，
   而解析入口靠「缓存里有没有」判断要不要重试，于是该 location 会永久显示编号；
3. 连续两次取数**复用同一个 `ClientSession`** —— 每次新建就等于每次重付 TCP+TLS
   （实测冷单 GET 中位 767.8ms，而稳态共享 session 只要 ~180ms）。
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from ui_qml.workers import order_workers
from ui_qml.workers.order_workers import OrderFetchWorker

pytestmark = pytest.mark.ui

#: 一个真实的 NPC 空间站（Jita 4-4）与一个 station 表里没有的玩家建筑
_NPC_STATION = 60003760
_STRUCTURE = 1044752365771


@pytest.fixture(autouse=True)
def _clean_cache():
    """缓存是模块级全局，用例之间必须隔离，否则先跑的用例会污染后面的判断。"""
    order_workers._station_name_cache.clear()
    yield
    order_workers._station_name_cache.clear()


def _worker() -> OrderFetchWorker:
    return OrderFetchWorker(34, 10000002)


def test_local_sde_hit_is_cached_without_touching_esi(qapp, monkeypatch):
    """本地查得到就写缓存，且**不**该再去打 ESI。"""
    monkeypatch.setattr(
        "services.npc_seller.resolve_stations_by_ids",
        lambda ids: {_NPC_STATION: ("Jita IV - Moon 4 - Caldari Navy Assembly Plant", "Jita")},
    )
    called: list[list[int]] = []

    async def _spy(self, client, ids):  # pragma: no cover - 不该被调到
        called.append(ids)

    monkeypatch.setattr(OrderFetchWorker, "_resolve_names_remote", _spy)

    asyncio.run(_worker()._resolve_names([_NPC_STATION]))

    assert order_workers._station_name_cache[_NPC_STATION] == "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
    assert called == [], "本地能解析的 location 不该走网络"


def test_failed_resolution_is_not_cached(qapp, monkeypatch):
    """回归：解析失败（本地没有 + ESI 也没解出来）**不能**把 ID 当名字写进缓存。

    原先失败时 `setdefault(lid, str(lid))`，而解析入口的 `need` 过滤会把已缓存的
    location 整个跳过 —— 一次失败就永久显示编号，重启前好不了。
    """
    monkeypatch.setattr("services.npc_seller.resolve_stations_by_ids", lambda ids: {})

    async def _no_remote(self, client, ids):
        return None  # 模拟 ESI 没给出任何结果

    monkeypatch.setattr(OrderFetchWorker, "_resolve_names_remote", _no_remote)

    asyncio.run(_worker()._resolve_names([_STRUCTURE]))

    assert _STRUCTURE not in order_workers._station_name_cache, "失败的 location 必须留待下次重试"


def test_already_cached_location_is_skipped(qapp, monkeypatch):
    """已缓存的不重复解析（第二次开窗不该再查一遍）。"""
    order_workers._station_name_cache[_NPC_STATION] = "Jita IV - Moon 4"
    calls: list[set[int]] = []

    monkeypatch.setattr(
        "services.npc_seller.resolve_stations_by_ids",
        lambda ids: calls.append(set(ids)) or {},
    )

    asyncio.run(_worker()._resolve_names([_NPC_STATION]))

    assert calls == [], "缓存命中就不该再查"


def test_order_book_takes_ten_best_per_side(qapp, monkeypatch):
    """买卖两侧各取**最优 10 条**（买降序 / 卖升序）—— 回归用户报的「各 5 个不太够」。

    截断常量原先硬编码 `[:5]`；现在走 `_ORDER_BOOK_ROWS`。并发取数（`asyncio.gather`）
    只是把两次 GET 同时发出去，不改结果集 —— 这里桩掉网络，只验截断与排序口径。
    """
    buys = [{"order_id": i, "price": float(i), "volume_remain": 1, "location_id": _NPC_STATION} for i in range(1, 16)]
    sells = [{**o, "order_id": 100 + int(o["order_id"])} for o in buys]

    async def _fake_fetch_raw(self, url):  # 替身：签名随被测调用处
        return buys if "order_type=buy" in url else sells

    monkeypatch.setattr("services.client.APIClient.fetch_raw", _fake_fetch_raw)

    async def _no_remote(self, client, ids):  # pragma: no cover - 本地 SDE 能解析，不该走网络
        return None

    monkeypatch.setattr(OrderFetchWorker, "_resolve_names_remote", _no_remote)

    got_buy, got_sell = asyncio.run(_worker()._fetch())

    assert len(got_buy) == len(got_sell) == order_workers._ORDER_BOOK_ROWS == 10
    assert [o["order_id"] for o in got_buy] == list(range(15, 5, -1)), "买单：价格最高的 10 条、降序"
    assert [o["order_id"] for o in got_sell] == list(range(101, 111)), "卖单：价格最低的 10 条、升序"


def test_two_fetches_reuse_one_session(qapp, monkeypatch):
    """连续两次取数复用**同一个** `ClientSession` —— 跨线程异步编排的端到端。

    为什么守这条：`OrderFetchWorker.run()` 现在把协程交给常驻循环里的共享 `APIClient`。
    若每次取数都新建 session，TCP+TLS 就白付了（实测冷单 GET 中位 767.8ms；共享 session
    稳态 228ms，见 `_shared_client`）。这里数 `aiohttp.ClientSession` 建了几次：
    两次取数只能 1 次，且第二次用的仍是它。网络全部桩掉，不打 ESI。
    """
    sessions: list[object] = []
    real_init = aiohttp.ClientSession.__init__

    def _counting_init(self, *args: object, **kwargs: object) -> None:
        sessions.append(self)
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(aiohttp.ClientSession, "__init__", _counting_init)

    async def _fake_fetch_raw(self, url):  # 替身：签名随被测调用处
        return [{"order_id": 1, "price": 1.0, "volume_remain": 1, "location_id": _NPC_STATION}]

    monkeypatch.setattr("services.client.APIClient.fetch_raw", _fake_fetch_raw)
    monkeypatch.setattr(order_workers, "_SHARED_CLIENT", None)

    emitted: list[tuple[int, int, int]] = []
    for _ in range(2):
        worker = _worker()
        # 直接调 run()（不 start()）：测的就是 run() 里「提交到常驻循环 + 等结果」那段
        worker.finished_signal.connect(lambda tid, buy, sell: emitted.append((tid, len(buy), len(sell))))
        worker.run()

    try:
        assert len(sessions) == 1, f"两次取数只该建 1 个 ClientSession，实际 {len(sessions)}"
        assert order_workers._SHARED_CLIENT is not None
        assert order_workers._SHARED_CLIENT.session is sessions[0], "第二次取数该用同一个 session"
        assert emitted == [(34, 1, 1), (34, 1, 1)], "两次取数都要拿到结果"
    finally:
        # 收尾：生产路径里共享 session 活到进程结束；测试里把它关掉，免得留「未关闭」噪音
        client = order_workers._SHARED_CLIENT
        if client is not None:
            asyncio.run_coroutine_threadsafe(client.__aexit__(None, None, None), order_workers._shared_loop()).result(5)

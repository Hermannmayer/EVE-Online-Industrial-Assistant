"""`ui_qml/workers/order_workers.py` 的站名解析口径测试。

守的是**两条**曾经出过问题的规则（用户实测「空间站列全是数字」）：

1. NPC 空间站走本地 SDE，不该白跑一趟 ESI；
2. **解析失败绝不写缓存** —— 写进去等于把「没解析出来」记成解析结果，
   而解析入口靠「缓存里有没有」判断要不要重试，于是该 location 会永久显示编号。
"""

from __future__ import annotations

import asyncio

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

    async def _spy(self, ids):  # pragma: no cover - 不该被调到
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

    async def _no_remote(self, ids):
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

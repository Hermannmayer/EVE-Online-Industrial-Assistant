"""`ui_qml/workers/esi_wallet_worker.py` 的钱包 / 挂单聚合口径。

守的是三条**会静默算错钱**的规则：

1. 钱包合计**缺角色就不写**（`wallet_total=None`）—— 少算一个角色的余额会把总资产写小，
   比「这轮不更新」更糟；
2. 单角色失败**不拖垮其余角色**：成功的照常落库，失败的只进 `errors` 让 UI 报出来；
3. `groups` 含每个成功角色的**两个归属组**（个人单 / 军团单），**空组也要** ——
   桥按组整体替换，少了空组就删不掉已成交的幽灵行。

`ui` 标记：被测对象是 QThread 子类（本仓「构造 worker 的用例一律标 ui」的惯例，
见 `tests/test_order_workers.py`）。
"""

from __future__ import annotations

import asyncio

import pytest

from ui_qml.workers import esi_wallet_worker as eww
from ui_qml.workers.esi_skill_worker import EsiAuthRevoked

pytestmark = pytest.mark.ui

_CHAR_IDS = {"甲": 111, "乙": 222}
_CHARS = [
    {"character_id": 111, "character_name": "甲"},
    {"character_id": 222, "character_name": "乙"},
]
_WALLET = {111: 1000.0, 222: 250.0}
#: 甲有一笔卖单；乙当前没有挂单（**空集也要声明已覆盖** —— 否则旧行删不掉）
_ORDERS = {
    111: [
        {
            "order_id": 1,
            "is_buy_order": False,
            "price": 5.0,
            "volume_total": 10,
            "volume_remain": 4,
            "location_id": 60003760,
            "type_id": 34,
            "issued": "2026-09-20T00:00:00Z",
            "duration": 90,
            "is_corporation": False,
        }
    ],
    222: [],
}


def _run_import(monkeypatch, obtain):
    """跑一次 `_import()`（不碰网络、不起线程）。"""
    worker = eww.EsiWalletOrdersWorker()
    monkeypatch.setattr(eww, "list_token_rows", lambda: [dict(r) for r in _CHARS])
    monkeypatch.setattr(eww.EsiWalletOrdersWorker, "isInterruptionRequested", lambda self: False)
    monkeypatch.setattr(eww.EsiWalletOrdersWorker, "_obtain_token", obtain)

    async def fake_pull(self, client, access, char_id):
        return _WALLET[int(char_id)], [dict(o) for o in _ORDERS[int(char_id)]]

    monkeypatch.setattr(eww.EsiWalletOrdersWorker, "_pull_one", fake_pull)

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("services.client.APIClient", lambda **kwargs: _FakeClient())
    return asyncio.run(worker._import())


def test_all_characters_succeed_emits_full_payload(qapp, monkeypatch):
    """全部角色成功 → 钱包是合计、每个角色的两个归属组都声明已覆盖。"""

    async def obtain(self, client, character_name=None, *, allow_browser=True):
        assert allow_browser is False, "批量同步不该弹浏览器授权（一个角色掉线别拖十分钟）"
        return "tok", _CHAR_IDS[character_name], character_name

    payload = _run_import(monkeypatch, obtain)

    assert payload["chars"] == 2
    assert payload["wallet_total"] == 1250.0
    assert payload["errors"] == []
    assert sorted(payload["groups"]) == [[111, 0], [111, 1], [222, 0], [222, 1]]
    # 乙没有挂单，但它的组必须出现 —— 桥靠这个删掉它已成交的旧行
    order = payload["orders"][0]
    assert order["order_id"] == 1
    assert order["char_id"] == 111
    # ESI 给的是 is_buy_order（真 bool），不显式映射的话所有挂单都会变成卖单
    assert order["is_buy"] == 0
    assert order["is_corp"] == 0


def test_one_character_failing_skips_wallet_but_keeps_orders(qapp, monkeypatch):
    """单角色授权失效：其余角色照常落库，**钱包合计整块跳过**并报出是谁失败。"""

    async def obtain(self, client, character_name=None, *, allow_browser=True):
        if character_name == "乙":
            raise EsiAuthRevoked("授权已失效，请重新授权")
        return "tok", _CHAR_IDS[character_name], character_name

    payload = _run_import(monkeypatch, obtain)

    assert payload["chars"] == 1
    assert payload["wallet_total"] is None, "缺一个角色的合计会把余额写小，必须整块跳过"
    assert [o["order_id"] for o in payload["orders"]] == [1], "成功角色的挂单仍要落库"
    assert payload["groups"] == [[111, 0], [111, 1]], "失败角色的组不能声明已覆盖"
    assert len(payload["errors"]) == 1 and "乙" in payload["errors"][0]

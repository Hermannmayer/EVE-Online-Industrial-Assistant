"""`getprices.fetch_and_save_histories` —— 市场历史并入「更新价格」流程。

用户要求：可制造物品窗口的「日订单量 / 日成交量」两列，数据必须统一走现有的
「更新价格」流程（`main`），不为页面单开一条 ESI 拉取。这里盯四个会坏的东西：

1. **候选集合**：产物 ∪ 被当材料的 type ∪ PLEX —— 材料自己没有产物行，漏了两列读数全空；
2. **增量 TTL**（性能红线）：TTL 内的 type **一条请求都不发** —— 没有它每轮 5554 次请求；
3. **失败隔离**：单条 404（`None`）/ 超时（异常）被跳过，同批其余仍写入；
4. **180 天裁剪**：写库前 `DELETE ... date < now-180d`（不裁剪 market.db 会多出约 200 万行）。

请求（`price_history.fetch_history`）、客户端（`APIClient`）、数据库（aiosqlite）、
蓝图库（容器 `db.connect("bp")`）全部替换成替身，**不发真请求**；
`tests/conftest.py` 的断网护栏照旧生效。
"""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.importers import getprices

_REGION = 10000002  # Jita / The Forge
_MANUFACTURING = [1, 2, 3]
_REACTION = [4]
_MATERIALS = [5, 6]  # 只当材料、自己不是产物的 type
_PLEX = getprices.PLEX_TYPE_ID
_CANDIDATES = _MANUFACTURING + _REACTION + _MATERIALS + [_PLEX]
_GOOD_ENTRY = [{"date": "2026-09-30", "average": 5.5, "highest": 6.0, "lowest": 5.0, "volume": 120, "order_count": 8}]


def _fake_bp_conn(material_ids):
    """替身 bp 连接：`_material_type_ids` 的 DISTINCT 查询返回这些材料 type。"""
    cursor = MagicMock()
    cursor.fetchall = MagicMock(return_value=[(t,) for t in material_ids])
    conn = MagicMock()
    conn.execute = MagicMock(return_value=cursor)
    return conn


class _Harness:
    """替身装配：容器（候选 type_id）+ APIClient + fetch_history + aiosqlite connect。"""

    def __init__(self, fetched_rows=None, history=None):
        self.cm, self.db = _fake_db(fetched_rows)
        self.fetch_history = AsyncMock(side_effect=history)
        self.api = MagicMock()
        self.api.return_value.__aenter__ = AsyncMock(return_value=_fake_client())
        self.api.return_value.__aexit__ = AsyncMock(return_value=False)
        self.container = MagicMock()
        self.container.blueprint_repo.get_all_product_ids = MagicMock(
            side_effect=lambda activity: list(_MANUFACTURING if activity == "manufacturing" else _REACTION)
        )
        self.container.db.connect.return_value.__enter__.return_value = _fake_bp_conn(_MATERIALS)
        self._stack = ExitStack()

    def __enter__(self):
        self._stack.enter_context(patch("services.importers.getprices.aiosqlite.connect", return_value=self.cm))
        self._stack.enter_context(patch("services.importers.getprices.APIClient", self.api))
        self._stack.enter_context(patch("services.importers.getprices.fetch_history", self.fetch_history))
        self._stack.enter_context(patch("services.importers.getprices.get_container", return_value=self.container))
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def executes_matching(self, needle: str) -> list:
        return [c for c in self.db.execute.await_args_list if c.args and needle in c.args[0]]


def _fake_db(fetched_rows):
    """替身 aiosqlite 连接：记录 execute/executemany，SELECT 返回 `fetched_rows`。"""
    db = MagicMock()
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=list(fetched_rows or []))
    cursor.close = AsyncMock()
    db.execute = AsyncMock(return_value=cursor)
    db.executemany = AsyncMock()
    db.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, db


def _fake_client():
    """替身 APIClient：`limiter.acquire()` / `async with semaphore` / `.session` 都齐。"""
    client = MagicMock()
    client.limiter.acquire = AsyncMock()
    client.semaphore = MagicMock()
    client.semaphore.__aenter__ = AsyncMock(return_value=None)
    client.semaphore.__aexit__ = AsyncMock(return_value=False)
    client.session = MagicMock()
    return client


@pytest.mark.asyncio
async def test_fresh_records_skip_requests():
    """① 增量过滤 + 区域口径 + 候选集合：
    TTL 内的 type 一条请求都不发；**勾了几个中心就查几个中心**（不再写死 Jita ——
    贸易页要按当前选的起点/终点读「两端日成交量」，用户口径是「同步哪些市场就拉哪些」）。

    第三段守**候选集合**：发起请求的 type 必须是「产物 ∪ 材料 ∪ PLEX」——
    材料（`_MATERIALS`）自己没有 `blueprint_products` 行，PLEX 两者都不是。
    """
    now = datetime.now(UTC).isoformat()
    rows = [(tid, now) for tid in _CANDIDATES]

    with _Harness(fetched_rows=rows) as h:
        written = await getprices.fetch_and_save_histories(getprices.TRADE_REGIONS)

    assert written == 0
    h.fetch_history.assert_not_awaited()
    h.api.assert_not_called()  # TTL 全命中时连 APIClient 都不建
    selects = h.executes_matching("SELECT type_id, MAX(fetched_at)")
    assert len(selects) == len(getprices.TRADE_REGIONS), "每个区域一条 GROUP BY，不是每个 type 一条"
    assert {c.args[1][0] for c in selects} == {rid for _, rid in getprices.TRADE_REGIONS}

    # 只勾 Amarr：照样查 Amarr（原来这里整步跳过）
    with _Harness(fetched_rows=rows) as h2:
        assert await getprices.fetch_and_save_histories([("Amarr", 10000043)]) == 0
    selects2 = h2.executes_matching("SELECT type_id, MAX(fetched_at)")
    assert [c.args[1] for c in selects2] == [(10000043,)]

    # TTL 全未命中（本地无记录）→ 逐条请求，请求到的 type 就是候选集合本身
    with _Harness(history=lambda tid, region_id, session=None: None) as h3:
        assert await getprices.fetch_and_save_histories([("Jita", _REGION)]) == 0
    assert {c.args[0] for c in h3.fetch_history.await_args_list} == set(_CANDIDATES)


@pytest.mark.asyncio
async def test_single_failure_is_isolated():
    """② 单条 404 / 超时被跳过，同批其余仍写入，进度照常走到 100%。

    传 5 个中心：请求量是 `7 个候选 type × 5 个区域 = 35 条`（每个同步的中心都要历史）。
    """

    async def _history(tid, region_id, session=None):
        if tid == 1:
            return _GOOD_ENTRY
        if tid == 2:
            return None  # 404
        raise TimeoutError("ESI 超时")

    with _Harness(history=_history) as h:
        progress: list[tuple[int, str]] = []
        written = await getprices.fetch_and_save_histories(
            getprices.TRADE_REGIONS, progress_cb=lambda pct, msg: progress.append((pct, msg))
        )

    expected_requests = len(_CANDIDATES) * len(getprices.TRADE_REGIONS)
    assert written == len(getprices.TRADE_REGIONS), "好的那一条在 5 个中心各写一行"
    assert h.fetch_history.await_count == expected_requests, "单条异常不得中断整批"
    assert {c.args[1] for c in h.fetch_history.await_args_list} == {rid for _, rid in getprices.TRADE_REGIONS}
    # 写库按区域分批（`executemany` 一次一个区域），所以要把各批摊平再看
    inserted = [row for call in h.db.executemany.await_args_list for row in call.args[1]]
    assert len(inserted) == len(getprices.TRADE_REGIONS)
    assert {row[1] for row in inserted} == {rid for _, rid in getprices.TRADE_REGIONS}
    assert inserted[0][:8] == (1, _REGION, "2026-09-30", 5.5, 6.0, 5.0, 120, 8)
    assert inserted[0][8], "fetched_at 必须写入 —— 下一轮的 TTL 判定靠它"
    assert progress == [(100, f"拉取市场历史 {expected_requests}/{expected_requests}")]


@pytest.mark.asyncio
async def test_keeps_only_recent_180_days():
    """③ 写库前按 `date < now-180d` 裁剪，插入用 INSERT OR REPLACE。"""
    history = AsyncMock(side_effect=lambda tid, region_id, session=None: _GOOD_ENTRY if tid == 1 else None)

    with _Harness(history=history) as h:
        await getprices.fetch_and_save_histories([("Jita", _REGION)])

    deletes = h.executes_matching("DELETE FROM price_history")
    assert len(deletes) == 1
    expected_cutoff = (datetime.now(UTC) - timedelta(days=getprices.HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    assert deletes[0].args[1] == (1, _REGION, expected_cutoff)
    assert "INSERT OR REPLACE INTO price_history" in h.db.executemany.await_args.args[0]

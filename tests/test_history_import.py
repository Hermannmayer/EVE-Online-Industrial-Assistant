"""`getprices.fetch_and_save_histories` —— 市场历史并入「更新价格」流程。

用户要求：可制造物品窗口的「日订单量 / 日成交量」两列，数据必须统一走现有的
「更新价格」流程（`main`），不为页面单开一条 ESI 拉取。这里盯五个会坏的东西：

1. **候选集合**：产物 ∪ 被当材料的 type —— 材料自己没有产物行，漏了两列读数全空；
   **PLEX 不在这条通道上**（BL-012）：它走官方的全域市场 region `PLEX_REGION_ID`
   （19000001），贸易中心的区块历史对它恒返回空（实测 `[]`）；
2. **增量 TTL**（性能红线）：TTL 内的 type **一条请求都不发** —— 没有它每轮 5554 次请求；
3. **失败隔离**：单条 404（`None`）/ 超时（异常）被跳过，同批其余仍写入；
4. **180 天裁剪**：写库前 `DELETE ... date < now-180d`（不裁剪 market.db 会多出约 200 万行）；
5. **候选前置过滤**（BL-013）：该区域「无挂单且无历史」的组合不发请求 ——
   实测贸易中心候选 27765 条里 7283 条（26%）注定返回空。

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

    def __init__(self, fetched_rows=None, history=None, active_by_region=None):
        self.cm, self.db = _fake_db(fetched_rows, active_by_region)
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


def _fake_db(fetched_rows, active_by_region=None):
    """替身 aiosqlite 连接：记录 execute/executemany，按 SQL 分流 SELECT 结果。

    - `SELECT ... FROM price_history` → `fetched_rows`（TTL 与「已有历史」判定用）；
    - `SELECT ... FROM market_prices` → `active_by_region[region_id]`，即「该区域有挂单」的 type
      （缺省 `{}` = **订单簿证据缺失**，生产代码此时退回「不过滤」，见 `_pending_history_tasks`）。
    """

    def _cursor_for(rows):
        cur = MagicMock()
        cur.fetchall = AsyncMock(return_value=list(rows))
        cur.close = AsyncMock()
        return cur

    async def _execute(sql, params=()):
        if "FROM market_prices" in sql:
            return _cursor_for([(t,) for t in (active_by_region or {}).get(int(params[0]), [])])
        return _cursor_for(fetched_rows or [])

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
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
    """① 增量过滤 + 区域口径 + 候选集合 + 候选前置过滤：
    TTL 内的 type 一条请求都不发；**勾了几个中心就查几个中心**（不再写死 Jita ——
    贸易页要按当前选的起点/终点读「两端日成交量」，用户口径是「同步哪些市场就拉哪些」）。

    第三段守**候选集合**：发起请求的 type 必须是「产物 ∪ 材料」——材料（`_MATERIALS`）
    自己没有 `blueprint_products` 行；**PLEX 不在这条通道上**（BL-012：贸易中心的历史
    对它恒返回空），它单独走全域 market region `PLEX_REGION_ID`。

    第四段守**候选前置过滤**（BL-013）：该区域「既无挂单、也无历史」的组合不发请求。
    """
    now = datetime.now(UTC).isoformat()
    rows = [(tid, now) for tid in _CANDIDATES]

    with _Harness(fetched_rows=rows) as h:
        written = await getprices.fetch_and_save_histories(getprices.TRADE_REGIONS)

    assert written == 0
    h.fetch_history.assert_not_awaited()
    h.api.assert_not_called()  # TTL 全命中时连 APIClient 都不建
    selects = h.executes_matching("SELECT type_id, MAX(fetched_at)")
    assert len(selects) == len(getprices.TRADE_REGIONS) + 1, (
        "每个区域一条 GROUP BY（+1 = PLEX 全域 region），不是每个 type 一条"
    )
    assert {c.args[1][0] for c in selects} == {rid for _, rid in getprices.TRADE_REGIONS} | {getprices.PLEX_REGION_ID}

    # 只勾 Amarr：照样查 Amarr（原来这里整步跳过），PLEX 全域 region 同样只看一条
    with _Harness(fetched_rows=rows) as h2:
        assert await getprices.fetch_and_save_histories([("Amarr", 10000043)]) == 0
    selects2 = h2.executes_matching("SELECT type_id, MAX(fetched_at)")
    assert [c.args[1] for c in selects2] == [(10000043,), (getprices.PLEX_REGION_ID,)]

    # TTL 全未命中（本地无记录）→ 逐条请求；请求的 (region, type) 就是候选集合本身，
    # 且 PLEX **只**出现在全域 region 上（BL-012 的最小回归）
    with _Harness(history=lambda tid, region_id, session=None: None) as h3:
        assert await getprices.fetch_and_save_histories([("Jita", _REGION)]) == 0
    assert {(c.args[1], c.args[0]) for c in h3.fetch_history.await_args_list} == {
        (_REGION, tid) for tid in set(_CANDIDATES) - {_PLEX}
    } | {(getprices.PLEX_REGION_ID, _PLEX)}

    # BL-013：Jita 只有 type 1 有挂单、只有 type 2 有（过期的）历史 → 只请求这两条；
    # 3~6 既无挂单也无历史，一条请求都不发。PLEX 全域 region 在 market_prices 里没有行
    # （订单侧本次不动），按「证据缺失 → 不过滤」照旧请求。
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with _Harness(
        fetched_rows=[(2, stale)], history=lambda tid, region_id, session=None: None, active_by_region={_REGION: [1]}
    ) as h4:
        await getprices.fetch_and_save_histories([("Jita", _REGION)])
    assert {(c.args[1], c.args[0]) for c in h4.fetch_history.await_args_list} == {
        (_REGION, 1),  # 有挂单
        (_REGION, 2),  # 已有历史（当前无挂单，序列不能丢）
        (getprices.PLEX_REGION_ID, _PLEX),
    }


@pytest.mark.asyncio
async def test_single_failure_is_isolated():
    """② 单条 404 / 超时被跳过，同批其余仍写入，进度照常走到 100%。

    传 5 个中心：请求量是 `6 个候选 type × 5 个区域 + 1 条 PLEX 全域 = 31 条`
    （每个同步的中心都要历史；PLEX 只走全域 region，见 BL-012）。
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

    expected_requests = (len(_CANDIDATES) - 1) * len(getprices.TRADE_REGIONS) + 1  # +1 = PLEX 全域任务
    assert written == len(getprices.TRADE_REGIONS), "好的那一条在 5 个中心各写一行"
    assert h.fetch_history.await_count == expected_requests, "单条异常不得中断整批"
    assert {c.args[1] for c in h.fetch_history.await_args_list} == {rid for _, rid in getprices.TRADE_REGIONS} | {
        getprices.PLEX_REGION_ID
    }
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


@pytest.mark.asyncio
async def test_global_price_snapshot_only_writes_anchor_types():
    """④ 全服统一价每日快照：**只写锚定集合**，`/markets/prices/` 里其它 type 一律不落库。

    这张表是 PLEX 锚的数据源（用户口径：PLEX 价格全服统一、没有本地市场划分）。
    当前锚定集合只有 PLEX 一个 —— **矿物不能加进来**：它们有权威的区域成交历史
    （一次能拉 398 天），而全服价只有当日一个点，混进来会被当退路数据源污染指数
    （实测：无条件覆盖时矿物的 398 天序列被换成 1 行当日价，MPI 整条变空）。
    """
    baseline = {t: {"buy_price": 10.0 + t, "adjusted_price": 1.0} for t in (44992, 34, 999999)}

    cm, db = _fake_db([])
    with ExitStack() as stack:
        stack.enter_context(patch("services.importers.getprices.aiosqlite.connect", return_value=cm))
        written = await getprices.save_global_price_snapshot(baseline, day="2026-10-05")

    rows = db.executemany.await_args.args[1]
    assert written == len(rows) == 1  # 只有 PLEX；矿物 34 与不存在的 999999 都不写
    assert [r[0] for r in rows] == [44992]
    assert rows[0][1] == "2026-10-05"
    assert rows[0][2] == pytest.approx(45002.0)  # average_price
    assert "INSERT OR REPLACE INTO global_price_daily" in db.executemany.await_args.args[0]
    assert any("CREATE TABLE IF NOT EXISTS global_price_daily" in c.args[0] for c in db.execute.await_args_list)


@pytest.mark.asyncio
async def test_global_price_snapshot_no_anchor_data_writes_nothing():
    """锚定 type 全不在基准价里（网络返回残缺）→ 不建表、不写行，也不抛异常。"""
    cm, db = _fake_db([])
    with ExitStack() as stack:
        stack.enter_context(patch("services.importers.getprices.aiosqlite.connect", return_value=cm))
        written = await getprices.save_global_price_snapshot({})

    assert written == 0
    db.executemany.assert_not_awaited()

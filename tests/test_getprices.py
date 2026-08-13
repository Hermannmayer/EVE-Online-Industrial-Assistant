"""测试 services/workers/getprices.py — 价格拉取流程

覆盖 5 个核心函数：
  - init_db: 数据库表结构创建
  - fetch_baseline_prices: /markets/prices/ 基准价格解析
  - discover_pages: 订单页数发现与缓存
  - fetch_order_pages: 多页订单并发拉取
  - fetch_orders: 完整订单聚合逻辑（最高买价/最低卖价/成交量求和）

全部 mock aiohttp 响应，不触发真实网络请求。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.workers.getprices import (
    _PAGE_CACHE,
    TRADE_REGIONS,
    discover_pages,
    fetch_baseline_only,
    fetch_baseline_prices,
    fetch_order_pages,
    fetch_orders,
    init_db,
)

# ════════════════════════════════════════════════════════════
#  Helper: 构建 mock aiohttp.ClientSession
# ════════════════════════════════════════════════════════════


def _mock_session(resp_get=None):
    """构造一个 __aenter__/__aexit__ 完备的 mock ClientSession。

    Parameters
    ----------
    resp_get : MagicMock | None
        若传入，直接作为 session.get 的返回值（上下文管理器）；
        若为 None 则新建一个默认的 MagicMock。
    """
    mock_cm = resp_get if resp_get is not None else MagicMock()
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_cm)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _mock_response(status=200, json_data=None, headers=None):
    """构造一个 mock aiohttp.ClientResponse。"""
    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    return resp


def _mock_client():
    """构造一个 mock APIClient（fetch_raw / get_headers / limiter）。

    getprices 现在统一走 services.client.APIClient。
    """
    client = MagicMock()
    client.fetch_raw = AsyncMock(return_value=[])
    client.get_headers = AsyncMock(return_value={"X-Pages": "1"})
    client.limiter = MagicMock()
    client.limiter.acquire = AsyncMock()
    return client


# ════════════════════════════════════════════════════════════
#  Test 1 — init_db
# ════════════════════════════════════════════════════════════


class TestInitDb:
    """init_db — 数据库表结构创建"""

    @pytest.mark.asyncio
    async def test_creates_tables_and_migrates(self):
        """验证 CREATE IF NOT EXISTS + ALTER 兜底迁移，commit 被调用，不再 DROP"""
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("services.workers.getprices.aiosqlite.connect", return_value=cm):
            await init_db()

        # CREATE market_prices + ALTER 补列 + CREATE volume_snapshots = 3 次
        assert db.execute.await_count == 3
        sqls = [c[0][0] for c in db.execute.await_args_list]

        assert any("CREATE TABLE IF NOT EXISTS market_prices" in s for s in sqls)
        assert any("ALTER TABLE market_prices ADD COLUMN adjusted_price" in s for s in sqls)
        assert any("CREATE TABLE IF NOT EXISTS market_volume_snapshots" in s for s in sqls)
        # 验证 volume_snapshots 表有复合主键
        assert any("PRIMARY KEY (type_id, region_id, date)" in s for s in sqls)
        # 不再 DROP TABLE（保留已有价格数据）
        assert not any(s.strip().upper().startswith("DROP") for s in sqls)

        db.commit.assert_awaited_once()


# ════════════════════════════════════════════════════════════
#  Test 2 — fetch_baseline_prices
# ════════════════════════════════════════════════════════════


class TestFetchBaselinePrices:
    """fetch_baseline_prices — /markets/prices/ 基准价格映射"""

    @pytest.mark.asyncio
    async def test_maps_average_and_adjusted_prices(self):
        """验证 average_price→buy_price, adjusted_price→sell_price 映射

        覆盖场景：正常值、None、缺失字段
        """
        fake_json = [
            {"type_id": 1001, "average_price": 4.5, "adjusted_price": 5.0},
            {"type_id": 1002, "average_price": None, "adjusted_price": 9.5},
        ]

        client = _mock_client()
        client.fetch_raw = AsyncMock(return_value=fake_json)

        with patch("services.workers.getprices.APIClient") as mock_api:
            mock_api.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_api.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await fetch_baseline_prices()

        assert len(result) == 2
        assert result[1001] == {
            "buy_price": 4.5,
            "sell_price": 5.0,
            "adjusted_price": 5.0,
            "buy_volume": 0,
            "sell_volume": 0,
        }
        assert result[1002] == {
            "buy_price": None,
            "sell_price": 9.5,
            "adjusted_price": 9.5,
            "buy_volume": 0,
            "sell_volume": 0,
        }

        # 验证请求发送至正确 URL
        client.fetch_raw.assert_awaited_once()
        url = client.fetch_raw.await_args.args[0]
        assert "/markets/prices/" in url

    @pytest.mark.asyncio
    async def test_failed_baseline_returns_empty(self):
        """拉取失败（None）→ 返回空 dict，不再抛异常（回归：无超时裸请求直接上抛）"""
        client = _mock_client()
        client.fetch_raw = AsyncMock(return_value=None)

        with patch("services.workers.getprices.APIClient") as mock_api:
            mock_api.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_api.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await fetch_baseline_prices()

        assert result == {}


# ════════════════════════════════════════════════════════════
#  Test 3 — discover_pages
# ════════════════════════════════════════════════════════════


class TestDiscoverPages:
    """discover_pages — 页数发现与缓存"""

    @pytest.mark.asyncio
    async def test_returns_page_counts_and_populates_cache(self):
        """验证 X-Pages 头被正确解析，_PAGE_CACHE 被填充"""
        _PAGE_CACHE.clear()

        client = _mock_client()
        client.get_headers = AsyncMock(return_value={"X-Pages": "3"})

        targets = [("Jita", 10000002)]
        result = await discover_pages(client, targets)

        assert result == {"10000002_sell": 3, "10000002_buy": 3}
        assert _PAGE_CACHE["10000002_sell"] == 3
        assert _PAGE_CACHE["10000002_buy"] == 3

        # get_headers 应被调用 2 次（sell + buy）
        assert client.get_headers.await_count == 2

    @pytest.mark.asyncio
    async def test_uses_cached_pages_skips_http(self):
        """缓存命中时跳过 HTTP 请求"""
        _PAGE_CACHE.clear()
        _PAGE_CACHE["10000002_sell"] = 1
        _PAGE_CACHE["10000002_buy"] = 2

        client = _mock_client()
        targets = [("Jita", 10000002)]

        result = await discover_pages(client, targets)

        assert result == {"10000002_sell": 1, "10000002_buy": 2}
        # 缓存命中，不应调用 get_headers
        client.get_headers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_200_response_returns_empty(self):
        """非 200 响应（get_headers=None）→ keys 为空且记日志"""
        _PAGE_CACHE.clear()

        client = _mock_client()
        client.get_headers = AsyncMock(return_value=None)

        targets = [("Jita", 10000002)]
        result = await discover_pages(client, targets)

        # get_headers None → 不进入写入分支，keys 中无该 key
        assert result == {}


# ════════════════════════════════════════════════════════════
#  Test 4 — fetch_order_pages
# ════════════════════════════════════════════════════════════


class TestFetchOrderPages:
    """fetch_order_pages — 多页订单并发拉取"""

    @pytest.mark.asyncio
    async def test_fetches_all_pages_and_concatenates(self):
        """所有页面被拉取并合并为单一列表"""
        page_size = 3
        page_data = [{"type_id": i, "price": float(i)} for i in range(page_size)]

        client = _mock_client()
        client.fetch_raw = AsyncMock(return_value=page_data)

        result = await fetch_order_pages(client, 10000002, "sell", 4)

        # 4 pages × 3 items each
        assert len(result) == 12
        assert result[0] == {"type_id": 0, "price": 0.0}
        assert result[-1] == {"type_id": 2, "price": 2.0}
        # fetch_raw 应被调用 4 次（每页一次）
        assert client.fetch_raw.await_count == 4
        # 验证所有请求 URL 包含正确的 region_id 和 order_type
        for call_args in client.fetch_raw.await_args_list:
            url = call_args.args[0]
            assert "10000002" in url
            assert "order_type=sell" in url

    @pytest.mark.asyncio
    async def test_returns_empty_when_total_pages_is_zero(self):
        """total_pages=0 时不发起 HTTP 请求，返回空列表"""
        client = _mock_client()

        result = await fetch_order_pages(client, 10000002, "buy", 0)

        assert result == []
        client.fetch_raw.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_page_returns_empty_and_continues(self):
        """单页失败（None）→ 该页为空不中断整体，且返回空页"""
        client = _mock_client()
        client.fetch_raw = AsyncMock(side_effect=[None, [{"type_id": 1}]])

        result = await fetch_order_pages(client, 10000002, "buy", 2)

        assert len(result) == 1  # 只含成功页数据
        assert result[0] == {"type_id": 1}


# ════════════════════════════════════════════════════════════
#  Test 5 — fetch_orders（完整聚合流程）
# ════════════════════════════════════════════════════════════


class TestFetchOrders:
    """fetch_orders — 订单聚合逻辑（最高买价/最低卖价/成交量）"""

    @pytest.mark.asyncio
    async def test_aggregates_buy_max_sell_min_and_fixes_inf(self):
        """验证聚合规则：
        - 同 type_id 多个买单 → 取最高价，成交量求和
        - 同 type_id 多个卖单 → 取最低价，成交量求和
        - 仅有买单无卖单 → sell_price 修复为 0.0
        """
        _PAGE_CACHE.clear()
        # ── 构造买／卖订单数据 ──
        # type 1001: 2 个买单（最高 5.0）+ 2 个卖单（最低 6.0）
        # type 2002: 1 个买单，无卖单 → sell_price 应修复为 0.0
        buy_data = [
            {"type_id": 1001, "price": 4.5, "volume_remain": 100, "is_buy_order": True},
            {"type_id": 1001, "price": 5.0, "volume_remain": 200, "is_buy_order": True},
            {"type_id": 2002, "price": 10.0, "volume_remain": 50, "is_buy_order": True},
        ]
        sell_data = [
            {"type_id": 1001, "price": 7.0, "volume_remain": 150, "is_buy_order": False},
            {"type_id": 1001, "price": 6.0, "volume_remain": 300, "is_buy_order": False},
        ]

        # ── patch 内层函数，避免真实 HTTP ──
        with (
            patch("services.workers.getprices.discover_pages") as mock_discover,
            patch("services.workers.getprices.fetch_order_pages") as mock_fetch_pages,
            patch("services.workers.getprices.APIClient") as mock_api,
        ):
            client = _mock_client()
            mock_api.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_api.return_value.__aexit__ = AsyncMock(return_value=False)

            # discover_pages 返回单区域 Jita 均为 1 页
            mock_discover.return_value = {"10000002_buy": 1, "10000002_sell": 1}

            # fetch_order_pages 根据 order_type 返回不同数据
            async def _fetch_side(client, region_id, order_type, total_pages):
                if order_type == "buy":
                    return buy_data
                return sell_data

            mock_fetch_pages.side_effect = _fetch_side

            result = await fetch_orders(regions=[("Jita", 10000002)])

        # ── 验证 ──
        assert 10000002 in result
        region = result[10000002]

        # type 1001: 买单最高价 5.0, 卖单最低价 6.0, 成交量合计
        assert region[1001]["buy_price"] == 5.0
        assert region[1001]["sell_price"] == 6.0
        assert region[1001]["buy_volume"] == 300  # 100 + 200
        assert region[1001]["sell_volume"] == 450  # 150 + 300

        # type 2002: 仅有买单，sell_price 修复为 0.0
        assert region[2002]["buy_price"] == 10.0
        assert region[2002]["sell_price"] == 0.0
        assert region[2002]["buy_volume"] == 50
        assert region[2002]["sell_volume"] == 0

        # 验证 discover_pages 和 fetch_order_pages 各被调用
        mock_discover.assert_awaited_once()
        assert mock_fetch_pages.await_count == 2  # buy + sell


# ════════════════════════════════════════════════════════════
#  Test — save_prices 失败保护
# ════════════════════════════════════════════════════════════


class TestSavePrices:
    """save_prices — 拉取失败区域保留旧价格（回归：先 DELETE 后 INSERT 会清空旧数据）"""

    @pytest.mark.asyncio
    async def test_failed_region_skips_delete_and_insert(self):
        """拉取失败的区域（order_prices 无该 region）→ 不 DELETE 旧价格"""
        db = MagicMock()
        db.execute = AsyncMock()
        db.executemany = AsyncMock()
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        baseline = {
            1: {"buy_price": 1.0, "sell_price": 2.0, "adjusted_price": 1.5, "buy_volume": 10, "sell_volume": 20}
        }
        # 仅 10000002 成功，10000043 失败（不在 order_prices）
        order_prices = {
            10000002: {
                1: {"buy_price": 1.1, "sell_price": 2.1, "adjusted_price": 1.6, "buy_volume": 11, "sell_volume": 21}
            },
        }
        from services.workers import getprices

        with patch("services.workers.getprices.aiosqlite.connect", return_value=cm):
            cnt = await getprices.save_prices(baseline, order_prices, region_ids=[10000002, 10000043])

        # 只对成功区域执行 DELETE（1 次），失败区域无 DELETE
        deletes = [c[0][0] for c in db.execute.await_args_list if c[0] and "DELETE" in c[0][0]]
        assert len(deletes) == 1, f"只应对成功区域执行 1 次 DELETE，实际 {len(deletes)}"
        assert "10000002" in str(db.execute.await_args_list[0][0]), "DELETE 应针对成功区域"
        assert cnt == 1  # 只写入成功区域

    @pytest.mark.asyncio
    async def test_empty_region_data_keeps_old_prices(self):
        """区域数据为空 dict（拉取无结果）→ 跳过删除，旧价格保留"""
        db = MagicMock()
        db.execute = AsyncMock()
        db.executemany = AsyncMock()
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        baseline = {
            1: {"buy_price": 1.0, "sell_price": 2.0, "adjusted_price": 1.5, "buy_volume": 10, "sell_volume": 20}
        }
        order_prices = {10000002: {}}  # 区域存在但拉取结果为空

        from services.workers import getprices

        with patch("services.workers.getprices.aiosqlite.connect", return_value=cm):
            cnt = await getprices.save_prices(baseline, order_prices, region_ids=[10000002])

        deletes = [c[0][0] for c in db.execute.await_args_list if c[0] and "DELETE" in c[0][0]]
        assert deletes == [], "空数据区域不应执行 DELETE（旧价格保留）"
        assert cnt == 0


# ════════════════════════════════════════════════════════════
#  Test — fetch_baseline_only（初始化首启快速兜底）
# ════════════════════════════════════════════════════════════


class TestFetchBaselineOnly:
    """fetch_baseline_only — 仅拉 /markets/prices/ 基准价写入 5 个贸易区域"""

    @pytest.mark.asyncio
    async def test_writes_baseline_to_all_trade_regions(self):
        """非空 baseline → save_prices 被调用，覆盖全部贸易区域"""
        baseline = {
            1: {"buy_price": 1.0, "sell_price": 2.0, "adjusted_price": 1.5, "buy_volume": 10, "sell_volume": 20}
        }
        mock_save = AsyncMock(return_value=len(baseline))

        with (
            patch("services.workers.getprices.init_db", AsyncMock()),
            patch("services.workers.getprices.fetch_baseline_prices", AsyncMock(return_value=baseline)),
            patch("services.workers.getprices.save_prices", mock_save),
        ):
            await fetch_baseline_only(progress_cb=lambda pct, msg: None)

        expected_regions = [rid for _, rid in TRADE_REGIONS]
        assert len(expected_regions) == 5, "应有 5 个贸易区域"
        mock_save.assert_awaited_once()
        _args, _kwargs = mock_save.await_args
        # save_prices(baseline, {rid: baseline for all}, region_ids) — region_ids 为第 3 位置参数
        assert _args[2] == expected_regions
        assert _args[1] == dict.fromkeys(expected_regions, baseline)

    @pytest.mark.asyncio
    async def test_empty_baseline_skips_save(self):
        """baseline 为空（网络失败）→ 不写库，仅告警返回"""
        with (
            patch("services.workers.getprices.init_db", AsyncMock()),
            patch("services.workers.getprices.fetch_baseline_prices", AsyncMock(return_value={})),
            patch("services.workers.getprices.save_prices", AsyncMock()) as mock_save,
        ):
            await fetch_baseline_only()

        mock_save.assert_not_awaited()

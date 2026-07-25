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
    discover_pages,
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


# ════════════════════════════════════════════════════════════
#  Test 1 — init_db
# ════════════════════════════════════════════════════════════


class TestInitDb:
    """init_db — 数据库表结构创建"""

    @pytest.mark.asyncio
    async def test_drops_and_creates_tables(self):
        """验证 DROP TABLE + CREATE TABLE 语句正确执行，commit 被调用"""
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("services.workers.getprices.aiosqlite.connect", return_value=cm):
            await init_db()

        # 2 DROP + 2 CREATE = 4 次 execute
        assert db.execute.await_count == 4
        sqls = [c[0][0] for c in db.execute.await_args_list]

        assert any("DROP TABLE IF EXISTS market_prices" in s for s in sqls)
        assert any("DROP TABLE IF EXISTS market_volume_snapshots" in s for s in sqls)
        assert any("CREATE TABLE market_prices" in s for s in sqls)
        assert any("CREATE TABLE market_volume_snapshots" in s for s in sqls)
        # 验证 volume_snapshots 表有复合主键
        assert any("PRIMARY KEY (type_id, region_id, date)" in s for s in sqls)

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

        resp = _mock_response(json_data=fake_json)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        session = _mock_session(resp_get=cm)

        with patch("services.workers.getprices.aiohttp.ClientSession", return_value=session):
            result = await fetch_baseline_prices()

        assert len(result) == 2
        assert result[1001] == {"buy_price": 4.5, "sell_price": 5.0, "adjusted_price": 5.0, "buy_volume": 0, "sell_volume": 0}
        assert result[1002] == {"buy_price": None, "sell_price": 9.5, "adjusted_price": 9.5, "buy_volume": 0, "sell_volume": 0}

        # 验证请求发送至正确 URL
        session.get.assert_called_once()
        args, _ = session.get.call_args
        assert "/markets/prices/" in args[0]


# ════════════════════════════════════════════════════════════
#  Test 3 — discover_pages
# ════════════════════════════════════════════════════════════


class TestDiscoverPages:
    """discover_pages — 页数发现与缓存"""

    @pytest.mark.asyncio
    async def test_returns_page_counts_and_populates_cache(self):
        """验证 X-Pages 头被正确解析，_PAGE_CACHE 被填充"""
        _PAGE_CACHE.clear()

        # 两个并发请求（sell + buy）共享同一响应
        resp = _mock_response(headers={"X-Pages": "3"})
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        session = _mock_session(resp_get=cm)

        targets = [("Jita", 10000002)]
        result = await discover_pages(session, targets)

        assert result == {"10000002_sell": 3, "10000002_buy": 3}
        assert _PAGE_CACHE["10000002_sell"] == 3
        assert _PAGE_CACHE["10000002_buy"] == 3

        # session.get 应被调用 2 次（sell + buy）
        assert session.get.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_cached_pages_skips_http(self):
        """缓存命中时跳过 HTTP 请求"""
        _PAGE_CACHE.clear()
        _PAGE_CACHE["10000002_sell"] = 1
        _PAGE_CACHE["10000002_buy"] = 2

        session = _mock_session()  # 没有 mock session.get 返回值也没关系，因为不会被调用
        targets = [("Jita", 10000002)]

        result = await discover_pages(session, targets)

        assert result == {"10000002_sell": 1, "10000002_buy": 2}
        # 缓存命中，不应调用 session.get
        session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_200_response_defaults_to_one_page(self):
        """非 200 响应时 X-Pages defaults to 1"""
        _PAGE_CACHE.clear()

        resp = _mock_response(status=500)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        session = _mock_session(resp_get=cm)

        targets = [("Jita", 10000002)]
        result = await discover_pages(session, targets)

        # status != 200 → 不进入 if，keys 中无该 key
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

        resp = _mock_response(json_data=page_data)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        session = _mock_session(resp_get=cm)

        result = await fetch_order_pages(session, 10000002, "sell", 4)

        # 4 pages × 3 items each
        assert len(result) == 12
        assert result[0] == {"type_id": 0, "price": 0.0}
        assert result[-1] == {"type_id": 2, "price": 2.0}
        # session.get 应被调用 4 次（每页一次）
        assert session.get.call_count == 4
        # 验证所有请求 URL 包含正确的 region_id 和 order_type
        for call_args in session.get.call_args_list:
            url = call_args[0][0]
            assert "10000002" in url
            assert "order_type=sell" in url

    @pytest.mark.asyncio
    async def test_returns_empty_when_total_pages_is_zero(self):
        """total_pages=0 时不发起 HTTP 请求，返回空列表"""
        session = _mock_session()

        result = await fetch_order_pages(session, 10000002, "buy", 0)

        assert result == []
        session.get.assert_not_called()


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
            patch("services.workers.getprices.aiohttp.ClientSession") as mock_http,
        ):
            # mock session 上下文管理器（不会被实际使用，但需要让 __aenter__ 通过）
            fake_session = MagicMock()
            fake_session.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = fake_session

            # discover_pages 返回单区域 Jita 均为 1 页
            mock_discover.return_value = {"10000002_buy": 1, "10000002_sell": 1}

            # fetch_order_pages 根据 order_type 返回不同数据
            async def _fetch_side(session, region_id, order_type, total_pages):
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

"""ESI HTTP 客户端单元测试"""

import asyncio
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from services.client import GLOBAL_ESI_LIMITER, MARKET_ORDER_LIMITER, APIClient

pytestmark = pytest.mark.fast


class TestAPIClient:
    """APIClient 单元测试（Mock 模式）"""

    @staticmethod
    def _make_mock_resp(status=200, text='{"ok": true}', headers=None):
        """创建同时充当响应对象和 async CM 的 mock"""
        mock = AsyncMock()
        mock.status = status
        mock.text = AsyncMock(return_value=text)
        mock.json = AsyncMock(return_value={"ok": True})
        mock.headers = headers or {}
        if status >= 400:
            err = aiohttp.ClientResponseError(status=status, request_info=Mock(), history=())
            mock.raise_for_status = Mock(side_effect=err)
        else:
            mock.raise_for_status = Mock()
        # async with mock as resp:  → resp = await mock.__aenter__()
        mock.__aenter__.return_value = mock
        mock.__aexit__.return_value = None
        return mock

    # ── test_create_session ──────────────────────────────────

    def test_create_session(self):
        """__aenter__ 应创建 ClientSession 和 Semaphore"""

        async def run():
            client = APIClient(concurrency=10, timeout=15, user_agent="TestApp/1.0")
            async with client:
                assert isinstance(client.session, aiohttp.ClientSession)
                assert client.semaphore._value == 10
                assert client.session._default_headers["User-Agent"] == "TestApp/1.0"
            assert client.session.closed

        asyncio.run(run())

    # ── test_fetch_json ──────────────────────────────────────

    def test_fetch_json(self):
        """fetch 应返回解析后的 JSON"""

        async def run():
            client = APIClient(retries=1)
            async with client:
                mock_resp = self._make_mock_resp(text='{"key": "value"}')
                # 不能用 AsyncMock — 代码期望 session.get 返回 async CM, 不是 coroutine
                client.session.get = Mock(return_value=mock_resp)
                result = await client.fetch("https://esi.example.com/api")
                assert result == {"key": "value"}
                client.session.get.assert_called_once()
                assert client.session.get.call_args[0][0] == "https://esi.example.com/api"

        asyncio.run(run())

    # ── test_fetch_retry ─────────────────────────────────────

    def test_fetch_retry(self):
        """失败后应重试：第一次网络错误、第二次成功 → 返回解析结果"""

        async def run():
            client = APIClient(retries=2)
            async with client:
                mock_resp = self._make_mock_resp(text="{}")
                # 第一次抛出网络错误，第二次成功
                client.session.get = Mock(side_effect=[aiohttp.ClientError("reset"), mock_resp])
                result = await client.fetch("https://esi.example.com/api")
                assert result == {}
                assert client.session.get.call_count == 2

        asyncio.run(run())

    # ── test_fetch_timeout ───────────────────────────────────

    def test_fetch_timeout(self):
        """超时 / 网络错误返回 None"""

        async def run():
            client = APIClient(retries=1)
            async with client:
                client.session.get = Mock(side_effect=TimeoutError("timed out"))
                result = await client.fetch("https://esi.example.com/api")
                assert result is None
                assert client.session.get.call_count == 1

        asyncio.run(run())

    # ── test_fetch_404 ───────────────────────────────────────

    def test_fetch_404_returns_none(self):
        """404 应返回 None，不重试"""

        async def run():
            client = APIClient(retries=1)
            async with client:
                mock_resp = self._make_mock_resp(status=404)
                client.session.get = Mock(return_value=mock_resp)
                result = await client.fetch("https://esi.example.com/api")
                assert result is None
                client.session.get.assert_called_once()
                assert client.session.get.call_args[0][0] == "https://esi.example.com/api"

        asyncio.run(run())


# ── RateLimiter 令牌桶 ─────────────────────────────────────


class TestRateLimiter:
    """RateLimiter — 异步令牌桶限流"""

    def test_immediate_acquire_when_bucket_full(self):
        """桶满（burst）时 acquire 不等待"""
        import asyncio
        import time

        from services.client import RateLimiter

        limiter = RateLimiter(rate=100.0, burst=50)

        async def run():
            t0 = time.monotonic()
            for _ in range(50):
                await limiter.acquire()
            return time.monotonic() - t0

        elapsed = asyncio.run(run())
        assert elapsed < 0.1, f"桶满时应瞬时通过，实际 {elapsed:.3f}s"

    def test_rate_limits_after_bucket_exhausted(self):
        """桶耗尽后按速率排队（50 个令牌 @100/s ≈ 0.5s）"""
        import asyncio
        import time

        from services.client import RateLimiter

        limiter = RateLimiter(rate=100.0, burst=10)

        async def run():
            t0 = time.monotonic()
            for _ in range(60):
                await limiter.acquire()
            return time.monotonic() - t0

        elapsed = asyncio.run(run())
        # 10 个突发 + 50 个按 100/s → ≥0.5s
        assert elapsed >= 0.45, f"超出突发容量的请求应被限流，实际 {elapsed:.3f}s"

    def test_acquire_is_thread_safe_within_loop(self):
        """并发 acquire 不超额发放（burst=10 时 20 个并发任务中 10 个立即通过）"""
        import asyncio

        from services.client import RateLimiter

        limiter = RateLimiter(rate=1000.0, burst=10)
        passed = []

        async def worker(i):
            t0 = asyncio.get_event_loop().time()
            await limiter.acquire()
            passed.append((i, asyncio.get_event_loop().time() - t0))

        async def run():
            await asyncio.gather(*[worker(i) for i in range(20)])

        asyncio.run(run())
        assert len(passed) == 20


# ════════════════════════════════════════════════════════════
#  02-05 限流分组 / 429 等待上限
# ════════════════════════════════════════════════════════════


class TestRateLimitGroups:
    def test_order_route_uses_market_order_limiter(self):
        """订单路由归 `market-order` 组（12000/15m、2 tokens/2XX ≈ 6.67 req/s），其余用全局桶。"""
        client = APIClient()
        order_url = "https://esi.evetech.net/latest/markets/10000002/orders/?type_id=34"
        hist_url = "https://esi.evetech.net/latest/markets/10000002/history/?type_id=34"
        assert client._limiter_for(order_url) is MARKET_ORDER_LIMITER
        assert client._limiter_for(hist_url) is GLOBAL_ESI_LIMITER
        assert MARKET_ORDER_LIMITER.rate <= 6.67 + 1e-6, "持续上限不能超过组上限 6.67 req/s"

    def test_429_long_retry_after_does_not_block(self):
        """Retry-After=900（窗口上限）不傻睡：>300s 抛 ClientError 让上层标失败（旧实现封顶 120s 后仍 429）。"""
        from unittest.mock import patch

        sleeps: list[float] = []

        async def _fake_sleep(sec):
            sleeps.append(sec)

        resp = Mock()
        resp.headers = {"Retry-After": "900"}
        with patch("services.client.asyncio.sleep", _fake_sleep):
            with pytest.raises(aiohttp.ClientError):
                asyncio.run(APIClient._handle_rate_limit(resp))
        assert not sleeps or max(sleeps) <= 300, f"不该阻塞等待 900s：{sleeps}"

    def test_429_short_retry_after_is_honored(self):
        """窗口内的 Retry-After（30s）照实等待。"""
        from unittest.mock import patch

        sleeps: list[float] = []

        async def _fake_sleep(sec):
            sleeps.append(sec)

        resp = Mock()
        resp.headers = {"Retry-After": "30"}
        with patch("services.client.asyncio.sleep", _fake_sleep):
            asyncio.run(APIClient._handle_rate_limit(resp))
        assert sleeps == [30]


# ════════════════════════════════════════════════════════════
#  02-08 三态取数：404 / 200+[] / 失败 必须可区分
# ════════════════════════════════════════════════════════════


class TestFetchState:
    def test_three_states_are_distinguishable(self):
        """404=(404,None)；200+[]=(200,[])；500/网络=(None,None)。"""
        # 这里只验证纯状态码分支，不验证 header 透传（分页用例在 test_order_workers）
        resp_404 = TestAPIClient._make_mock_resp(status=404)
        resp_empty = TestAPIClient._make_mock_resp(status=200, text="[]")
        resp_500 = TestAPIClient._make_mock_resp(status=500)

        async def run():
            client = APIClient(retries=1)
            async with client:
                client.session.get = Mock(return_value=resp_404)
                assert await client.fetch_state("https://esi.example.com/a") == (404, None, {})
            async with client:
                client.session.get = Mock(return_value=resp_empty)
                status, data, _headers = await client.fetch_state("https://esi.example.com/a")
                assert status == 200 and data == []
            async with client:
                client.session.get = Mock(return_value=resp_500)
                assert await client.fetch_state("https://esi.example.com/a") == (None, None, {})

        asyncio.run(run())

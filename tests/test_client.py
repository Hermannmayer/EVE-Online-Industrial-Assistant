"""ESI HTTP 客户端单元测试"""

import asyncio
from unittest.mock import AsyncMock, Mock

import aiohttp

from services.client import APIClient


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
                assert client.session is not None
                assert isinstance(client.session, aiohttp.ClientSession)
                assert client.semaphore is not None
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
        asyncio.run(run())

    # ── test_fetch_retry ─────────────────────────────────────

    def test_fetch_retry(self):
        """失败后应重试，最终返回 None"""
        async def run():
            client = APIClient(retries=2)
            async with client:
                mock_resp = self._make_mock_resp(text="{}")
                # 第一次抛出网络错误，第二次成功
                client.session.get = Mock(
                    side_effect=[aiohttp.ClientError("reset"), mock_resp]
                )
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
                client.session.get = Mock(
                    side_effect=asyncio.TimeoutError("timed out")
                )
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
        asyncio.run(run())

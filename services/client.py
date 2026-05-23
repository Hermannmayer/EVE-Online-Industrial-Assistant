"""
共享 HTTP 客户端 — 所有 worker 统一使用
"""
import aiohttp
import asyncio
import json
from tenacity import retry, stop_after_attempt, wait_exponential


class APIClient:
    """异步 HTTP 客户端（含重试、并发控制）"""

    def __init__(self, concurrency: int = 20, timeout: int = 30,
                 user_agent: str = "EveApp/1.0", retries: int = 3):
        self._concurrency = concurrency
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._user_agent = user_agent
        self._retries = retries
        self.session: aiohttp.ClientSession | None = None
        self.semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self):
        self.semaphore = asyncio.Semaphore(self._concurrency)
        self.session = aiohttp.ClientSession(headers={
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        })
        return self

    async def __aexit__(self, *exc):
        if self.session:
            await self.session.close()

    async def fetch(self, url: str):
        """GET 请求，返回解析后的 JSON，404/超时返回 None"""
        retry_deco = retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, min=1, max=5),
        )

        @retry_deco
        async def _do_fetch():
            async with self.semaphore:
                async with self.session.get(url, timeout=self._timeout) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    text = await resp.text()
                    if not text.strip():
                        return None
                    return json.loads(text)

        try:
            return await _do_fetch()
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
            return None

    async def fetch_required(self, url: str):
        """GET 请求，失败时抛出异常"""
        async with self.semaphore:
            async with self.session.get(url, timeout=self._timeout) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_text(self, url: str) -> str | None:
        """GET 请求，返回原始文本"""
        async with self.semaphore:
            async with self.session.get(url, timeout=self._timeout) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.text()

"""
共享 HTTP 客户端 — 所有 worker 统一使用
"""

import asyncio
import json
import threading
import time

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential


class RateLimiter:
    """异步令牌桶限流器 — ESI 要求 ≤20 req/s，超发时自动排队等待。

    用法：请求前 `await limiter.acquire()`。rate 为每秒令牌数，
    burst 为瞬时突发上限（桶容量）。

    用 threading.Lock 保护令牌更新：不绑定事件循环（模块级单例可被
    多个 asyncio.run 复用，重试不会抛 "bound to a different event loop"），
    同时线程安全。
    """

    def __init__(self, rate: float = 20.0, burst: int = 40):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    async def acquire(self) -> None:
        """获取一个令牌（不足时按速率等待）"""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)

    @property
    def rate(self) -> float:
        return self._rate


# 全应用共享的 ESI 令牌桶：多个步骤并行下载时（prices/implants/rigs/industry），
# 所有 APIClient 共用同一个桶，避免对 esi.evetech.net 的合速率超过 20 req/s 触发 429 雪崩。
GLOBAL_ESI_LIMITER = RateLimiter(rate=20.0, burst=40)


class APIClient:
    """异步 HTTP 客户端（含重试、并发控制、全局限流）"""

    def __init__(
        self,
        concurrency: int = 20,
        timeout: int = 30,
        user_agent: str = "EveApp/1.0",
        retries: int = 3,
        limiter: RateLimiter | None = None,
    ):
        self._concurrency = concurrency
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._user_agent = user_agent
        self._retries = retries
        self.session: aiohttp.ClientSession | None = None
        self.semaphore: asyncio.Semaphore | None = None
        # ESI 全局限流：≤20 req/s（进程内全部请求共享同一个限流器，可传入独立实例供测试）
        self._limiter = limiter if limiter is not None else GLOBAL_ESI_LIMITER

    @property
    def limiter(self) -> RateLimiter:
        """共享限流器 — worker 直接用它保护裸请求"""
        return self._limiter

    async def __aenter__(self):
        self.semaphore = asyncio.Semaphore(self._concurrency)
        self.session = aiohttp.ClientSession(
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            }
        )
        return self

    async def __aexit__(self, *exc):
        if self.session:
            await self.session.close()

    @staticmethod
    async def _handle_rate_limit(resp: aiohttp.ClientResponse):
        """处理 ESI 429 限流：读取 Retry-After 响应头并等待（最多 120 秒）"""
        retry_after = resp.headers.get("Retry-After", "30")
        wait_time = int(retry_after) if retry_after.isdigit() else 30
        await asyncio.sleep(min(wait_time, 120))

    async def fetch(self, url: str) -> dict | None:
        """GET 请求，返回解析后的 JSON，404/超时返回 None"""
        retry_deco = retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            reraise=True,
        )

        @retry_deco
        async def _do_fetch() -> dict | None:
            await self._limiter.acquire()
            async with self.semaphore:  # type: ignore[union-attr]
                async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                    if resp.status == 429:
                        await self._handle_rate_limit(resp)
                        raise aiohttp.ClientError("Rate limited, retrying...")
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    text = await resp.text()
                    if not text.strip():
                        return None
                    parsed = json.loads(text)
                    return parsed if isinstance(parsed, dict) else None

        try:
            return await _do_fetch()
        except (TimeoutError, aiohttp.ClientError):
            return None

    async def fetch_raw(self, url: str) -> list | None:
        """GET 请求，返回原始 JSON（列表响应，如订单簿页），404/超时返回 None"""
        for attempt in range(self._retries):
            try:
                await self._limiter.acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            if attempt + 1 < self._retries:
                                continue
                            return None
                        if resp.status == 404:
                            return None
                        resp.raise_for_status()
                        text = await resp.text()
                        if not text.strip():
                            return None
                        parsed = json.loads(text)
                        return parsed if isinstance(parsed, list) else None
            except (TimeoutError, aiohttp.ClientError):
                if attempt + 1 >= self._retries:
                    return None
                await asyncio.sleep(min(2**attempt, 5))
        return None

    async def get_headers(self, url: str) -> dict[str, str] | None:
        """GET 请求，返回响应头（X-Pages 等）；非 200 返回 None"""
        for attempt in range(self._retries):
            try:
                await self._limiter.acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            if attempt + 1 < self._retries:
                                continue
                            return None
                        if resp.status != 200:
                            return None
                        return dict(resp.headers)
            except (TimeoutError, aiohttp.ClientError):
                if attempt + 1 >= self._retries:
                    return None
                await asyncio.sleep(min(2**attempt, 5))
        return None

    async def fetch_required(self, url: str):
        """GET 请求，失败时抛出异常"""
        retries_left = max(self._retries, 3)
        while retries_left > 0:
            try:
                await self._limiter.acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            retries_left -= 1
                            continue
                        resp.raise_for_status()
                        return await resp.json()
            except (TimeoutError, aiohttp.ClientError):
                retries_left -= 1
                if retries_left <= 0:
                    raise
                await asyncio.sleep(min(2 ** (max(self._retries, 3) - retries_left), 5))
        raise aiohttp.ClientError("Rate limit retries exhausted")

    async def get_text(self, url: str) -> str | None:
        """GET 请求，返回原始文本"""
        retries_left = max(self._retries, 3)
        while retries_left > 0:
            try:
                await self._limiter.acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            retries_left -= 1
                            continue
                        if resp.status == 404:
                            return None
                        resp.raise_for_status()
                        return await resp.text()
            except (TimeoutError, aiohttp.ClientError):
                retries_left -= 1
                if retries_left <= 0:
                    return None
                await asyncio.sleep(min(2 ** (max(self._retries, 3) - retries_left), 5))
        return None

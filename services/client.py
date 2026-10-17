"""
共享 HTTP 客户端 — 所有 worker 统一使用
"""

import asyncio
import json
import threading
import time

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logger import log


class RateLimiter:
    """异步令牌桶限流器 — 按路由所属限流组排队，超发时等待。

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

#: `market-order` 限流组（`/markets/{region_id}/orders`）独立建桶（02-05）：
#: 官方实测 `X-Ratelimit-Limit: 12000/15m`、每个 2XX `X-Ratelimit-Used: 2`
#: ⇒ 持续上限 = 12000 ÷ 2 ÷ 900 ≈ **6.67 req/s**，旧的 20 req/s 是它的 3 倍。
MARKET_ORDER_LIMITER = RateLimiter(rate=12000 / 2 / 900, burst=40)


def _is_market_order_url(url: str) -> bool:
    """订单路由（归 `market-order` 组，2 tokens/2XX）；history/prices 等不归组。"""
    return "/markets/" in url and "/orders" in url


def _rate_remaining(headers) -> int | None:
    """`X-Ratelimit-Remaining` → int（缺失/非法 → None）。"""
    try:
        return int(headers.get("X-Ratelimit-Remaining"))
    except (TypeError, ValueError):
        return None


def _rate_reset_seconds(headers) -> int | None:
    """`X-Ratelimit-Reset`（距窗口重置的秒数）→ int（缺失/非法 → None）。"""
    try:
        return int(float(headers.get("X-Ratelimit-Reset")))
    except (TypeError, ValueError):
        return None


class APIClient:
    """异步 HTTP 客户端（含重试、并发控制、按限流组排队）"""

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
        # ESI 全局限流（进程内全部请求共享同一个限流器，可传入独立实例供测试）
        self._limiter = limiter if limiter is not None else GLOBAL_ESI_LIMITER

    @property
    def limiter(self) -> RateLimiter:
        """共享限流器 — worker 直接用它保护裸请求"""
        return self._limiter

    def _limiter_for(self, url: str) -> RateLimiter:
        """按 URL 选限流桶：订单路由走 `market-order` 组（02-05），其余用注入/全局桶。

        注入了自定义 limiter（测试/隔离场景）时一律用它，保证替身行为可预测。
        """
        if self._limiter is GLOBAL_ESI_LIMITER and _is_market_order_url(url):
            return MARKET_ORDER_LIMITER
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
        """处理 ESI 429 限流（02-05）。

        `Retry-After` 是「令牌回填所需秒数」，最大可到窗口 900s（旧实现封顶 120s →
        等完再 429）。这里：优先 Retry-After，缺失时用 `X-Ratelimit-Reset`；上限 900s；
        **超过 300s 不阻塞傻等**——抛 ClientError 让调用方把本轮标失败/报错（与三态模型联动）。
        """
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None and str(retry_after).isdigit():
            wait = int(retry_after)
        else:
            wait = _rate_reset_seconds(resp.headers) or 30
        wait = max(1, min(wait, 900))
        if wait > 300:
            log.warning("ESI 429 要求等待 %ss（>300s），本轮不阻塞、按失败处理", wait)
            raise aiohttp.ClientError(f"rate limited, retry-after={wait}s")
        await asyncio.sleep(wait)

    @staticmethod
    def _note_rate_headers(url: str, headers) -> None:
        """读 `X-Ratelimit-*`（02-05）：余量低时告警，便于定位「快打满」的批次。"""
        remaining = _rate_remaining(headers)
        if remaining is None:
            return
        if remaining <= 20:
            log.warning(
                "ESI 限流余量低：remaining=%s reset=%ss url=%s",
                remaining,
                _rate_reset_seconds(headers),
                url,
            )

    async def fetch(self, url: str) -> dict | None:
        """GET 请求，返回解析后的 JSON，404/超时返回 None"""
        retry_deco = retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            reraise=True,
        )

        @retry_deco
        async def _do_fetch() -> dict | None:
            await self._limiter_for(url).acquire()
            async with self.semaphore:  # type: ignore[union-attr]
                async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                    self._note_rate_headers(url, resp.headers)
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
                await self._limiter_for(url).acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        self._note_rate_headers(url, resp.headers)
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

    async def fetch_state(self, url: str) -> tuple[int | None, list | None, dict]:
        """GET 列表响应，返回**三态**（02-08）：

        - `(200, list, headers)`：成功（`list` 可能是 `[]`，那是**合法空**）；
        - `(404, None, headers)`：资源不存在（不重试）；
        - `(None, None, {})`：429 重试耗尽 / 5xx / 网络 / 超时 / 非列表载荷（可重试失败）。

        与 `fetch_raw` 的区别：不把「失败」和「空数组」压平成同一个 `None`，
        用户可见的读端（订单详情/定向刷新）才能分别显示「空」与「拉取失败」。
        headers 供调用方读 `X-Pages`（02-11 分页）。
        """
        for attempt in range(self._retries):
            try:
                await self._limiter_for(url).acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.get(url, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        headers = dict(resp.headers)
                        self._note_rate_headers(url, resp.headers)
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            if attempt + 1 < self._retries:
                                continue
                            return None, None, {}
                        if resp.status == 404:
                            return 404, None, headers
                        resp.raise_for_status()
                        text = await resp.text()
                        if not text.strip():
                            return int(resp.status), [], headers
                        parsed = json.loads(text)
                        return int(resp.status), (parsed if isinstance(parsed, list) else None), headers
            except (TimeoutError, aiohttp.ClientError):
                if attempt + 1 >= self._retries:
                    return None, None, {}
                await asyncio.sleep(min(2**attempt, 5))
        return None, None, {}

    async def get_headers(self, url: str) -> dict[str, str] | None:
        """GET 请求，返回响应头（X-Pages 等）；非 200 返回 None"""
        for attempt in range(self._retries):
            try:
                await self._limiter_for(url).acquire()
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
                await self._limiter_for(url).acquire()
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

    async def post(self, url: str, json: dict | list | None = None):
        """POST JSON 请求，返回解析后的 JSON；404/超时返回 None。"""
        for attempt in range(self._retries):
            try:
                await self._limiter_for(url).acquire()
                async with self.semaphore:  # type: ignore[union-attr]
                    async with self.session.post(url, json=json, timeout=self._timeout) as resp:  # type: ignore[union-attr]
                        if resp.status == 429:
                            await self._handle_rate_limit(resp)
                            if attempt + 1 < self._retries:
                                continue
                            return None
                        if resp.status == 404:
                            return None
                        resp.raise_for_status()
                        return await resp.json()
            except (TimeoutError, aiohttp.ClientError):
                if attempt + 1 >= self._retries:
                    return None
                await asyncio.sleep(min(2**attempt, 5))
        return None

    async def get_text(self, url: str) -> str | None:
        """GET 请求，返回原始文本"""
        retries_left = max(self._retries, 3)
        while retries_left > 0:
            try:
                await self._limiter_for(url).acquire()
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

# services.client

> 源文件 `services/client.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

共享 HTTP 客户端 — 所有 worker 统一使用

## 函数

### `_is_market_order_url`

```python
def _is_market_order_url(url: str) -> bool
```

订单路由（归 `market-order` 组，2 tokens/2XX）；history/prices 等不归组。

定义行：`62`

### `_rate_remaining`

```python
def _rate_remaining(headers) -> int | None
```

`X-Ratelimit-Remaining` → int（缺失/非法 → None）。

定义行：`67`

### `_rate_reset_seconds`

```python
def _rate_reset_seconds(headers) -> int | None
```

`X-Ratelimit-Reset`（距窗口重置的秒数）→ int（缺失/非法 → None）。

定义行：`75`

## 类

### `class RateLimiter`

异步令牌桶限流器 — 按路由所属限流组排队，超发时等待。

用法：请求前 `await limiter.acquire()`。rate 为每秒令牌数，
burst 为瞬时突发上限（桶容量）。

用 threading.Lock 保护令牌更新：不绑定事件循环（模块级单例可被
多个 asyncio.run 复用，重试不会抛 "bound to a different event loop"），
同时线程安全。

定义行：`16`

#### 方法

##### `__init__`

```python
def __init__(self, rate: float=20.0, burst: int=40)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`27`
##### `acquire`

```python
async def acquire(self) -> None
```

获取一个令牌（不足时按速率等待）

定义行：`34`
##### `rate`

```python
def rate(self) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`48`

### `class APIClient`

异步 HTTP 客户端（含重试、并发控制、按限流组排队）

定义行：`83`

#### 方法

##### `__init__`

```python
def __init__(self, concurrency: int=20, timeout: int=30, user_agent: str='EveApp/1.0', retries: int=3, limiter: RateLimiter | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`
##### `limiter`

```python
def limiter(self) -> RateLimiter
```

共享限流器 — worker 直接用它保护裸请求

定义行：`104`
##### `_limiter_for`

```python
def _limiter_for(self, url: str) -> RateLimiter
```

按 URL 选限流桶：订单路由走 `market-order` 组（02-05），其余用注入/全局桶。

定义行：`108`
##### `__aenter__`

```python
async def __aenter__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`117`
##### `__aexit__`

```python
async def __aexit__(self, *exc)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`127`
##### `_handle_rate_limit`

```python
async def _handle_rate_limit(resp: aiohttp.ClientResponse)
```

处理 ESI 429 限流（02-05）。

定义行：`132`
##### `_note_rate_headers`

```python
def _note_rate_headers(url: str, headers) -> None
```

读 `X-Ratelimit-*`（02-05）：余量低时告警，便于定位「快打满」的批次。

定义行：`151`
##### `fetch`

```python
async def fetch(self, url: str) -> dict | None
```

GET 请求，返回解析后的 JSON，404/超时返回 None

定义行：`164`
##### `fetch_raw`

```python
async def fetch_raw(self, url: str) -> list | None
```

GET 请求，返回原始 JSON（列表响应，如订单簿页），404/超时返回 None

定义行：`195`
##### `fetch_state`

```python
async def fetch_state(self, url: str) -> tuple[int | None, list | None, dict]
```

GET 列表响应，返回**三态**（02-08）：

定义行：`222`
##### `get_headers`

```python
async def get_headers(self, url: str) -> dict[str, str] | None
```

GET 请求，返回响应头（X-Pages 等）；非 200 返回 None

定义行：`259`
##### `fetch_required`

```python
async def fetch_required(self, url: str)
```

GET 请求，失败时抛出异常

定义行：`280`
##### `post`

```python
async def post(self, url: str, json: dict | list | None=None)
```

POST JSON 请求，返回解析后的 JSON；404/超时返回 None。

定义行：`301`
##### `get_text`

```python
async def get_text(self, url: str) -> str | None
```

GET 请求，返回原始文本

定义行：`323`

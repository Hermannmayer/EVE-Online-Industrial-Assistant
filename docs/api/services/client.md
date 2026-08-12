# services.client

> 源文件 `services/client.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

共享 HTTP 客户端 — 所有 worker 统一使用

## 类

### `class RateLimiter`

异步令牌桶限流器 — ESI 要求 ≤20 req/s，超发时自动排队等待。

定义行：`14`

#### 方法

##### `__init__`

```python
def __init__(self, rate: float=20.0, burst: int=40)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`
##### `acquire`

```python
async def acquire(self) -> None
```

获取一个令牌（不足时按速率等待）

定义行：`32`
##### `rate`

```python
def rate(self) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`

### `class APIClient`

异步 HTTP 客户端（含重试、并发控制、全局限流）

定义行：`55`

#### 方法

##### `__init__`

```python
def __init__(self, concurrency: int=20, timeout: int=30, user_agent: str='EveApp/1.0', retries: int=3, limiter: RateLimiter | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`58`
##### `limiter`

```python
def limiter(self) -> RateLimiter
```

共享限流器 — worker 直接用它保护裸请求

定义行：`76`
##### `__aenter__`

```python
async def __aenter__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`80`
##### `__aexit__`

```python
async def __aexit__(self, *exc)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`90`
##### `_handle_rate_limit`

```python
async def _handle_rate_limit(resp: aiohttp.ClientResponse)
```

处理 ESI 429 限流：读取 Retry-After 响应头并等待（最多 120 秒）

定义行：`95`
##### `fetch`

```python
async def fetch(self, url: str) -> dict | None
```

GET 请求，返回解析后的 JSON，404/超时返回 None

定义行：`101`
##### `fetch_raw`

```python
async def fetch_raw(self, url: str) -> list | None
```

GET 请求，返回原始 JSON（列表响应，如订单簿页），404/超时返回 None

定义行：`131`
##### `get_headers`

```python
async def get_headers(self, url: str) -> dict[str, str] | None
```

GET 请求，返回响应头（X-Pages 等）；非 200 返回 None

定义行：`148`
##### `fetch_required`

```python
async def fetch_required(self, url: str)
```

GET 请求，失败时抛出异常

定义行：`160`
##### `get_text`

```python
async def get_text(self, url: str) -> str | None
```

GET 请求，返回原始文本

定义行：`174`

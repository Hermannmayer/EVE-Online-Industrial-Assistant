# services.client

> 源文件 `services/client.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

共享 HTTP 客户端 — 所有 worker 统一使用

## 类

### `class APIClient`

异步 HTTP 客户端（含重试、并发控制）

定义行：`12`

#### 方法

##### `__init__`

```python
def __init__(self, concurrency: int=20, timeout: int=30, user_agent: str='EveApp/1.0', retries: int=3)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`15`
##### `__aenter__`

```python
async def __aenter__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`
##### `__aexit__`

```python
async def __aexit__(self, *exc)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`33`
##### `_handle_rate_limit`

```python
async def _handle_rate_limit(resp: aiohttp.ClientResponse)
```

处理 ESI 429 限流：读取 Retry-After 响应头并等待（最多 120 秒）

定义行：`38`
##### `fetch`

```python
async def fetch(self, url: str)
```

GET 请求，返回解析后的 JSON，404/超时返回 None

定义行：`44`
##### `fetch_required`

```python
async def fetch_required(self, url: str)
```

GET 请求，失败时抛出异常

定义行：`72`
##### `get_text`

```python
async def get_text(self, url: str) -> str | None
```

GET 请求，返回原始文本

定义行：`86`

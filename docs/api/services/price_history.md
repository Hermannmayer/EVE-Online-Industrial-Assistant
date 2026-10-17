# services.price_history

> 源文件 `services/price_history.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Market price history — ESI /markets/&#123;region_id&#125;/history/
Cache in market.db price_history table

## 函数

### `_last_history_update`

```python
def _last_history_update(now: datetime) -> datetime
```

最近一次 ESI 日更点（UTC naive）。

定义行：`59`

### `_ensure_table`

```python
def _ensure_table(db=None) -> None
```

Ensure price_history table（与索引）exists in market.db

定义行：`70`

### `fetch_history`

```python
async def fetch_history(type_id: int, region_id: int=REGION_ID, session: aiohttp.ClientSession | None=None, *, etag: str | None=None, etag_holder: list | None=None) -> list[dict] | None | object
```

Fetch price history from ESI /markets/&#123;region_id&#125;/history/

定义行：`78`

### `get_cached_history`

```python
def get_cached_history(type_id: int, region_id: int=REGION_ID, _db=None) -> list[dict] | None
```

Read cached history from market.db

定义行：`121`

### `save_cache`

```python
def save_cache(type_id: int, region_id: int, data: list[dict], _db=None) -> None
```

Save price history to market.db cache

定义行：`151`

### `get_history_summary`

```python
def get_history_summary(type_ids, region_id: int=REGION_ID, days: int=SUMMARY_DAYS, _db=None, today: date | None=None) -> dict[int, dict]
```

读本地缓存，算「最近 `days` 个**日历天**的平均订单量 / 成交量」→ `&#123;type_id: &#123;...&#125;&#125;`。

定义行：`189`

## 类

### `class PriceHistoryService`

价格历史服务 — 容器注入 DatabaseManager（替代模块级 get_db 单例）

定义行：`274`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`277`
##### `fetch`

```python
async def fetch(self, type_id: int, region_id: int=REGION_ID, session=None) -> list[dict] | None
```

拉取 ESI 历史价格（失败返回 None）。

定义行：`280`
##### `get_cached`

```python
def get_cached(self, type_id: int, region_id: int=REGION_ID) -> list[dict] | None
```

读取缓存历史价格（TTL 内命中，否则 None）

定义行：`289`
##### `save`

```python
def save(self, type_id: int, region_id: int, data: list[dict]) -> None
```

写入缓存历史价格

定义行：`293`

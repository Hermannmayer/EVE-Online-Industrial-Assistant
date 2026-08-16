# services.price_history

> 源文件 `services/price_history.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Market price history — ESI /markets/&#123;region_id&#125;/history/
Cache in market.db price_history table

## 函数

### `_ensure_table`

```python
def _ensure_table(db=None) -> None
```

Ensure price_history table exists in market.db

定义行：`19`

### `fetch_history`

```python
async def fetch_history(type_id: int, region_id: int=REGION_ID, session: aiohttp.ClientSession | None=None) -> list[dict] | None
```

Fetch price history from ESI /markets/&#123;region_id&#125;/history/

定义行：`39`

### `get_cached_history`

```python
def get_cached_history(type_id: int, region_id: int=REGION_ID, _db=None) -> list[dict] | None
```

Read cached history from market.db

定义行：`70`

### `save_cache`

```python
def save_cache(type_id: int, region_id: int, data: list[dict], _db=None) -> None
```

Save price history to market.db cache

定义行：`99`

## 类

### `class PriceHistoryService`

价格历史服务 — 容器注入 DatabaseManager（替代模块级 get_db 单例）

定义行：`129`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`132`
##### `fetch`

```python
async def fetch(self, type_id: int, region_id: int=REGION_ID, session=None) -> list[dict] | None
```

拉取 ESI 历史价格（失败返回 None）

定义行：`135`
##### `get_cached`

```python
def get_cached(self, type_id: int, region_id: int=REGION_ID) -> list[dict] | None
```

读取缓存历史价格（TTL 内命中，否则 None）

定义行：`139`
##### `save`

```python
def save(self, type_id: int, region_id: int, data: list[dict]) -> None
```

写入缓存历史价格

定义行：`143`

# services.price_history

> 源文件 `services/price_history.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Market price history — ESI /markets/&#123;region_id&#125;/history/
Cache in market.db price_history table

## 函数

### `_ensure_table`

```python
def _ensure_table() -> None
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
def get_cached_history(type_id: int, region_id: int=REGION_ID) -> list[dict] | None
```

Read cached history from market.db

定义行：`69`

### `save_cache`

```python
def save_cache(type_id: int, region_id: int, data: list[dict]) -> None
```

Save price history to market.db cache

定义行：`98`

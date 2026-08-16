# services.price_refresh_service

> 源文件 `services/price_refresh_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

定向价格刷新服务 — 缓存检查与价格落库。

## 函数

### `check_stale_type_ids`

```python
async def check_stale_type_ids(type_ids: set[int]) -> set[int]
```

返回需要刷新的 type_id（无数据或超过 TTL）。

定义行：`15`

### `save_refreshed_prices`

```python
async def save_refreshed_prices(type_orders: dict[int, dict], region_id: int=10000002) -> int
```

把拉取到的价格写入 market_prices，保留 adjusted_price。返回写入条数。

定义行：`41`

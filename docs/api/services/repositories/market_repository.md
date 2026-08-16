# services.repositories.market_repository

> 源文件 `services/repositories/market_repository.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

市场价格数据查询仓库

## 类

### `class MarketRepository`

市场价格只读查询

定义行：`8`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`11`
##### `get_price`

```python
def get_price(self, type_id: int, price_type: str, hub: str | None=None) -> float | None
```

获取指定区域的价格。price_type: 'buy' / 'sell'

定义行：`16`
##### `get_volume`

```python
def get_volume(self, type_id: int, vol_type: str='total', hub: str | None=None) -> int
```

获取成交量。vol_type: 'buy' / 'sell' / 'total'

定义行：`42`
##### `get_latest_fetch_time`

```python
def get_latest_fetch_time(self) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`72`
##### `has_any_prices`

```python
def has_any_prices(self) -> bool
```

市场价表是否已有任意价格数据。

定义行：`77`
##### `get_batch_market_snapshot`

```python
def get_batch_market_snapshot(self, type_ids: list[int], region_id: int) -> dict[int, dict[str, float | int | None]]
```

批量获取指定区域的市场价/量快照。

定义行：`83`
##### `get_prices_by_region`

```python
def get_prices_by_region(self, type_ids: list[int], region_id: int, price_type: str) -> dict[int, float]
```

批量获取指定区域价格（buy/sell/avg）。

定义行：`109`
##### `get_sell_prices`

```python
def get_sell_prices(self, type_ids: list[int], region_id: int) -> dict[int, float]
```

批量获取指定区域卖单价。

定义行：`139`
##### `get_price_by_region`

```python
def get_price_by_region(self, type_id: int, price_type: str, region_id: int) -> float | None
```

获取指定区域的价格；price_type: 'buy' / 'sell' / 'avg'。

定义行：`151`
##### `get_latest_price`

```python
def get_latest_price(self, type_id: int) -> tuple[float | None, float | None, int, int] | None
```

获取指定物品最新一条价格记录 (buy_price, sell_price, buy_volume, sell_volume)。

定义行：`172`
##### `get_adjusted_price`

```python
def get_adjusted_price(self, type_id: int) -> float | None
```

获取 ESI adjusted_price（EIV 计算用）。列不存在时回退 sell_price。

定义行：`189`

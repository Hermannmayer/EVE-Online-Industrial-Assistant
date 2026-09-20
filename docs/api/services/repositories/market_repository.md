# services.repositories.market_repository

> 源文件 `services/repositories/market_repository.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

市场价格数据查询仓库

## 函数

### `_chunked`

```python
def _chunked(ids: list[int]) -> Iterator[list[int]]
```

按绑定变量上限切批，供批量查询的 `IN (?)` 使用。

定义行：`16`

## 类

### `class MarketRepository`

市场价格只读查询

定义行：`22`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`
##### `get_price`

```python
def get_price(self, type_id: int, price_type: str, hub: str | None=None) -> float | None
```

获取指定区域的价格。price_type: 'buy' / 'sell'

定义行：`30`
##### `get_volume`

```python
def get_volume(self, type_id: int, vol_type: str='total', hub: str | None=None) -> int
```

获取成交量。vol_type: 'buy' / 'sell' / 'total'

定义行：`56`
##### `get_latest_fetch_time`

```python
def get_latest_fetch_time(self) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`
##### `has_any_prices`

```python
def has_any_prices(self) -> bool
```

市场价表是否已有任意价格数据。

定义行：`91`
##### `get_batch_market_snapshot`

```python
def get_batch_market_snapshot(self, type_ids: list[int], region_id: int) -> dict[int, dict[str, float | int | None]]
```

批量获取指定区域的市场价/量快照。

定义行：`97`
##### `get_prices_by_region`

```python
def get_prices_by_region(self, type_ids: list[int], region_id: int, price_type: str) -> dict[int, float]
```

批量获取指定区域价格（buy/sell/avg）。

定义行：`123`
##### `get_sell_prices`

```python
def get_sell_prices(self, type_ids: list[int], region_id: int) -> dict[int, float]
```

批量获取指定区域卖单价。

定义行：`155`
##### `get_price_by_region`

```python
def get_price_by_region(self, type_id: int, price_type: str, region_id: int) -> float | None
```

获取指定区域的价格；price_type: 'buy' / 'sell' / 'avg'。

定义行：`171`
##### `get_latest_price`

```python
def get_latest_price(self, type_id: int) -> tuple[float | None, float | None, int, int] | None
```

获取指定物品最新一条价格记录 (buy_price, sell_price, buy_volume, sell_volume)。

定义行：`192`
##### `get_adjusted_price`

```python
def get_adjusted_price(self, type_id: int) -> float | None
```

获取 ESI adjusted_price（EIV 计算用）。列不存在时回退 sell_price。

定义行：`209`
##### `get_adjusted_prices`

```python
def get_adjusted_prices(self, type_ids: list[int]) -> dict[int, float] | None
```

批量获取 adjusted price（EIV 用），只返回 > 0 的行 —— 与 get_adjusted_price 同口径。

定义行：`226`
##### `get_system_cost_index`

```python
def get_system_cost_index(self, system_id: int | None, activity: str='manufacturing', hub: str='Jita') -> float
```

星系的制造成本指数（SCI）。`system_id=None` 时从 hub 名称推断，查无统一用默认值。

定义行：`248`

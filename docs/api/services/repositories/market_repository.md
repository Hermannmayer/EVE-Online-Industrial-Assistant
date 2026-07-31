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
##### `get_item_with_price`

```python
def get_item_with_price(self, type_id: int) -> dict | None
```

获取物品信息及其市场价格（跨库 JOIN）

定义行：`72`
##### `get_latest_fetch_time`

```python
def get_latest_fetch_time(self) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`
##### `get_adjusted_price`

```python
def get_adjusted_price(self, type_id: int) -> float | None
```

获取 ESI adjusted_price（EIV 计算用）。列不存在时回退 sell_price。

定义行：`88`

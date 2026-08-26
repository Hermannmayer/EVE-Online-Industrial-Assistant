# services.pricing_service

> 源文件 `services/pricing_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

统一定价查询服务 — 市场价格 + 成交量 + 系统成本指数 + adjusted price

数据来源：market.db（market_prices 单张表含价格/成交量/adjusted price）、
reference.db（industry_system_costs 系统成本指数）。
被 UI 财务/运费/精炼/BOM 展开消费（经 bootstrap 容器 get_container().pricing_service）。
注意：评分链路不经过本服务（走 scoring_service 模块级 get_price），改价需两边同步。

## 函数

### `trade_hub_to_system_id`

```python
def trade_hub_to_system_id(hub: str) -> int | None
```

将贸易中心名称映射为太阳系 ID。

定义行：`15`

## 类

### `class PricingService`

统一定价查询

定义行：`20`

#### 方法

##### `__init__`

```python
def __init__(self, db: DatabaseManager) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`
##### `get_price`

```python
def get_price(self, type_id: int, price_type: str, hub: str | None=None) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`27`
##### `get_volume`

```python
def get_volume(self, type_id: int, vol_type: str='total', hub: str | None=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`30`
##### `get_system_cost_index`

```python
def get_system_cost_index(self, system_id: int | None, activity: str='manufacturing', hub: str='Jita') -> float
```

获取系统成本指数。system_id=None 时从 hub 名称推断，查无/未知统一用默认 SCI。

定义行：`33`
##### `get_adjusted_price`

```python
def get_adjusted_price(self, type_id: int) -> float | None
```

获取 ESI adjusted price（EIV 计算用）

定义行：`48`

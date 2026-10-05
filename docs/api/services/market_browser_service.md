# services.market_browser_service

> 源文件 `services/market_browser_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

全物品市场浏览器数据访问 — 供 UI Worker 调用的只读查询。

## 函数

### `_rows_to_dicts`

```python
def _rows_to_dicts(rows) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`19`

### `fetch_market_tree`

```python
def fetch_market_tree() -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`41`

### `fetch_items`

```python
def fetch_items(ids: list[int] | None, rid: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`48`

### `search_items`

```python
def search_items(query: str, rid: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`

### `_spread_row`

```python
def _spread_row(row) -> dict
```

把 SQL 行算成排行行。**体积 ≤ 0 时每方利润为 None，不做除零。**

定义行：`112`

### `fetch_cross_region_spread`

```python
def fetch_cross_region_spread(region_a: int, region_b: int, side_a: str='sell', side_b: str='buy', group_ids: list[int] | None=None) -> list[dict]
```

A → B 全品类价差排行。

定义行：`139`

### `fetch_hub_fetch_time`

```python
def fetch_hub_fetch_time(region_ids: list[int]) -> dict[int, str]
```

各贸易中心最新价格的抓取时间 → `&#123;region_id: "YYYY-MM-DD HH:MM:SS"&#125;`。

定义行：`168`

### `_day_span`

```python
def _day_span(d0: str, d1: str) -> int
```

两个 `YYYY-MM-DD` 之间的天数差。

定义行：`186`

### `order_change_per_day`

```python
def order_change_per_day(first_volume: int | None, last_volume: int | None, first_date: str | None, last_date: str | None, snapshots: int) -> float | None
```

窗口内挂单量的**日均净变化**。

定义行：`191`

### `fetch_hub_order_change`

```python
def fetch_hub_order_change(region_id: int, days: int=7) -> dict[int, dict]
```

目的贸易中心 B 侧卖单挂单量的近日变化 → `&#123;type_id: &#123;"per_day": …, "days": …&#125;&#125;`。

定义行：`234`

# ui_pyside6.workers.trade_workers

> 源文件 `ui_pyside6/workers/trade_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

贸易页面 — 后台 Worker 线程

## 类

### `class CrossRegionPriceWorker`（继承 `QThread`）

获取物品在四大贸易中心的价格

定义行：`10`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, db, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`15`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`

### `class TradeScoreWorker`（继承 `BaseScoreWorker`）

单项贸易评分 — 继承 BaseScoreWorker

定义行：`43`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, buy_hub: str='Jita', sell_hub: str='Jita', buy_price_type: str='buy', sell_price_type: str='sell', quantity: int=1, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `_compute`

```python
def _compute(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`63`

### `class TransportWorker`（继承 `BaseScoreWorker`）

跨区域运输利润计算 — 继承 BaseScoreWorker

定义行：`79`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, buy_hub: str, sell_hub: str, buy_price_type: str, sell_price_type: str, quantity: int, distance_jumps: int, use_public_freight: bool=True, char_config: dict | None=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`82`
##### `_compute`

```python
def _compute(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`104`

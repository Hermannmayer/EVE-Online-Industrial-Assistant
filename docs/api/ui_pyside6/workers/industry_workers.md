# ui_pyside6.workers.industry_workers

> 源文件 `ui_pyside6/workers/industry_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业制造 — 后台 Worker 线程

## 类

### `class SearchWorker`（继承 `QThread`）

搜索可制造物品

定义行：`11`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, db, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`16`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`21`

### `class ScoreWorker`（继承 `BaseScoreWorker`）

单项制造评分 — 继承 BaseScoreWorker

定义行：`39`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, bp_me: int, bp_te: int, mat_hub: str, sell_hub: str, tax: float, mat_price_type: str='sell', runs: int=1, parent=None, char_name: str | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`42`
##### `_compute`

```python
def _compute(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`64`

### `class BatchPlanCalcWorker`（继承 `BaseBatchScoreWorker`）

后台批量重算所有生产计划的利润/评分

定义行：`82`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict], char_config: dict, parent=None, char_name: str | None=None, mat_hub: str='Jita', mat_price_type: str='sell', prod_hub: str='Jita', prod_price_type: str='sell')
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`89`
##### `_resolve_char_config`

```python
def _resolve_char_config(self, plan_char_name: str) -> dict
```

按计划角色名解析配置，带缓存

定义行：`109`
##### `_calc_item`

```python
def _calc_item(self, item) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`119`
##### `_calc_personal_margin`

```python
def _calc_personal_margin(self, plan: dict, result: dict) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`153`
##### `_get_inventory_cost_map`

```python
def _get_inventory_cost_map(self) -> dict[int, tuple[int, float]]
```

批量重算期间库存快照只取一次（避免每计划重复聚合查询）

定义行：`170`
##### `run`

```python
def run(self)
```

BatchPlanCalcWorker 的 run 覆盖：直接遍历 _items 生成结果列表

定义行：`178`

### `class RankWorker`（继承 `QThread`）

批量评分所有可制造物品

定义行：`188`

#### 方法

##### `__init__`

```python
def __init__(self, mat_hub: str, sell_hub: str, mat_price_type: str, bp_me: int, bp_te: int, tax: float, db, parent=None, top_n: int | None=None, char_name: str | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`195`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`219`

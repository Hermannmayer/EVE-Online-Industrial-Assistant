# ui_qml.workers.industry_workers

> 源文件 `ui_qml/workers/industry_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业制造 — 后台 Worker 线程

## 类

### `class SearchWorker`（继承 `QThread`）

搜索可制造物品

定义行：`21`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, db, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`26`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`31`

### `class ScoreWorker`（继承 `BaseScoreWorker`）

单项制造评分 — 继承 BaseScoreWorker

定义行：`37`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, bp_me: int, bp_te: int, mat_hub: str, sell_hub: str, tax: float, mat_price_type: str='sell', runs: int=1, parent=None, char_name: str | None=None, system_id: int | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`40`
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

定义行：`83`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict], char_config: dict, parent=None, char_name: str | None=None, mat_hub: str='Jita', mat_price_type: str='sell', prod_hub: str='Jita', prod_price_type: str='sell', mat_mult: float=1.0, prod_mult: float=1.0)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`90`
##### `_resolve_char_config`

```python
def _resolve_char_config(self, plan_char_name: str) -> dict
```

按计划角色名解析配置，带缓存

定义行：`115`
##### `_calc_base`

```python
def _calc_base(self, item) -> dict
```

单计划基准指标（calculate_plan_metrics），异常返回空 dict。

定义行：`125`
##### `_subitem_output_qty`

```python
def _subitem_output_qty(self, mother: dict, base_results: dict) -> dict[int, int]
```

同组更深子项产线的**实际产出量** `&#123;子项 plan_id: runs × parallels × 单轮产出&#125;`。

定义行：`152`
##### `_apply_mother_subitem_cost`

```python
def _apply_mother_subitem_cost(self, item, result, base_results) -> dict[int, SubitemCost]
```

拆解母项的自制子项制造价 → cost_overrides（**只供个人利润率使用**）。

定义行：`193`
##### `_calc_personal_margin`

```python
def _calc_personal_margin(self, plan: dict, result: dict, cost_overrides: dict[int, SubitemCost] | None=None) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`221`
##### `_get_inventory_cost_map`

```python
def _get_inventory_cost_map(self) -> dict[int, tuple[int, float]]
```

批量重算期间库存快照只取一次（避免每计划重复聚合查询）

定义行：`247`
##### `run`

```python
def run(self)
```

两遍计算：先算所有计划基准指标，再按子项制造价算拆解母项的**个人利润率**。

定义行：`255`

### `class RankWorker`（继承 `QThread`）

批量评分所有可制造物品

定义行：`335`

#### 方法

##### `__init__`

```python
def __init__(self, mat_hub: str, sell_hub: str, mat_price_type: str, bp_me: int, bp_te: int, tax: float, db, parent=None, top_n: int | None=None, char_name: str | None=None, system_id: int | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`342`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`368`

### `class ProcurementSummaryWorker`（继承 `QThread`）

后台聚合「备料中」计划的待采购金额/体积（统计条模式，按计划机库扣库存）

定义行：`425`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict], *, default_mat_hangar_id: int | None=None, region_id: int=10000002, price_type: str='sell', price_mult: float=1.0, self_made: set[int] | None=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`430`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`452`

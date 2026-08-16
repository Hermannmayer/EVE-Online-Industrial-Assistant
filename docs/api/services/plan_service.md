# services.plan_service

> 源文件 `services/plan_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划共享落库 — 统一「加入制造规划」的检查/落库/重算。

## 函数

### `calculate_plan_metrics`

```python
def calculate_plan_metrics(plan_input: dict, *, char_name: str='', mat_price_type: str='buy', prod_price_type: str='sell') -> dict
```

用统一方法计算派生指标（profit/margin/score/iskph/material_cost/calculated_time/daily_output）。

定义行：`13`

### `insert_plan`

```python
def insert_plan(type_id: int, product_name: str, data: dict, *, mat_hub: str='Jita', sell_hub: str='Jita', facility: str='', solar_system_id: int | None=None, mat_hangar_id: int | None=None, deposit_hangar_id: int | None=None, metrics: dict | None=None) -> int
```

INSERT 一条 pending 制造计划（24 列，含派生指标），返回 plan_id。

定义行：`35`

### `insert_plans_batch`

```python
def insert_plans_batch(rows: list[dict]) -> list[int]
```

批量 INSERT 多条 pending 制造计划（一次连接/事务），返回 plan_id 列表。

定义行：`87`

### `datetime_now_str`

```python
def datetime_now_str() -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`136`

### `enrich_plan_hangar_names`

```python
def enrich_plan_hangar_names(rows: list[dict], hangar_names: dict[int, str]) -> list[dict]
```

为计划行补派生显示字段（内存，不落库）。

定义行：`142`

### `load_plans`

```python
def load_plans(filter_key: str) -> list[dict]
```

加载生产计划列表，并补全蓝图可用标记/类别/机库名称。

定义行：`157`

### `collect_refresh_type_ids`

```python
def collect_refresh_type_ids() -> tuple[set[int], int]
```

收集工业页定向刷新所需的 type_id 集合，并返回其中 5 分钟内已缓存的条数。

定义行：`206`

### `save_price_snapshots`

```python
def save_price_snapshots() -> int
```

为活跃计划及其物料保存当前 Jita 价格快照，返回保存条数。

定义行：`244`

### `load_active_plans_for_procurement`

```python
def load_active_plans_for_procurement() -> list[dict]
```

加载采购对话框所需的活跃计划列表。

定义行：`281`

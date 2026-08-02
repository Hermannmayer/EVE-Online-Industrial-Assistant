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

INSERT 一条 pending 制造计划（23 列，含派生指标），返回 plan_id。

定义行：`35`

### `insert_plans_batch`

```python
def insert_plans_batch(rows: list[dict]) -> list[int]
```

批量 INSERT 多条 pending 制造计划（一次连接/事务），返回 plan_id 列表。

定义行：`86`

### `datetime_now_str`

```python
def datetime_now_str() -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`134`

# services.plan_metrics

> 源文件 `services/plan_metrics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

计划指标计算 — 个人利润率 / 拆解母项成本调整（纯函数，无 DB/Qt 依赖）。

## 函数

### `calculate_personal_margin`

```python
def calculate_personal_margin(result: dict, inv_map: dict[int, tuple[int, float]], runs: int=1, parallels: int=1, cost_overrides: dict[int, float] | None=None) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`12`

### `child_manufacturing_cost`

```python
def child_manufacturing_cost(plan: dict, metrics: dict) -> float
```

一条子项产线的总制造价 = 材料成本 + 制造作业费（安装费）。

定义行：`81`

### `mother_subitem_cost_map`

```python
def mother_subitem_cost_map(base_results: dict[int, tuple[dict, dict]], mother: dict) -> dict[int, float]
```

母项同组更深子项的自制成本映射 &#123;子项 product_type_id: 制造价合计&#125;。

定义行：`99`

### `adjust_mother_metrics`

```python
def adjust_mother_metrics(metrics: dict, sub_cost_map: dict[int, float], total_mult: int) -> tuple[float, float, float, dict[int, float]]
```

把拆解母项的自制子项按其制造价计入成本，其余材料仍按市场价。

定义行：`124`

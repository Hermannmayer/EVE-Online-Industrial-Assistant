# services.plan_metrics

> 源文件 `services/plan_metrics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

计划指标计算 — 个人利润率 / 拆解母项成本调整 / 科研作业成本（纯函数，无 DB/Qt 依赖）。

从 scoring_service.ScoringService 中抽出的纯算法：这些函数只做数值计算，
输入全部显式传入（result dict + 库存成本映射 + 流程数），不触碰数据库/容器，
便于脱离 SQLite/Qt 单测。ScoringService 保留 thin delegate 向后兼容。

科研作业成本（拷贝/发明/研究）与制造共用 `domain.formulas` 的 EIV / 安装费 /
材料量公式，区别只在「作业次数」的口径：制造按 runs×parallels，科研按作业次数。

## 函数

### `calculate_personal_margin`

```python
def calculate_personal_margin(result: dict, inv_map: dict[int, tuple[int, float]], runs: int=1, parallels: int=1, cost_overrides: dict[int, float] | None=None) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`27`

### `child_manufacturing_cost`

```python
def child_manufacturing_cost(plan: dict, metrics: dict) -> float
```

一条子项产线的总制造价 = 材料成本 + 制造作业费（安装费）。

定义行：`96`

### `mother_subitem_cost_map`

```python
def mother_subitem_cost_map(base_results: dict[int, tuple[dict, dict]], mother: dict) -> dict[int, float]
```

母项同组更深子项的自制成本映射 &#123;子项 product_type_id: 制造价合计&#125;。

定义行：`114`

### `adjust_mother_metrics`

```python
def adjust_mother_metrics(metrics: dict, sub_cost_map: dict[int, float], total_mult: int) -> tuple[float, float, float, dict[int, float]]
```

把拆解母项的自制子项按其制造价计入成本，其余材料仍按市场价。

定义行：`139`

### `job_batch_materials`

```python
def job_batch_materials(materials: list[tuple[int, int]], job_count: int, *, me_level: int=0) -> list[tuple[int, int]]
```

一次科研作业批次的材料总量 [(type_id, qty)]。

定义行：`186`

### `material_cost_of`

```python
def material_cost_of(mats: list[tuple[int, int]], prices: dict[int, float], extra: list[tuple[int, float]] | None=None) -> float
```

材料总价 = Σ(基础量 × 单价) + extra([(type_id, qty), ...] 小数量的附加项)。

定义行：`202`

### `_installation_fee`

```python
def _installation_fee(eiv_materials: list[tuple[int, int]], prices: dict[int, float], sci: float, *, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0, scc: float=DEFAULT_SCC_SURCHARGE) -> float
```

按 EIV（材料基础量 × adjusted_price）算安装费。

定义行：`219`

### `invention_plan_cost`

```python
def invention_plan_cost(*, base_probability: float, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, science_skill_1: int=0, science_skill_2: int=0, encryption_skill: int=0, decryptor: Decryptor | None=None, base_runs: int=10, output_runs_needed: int=1, input_bpc_cost_per_run: float=0.0, success_rate_override: float | None=None, actual_output_runs: int | None=None, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

发明作业成本（期望值口径）。

定义行：`238`

### `copying_plan_cost`

```python
def copying_plan_cost(*, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, total_copy_runs: int, copies: int=1, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

拷贝作业成本。材料与时长按**总授权流程数**计，无概率项。

定义行：`335`

### `research_plan_cost`

```python
def research_plan_cost(*, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, target_level: int=1, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

ME/TE 研究作业成本。

定义行：`370`

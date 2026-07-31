# services.manufacturing_calculator

> 源文件 `services/manufacturing_calculator.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

制造计算器 — 所有制造相关公式的唯一存放地。

## 函数

### `_waste_mult`

```python
def _waste_mult(wastefactor: int, me_level: int) -> float
```

保留兼容，新公式已不使用 wastefactor。

定义行：`51`

### `calc_waste_factor`

```python
def calc_waste_factor(wastefactor: int, me_level: int) -> float
```

计算材料减成倍率（相对 SDE quantity）。

定义行：`58`

### `calc_material_per_run`

```python
def calc_material_per_run(db_qty: int, wastefactor: int=10, me_level: int=0, structure_mat_saving: float=1.0) -> int
```

计算每轮次制造所需材料数量。

定义行：`69`

### `calc_material_for_runs`

```python
def calc_material_for_runs(db_qty: int, wastefactor: int=10, me_level: int=0, runs: int=1, structure_mat_saving: float=1.0) -> int
```

计算多轮次制造所需材料总量。

定义行：`88`

### `calc_eiv`

```python
def calc_eiv(materials: list[tuple[int, float]]) -> float
```

计算 Estimated Item Value (EIV)。

定义行：`112`

### `calc_job_cost_fees`

```python
def calc_job_cost_fees(eiv: float, sci: float, structure_mult: float=1.0, facility_tax: float=FACILITY_TAX_NPC, scc: float=SCC_SURCHARGE, alpha_tax: float=0.0) -> dict[str, float]
```

计算制造安装费（加法结构）。

定义行：`130`

### `calc_production_time`

```python
def calc_production_time(base_time: int, industry_skill: int=5, adv_industry_skill: int=5, te_level: int=0, structure_time_mod: float=1.0) -> float
```

计算实际制造时间（秒）。

定义行：`178`

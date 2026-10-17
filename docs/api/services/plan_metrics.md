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

### `parse_subitem_snapshot`

```python
def parse_subitem_snapshot(raw: str | None) -> dict[int, SubitemCost]
```

母项 `subitem_cost_snapshot` 列 → ``&#123;子项 type_id: SubitemCost&#125;``。

定义行：`60`

### `merge_subitem_snapshot`

```python
def merge_subitem_snapshot(raw: str | None, entries: dict[int, dict]) -> str
```

既有 snapshot + 新条目 → 新 JSON 串（保留已有值，同 type_id 用新值覆盖）。

定义行：`99`

### `subitem_snapshot_entry`

```python
def subitem_snapshot_entry(plan: dict, metrics: dict, *, output_qty: int | float | None=None) -> tuple[int, dict] | None
```

子项计划 + 评分结果 → `(product_type_id, snapshot 条目)`；无可固化成本 → None。

定义行：`127`

### `_cost_for_need`

```python
def _cost_for_need(need: float, unit_price: float, stock_qty: float, stock_cost: float) -> float
```

一批料的个人口径成本：库存够就全按库存成本，不够则「库存部分 + 缺口按市价」。

定义行：`149`

### `calculate_personal_margin`

```python
def calculate_personal_margin(result: dict, inv_map: dict[int, tuple[int, float]], runs: int=1, parallels: int=1, cost_overrides: dict[int, SubitemCost] | None=None) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`163`

### `child_manufacturing_cost`

```python
def child_manufacturing_cost(plan: dict, metrics: dict) -> float
```

一条子项产线的总制造价 = 材料成本 + 制造作业费（安装费）。

定义行：`237`

### `mother_subitem_cost_map`

```python
def mother_subitem_cost_map(base_results: dict[int, tuple[dict, dict]], mother: dict, *, output_qty_by_plan: dict[int, int] | None=None) -> dict[int, SubitemCost]
```

母项同组更深子项的自制成本映射 &#123;子项 product_type_id: `SubitemCost`&#125;。

定义行：`267`

### `adjust_mother_metrics`

```python
def adjust_mother_metrics(metrics: dict, sub_cost_map: dict[int, SubitemCost], total_mult: int) -> tuple[float, float, float, dict[int, SubitemCost]]
```

把拆解母项的自制子项按其制造价计入成本，其余材料仍按市场价。

定义行：`327`

### `job_batch_materials`

```python
def job_batch_materials(materials: list[tuple[int, int]], job_count: int, *, me_level: int=0) -> list[tuple[int, int]]
```

一次科研作业批次的材料总量 [(type_id, qty)]。

定义行：`389`

### `material_cost_of`

```python
def material_cost_of(mats: list[tuple[int, int]], prices: dict[int, float], extra: list[tuple[int, float]] | None=None) -> float
```

材料总价 = Σ(基础量 × 单价) + extra([(type_id, qty), ...] 小数量的附加项)。

定义行：`406`

### `_installation_fee`

```python
def _installation_fee(eiv_materials: list[tuple[int, int]], prices: dict[int, float], sci: float, *, job_value: float | None=None, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0, scc: float=DEFAULT_SCC_SURCHARGE) -> float
```

按 EIV（材料基础量 × adjusted_price）算安装费。

定义行：`423`

### `invention_plan_cost`

```python
def invention_plan_cost(*, base_probability: float, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, science_skill_1: int=0, science_skill_2: int=0, encryption_skill: int=0, decryptor: Decryptor | None=None, base_runs: int=10, output_runs_needed: int=1, attempts_override: int | None=None, input_bpc_cost_per_run: float=0.0, success_rate_override: float | None=None, actual_output_runs: int | None=None, job_value: float | None=None, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

发明作业成本（期望值口径）。

定义行：`451`

### `copying_plan_cost`

```python
def copying_plan_cost(*, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, total_copy_runs: int, copies: int=1, job_value: float | None=None, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

拷贝作业成本。

定义行：`567`

### `research_plan_cost`

```python
def research_plan_cost(*, materials: list[tuple[int, int]], prices: dict[int, float], sci: float, target_level: int=1, job_value: float | None=None, structure_mult: float=1.0, facility_tax: float=DEFAULT_FACILITY_TAX, alpha_tax: float=0.0) -> dict
```

ME/TE 研究作业成本。

定义行：`615`

## 类

### `class SubitemCost`

拆解子项的自制成本口径：**单件制造价** + 子项产线**自己产出的数量**。

为什么不是「整条产线总价」：子项产线排的是**净需求**（`services/plan_rebuild.plan_net_runs`
会先扣掉母项机库里已有的成品库存），所以「产出量」通常 **小于** 母项的材料需求 ——
实测 紫外晶体 XL（计划 385）需求 1368、产出 1310（差的 58 件在库存里）。

旧口径只传整线总价、消费方一律当成「覆盖母项全部需求」，等于把那 58 件当 0 成本：
既让「单价」偏低（701,615,501.12 ÷ 1368 = 512,876.83，而子项真实单件 535,584.35），
又让个人口径的总成本偏低。这里把两个数都带出来，由消费方按
「`min(需求, 产出量)` 件按单件制造价 + 缺口按库存/市价」结算。

`covered_qty=None` = 调用方拿不到产出量（老调用点）→ 消费方退回旧口径
（等价于产出量 = 需求）。

定义行：`32`

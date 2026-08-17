# services.plan_execution

> 源文件 `services/plan_execution.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划执行 — 倒计时 / 材料校验扣减 / 蓝图绑定占用消耗 / 完成入库

## 函数

### `_now_str`

```python
def _now_str() -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`

### `remaining_seconds`

```python
def remaining_seconds(plan: dict, *, now: datetime | None=None) -> int | None
```

倒计时剩余秒数。非进行中 / 无 started_at / 无时长 → None；已超时返回负值。

定义行：`27`

### `expire_overdue_plans`

```python
def expire_overdue_plans(db=None) -> int
```

把已超时的进行中计划置为 ready（重启补算）。返回受影响行数。

定义行：`48`

### `material_requirements`

```python
def material_requirements(plan: dict) -> list[dict]
```

计算计划总材料需求 [&#123;type_id, name, need&#125;]。

定义行：`86`

### `check_materials`

```python
def check_materials(plan: dict, mat_hangar_id: int | None) -> list[dict]
```

对照材料机库库存，返回 [&#123;type_id, name, need, owned, missing&#125;]。

定义行：`119`

### `get_plans_for_mat_hangar`

```python
def get_plans_for_mat_hangar(mat_hangar_id: int) -> list[dict]
```

列出以该机库为材料机库的活跃计划（status NOT IN ('completed','done')）。

定义行：`137`

### `aggregate_material_requirements`

```python
def aggregate_material_requirements(plans: list[dict], mat_hangar_id: int) -> list[dict]
```

跨计划聚合材料需求：按 type_id 累加 need，对照材料机库库存算缺口。

定义行：`151`

### `deduct_materials`

```python
def deduct_materials(plan: dict, mat_hangar_id: int) -> list[dict]
```

从材料机库逐个扣减，返回 [&#123;type_id, name, need, owned, deducted, missing&#125;]。

定义行：`182`

### `start_plan`

```python
def start_plan(plan: dict, *, mat_hangar_id: int | None, allow_short: bool=False, auto_bind: bool=True, char_name: str | None=None, facility: str | None=None) -> dict
```

启动一条计划：校验 → 扣减材料 → 绑定蓝图 → 写 started_at/in_progress。

定义行：`200`

### `start_plan_batch`

```python
def start_plan_batch(plans: list[dict], *, mat_hangar_id: int | None, allow_short: bool=False, char_name: str | None=None, facility: str | None=None) -> dict
```

批量启动（产线小助手/组）。逐条独立，单条失败不中断其余。

定义行：`335`

### `output_per_run`

```python
def output_per_run(product_type_id: int) -> int
```

蓝图单流程产出量（查 blueprint_products，缺省 1）。

定义行：`363`

### `complete_plan`

```python
def complete_plan(plan: dict, *, conn=None) -> dict
```

ready/pending/in_progress → completed：入库成品 + 消耗绑定 BPC。

定义行：`380`

### `cancel_plan`

```python
def cancel_plan(plan: dict) -> dict
```

撤销启动：in_progress → pending，并返还已扣减材料到材料机库。

定义行：`485`

### `reset_plan_for_reuse`

```python
def reset_plan_for_reuse(plan_id: int) -> dict
```

设为待生产：仅 completed 计划复用（不返还材料——材料已变为成品）。

定义行：`579`

### `bind_blueprint`

```python
def bind_blueprint(plan_id: int, blueprint_id: int) -> bool
```

把一张库存蓝图绑定到计划（单条产线）。BPC 已被其他活跃计划占用时拒绝；BPO 可共享。

定义行：`609`

### `bind_blueprints`

```python
def bind_blueprints(plan_id: int, blueprint_ids: list[int]) -> bool
```

全量替换绑定：一条产线一张蓝图。

定义行：`614`

### `bind_blueprints_many`

```python
def bind_blueprints_many(bindings: list[tuple[int, list[int]]]) -> bool
```

批量全量替换绑定多计划（一次连接/事务）。

定义行：`665`

### `get_plan_binding_state`

```python
def get_plan_binding_state(plan_id: int) -> dict
```

返回计划蓝图绑定状态：bound(已绑张数清单)、need(需要的产线条数=parallels)、runs(每条产线流程)。

定义行：`720`

### `_bp_available_runs`

```python
def _bp_available_runs(conn, bp_id: int) -> int | float
```

连接内查 BPC 可用流程 = quantity×runs；BPO 返回大数（视为无限）。

定义行：`746`

### `_binding_shortfall`

```python
def _binding_shortfall(conn, bound_ids: list[int], parallels: int, runs: int) -> str | None
```

校验绑定是否满足一条产线一张蓝图且每张流程≥runs；不足返回原因文本，满足返回 None。

定义行：`756`

### `get_plan_blueprints`

```python
def get_plan_blueprints(plan_id: int) -> list[int]
```

返回计划绑定的库存蓝图 id 列表（关联表；无关联表时回退旧单值列）。

定义行：`766`

### `_clear_plan_bindings`

```python
def _clear_plan_bindings(conn, plan_id: int) -> None
```

清空计划的多蓝图绑定关联行（兼容旧库无关联表）。

定义行：`781`

### `release_blueprint`

```python
def release_blueprint(plan_id: int) -> bool
```

计划取消/删除/回退时释放占用（清空关联表与旧单值列）。

定义行：`789`

### `get_assigned_blueprint_id`

```python
def get_assigned_blueprint_id(plan_id: int) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`803`

### `get_occupied_blueprint_ids`

```python
def get_occupied_blueprint_ids(db=None, *, exclude_plan_id: int | None=None) -> set[int]
```

返回被活跃计划（非 completed/done）占用的 user_blueprints.id 集合。

定义行：`809`

### `find_available_blueprints`

```python
def find_available_blueprints(conn, blueprint_type_id: int) -> list[dict]
```

按蓝图类型列出库存蓝图（含占用标注/可用流程）。

定义行：`850`

### `consume_bpc_runs`

```python
def consume_bpc_runs(conn, bp_id: int, runs_used: int) -> dict
```

完成时消耗 BPC 剩余流程；BPO 无操作。

定义行：`888`

### `_split_bpc_consumption`

```python
def _split_bpc_consumption(quantity: int, runs: int, used: int) -> tuple[int, int | None]
```

纯函数：消耗 used 流程后返回应保留的 (数量, 每张剩余流程)。

定义行：`923`

### `_container`

```python
def _container()
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`949`

### `_occupied_ids`

```python
def _occupied_ids(conn, *, exclude_plan_id: int | None=None) -> set[int]
```

连接内查询占用蓝图 id 集合（兼容关联表与旧单值列）。

定义行：`955`

### `_auto_bind_blueprint`

```python
def _auto_bind_blueprint(plan: dict) -> int | None
```

自动选最优库存蓝图：BPO 优先 → ME 最高的够用 BPC。返回 user_blueprints.id 或 None。

定义行：`990`

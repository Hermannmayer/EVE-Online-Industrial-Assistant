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

定义行：`83`

### `check_materials`

```python
def check_materials(plan: dict, mat_hangar_id: int | None) -> list[dict]
```

对照材料机库库存，返回 [&#123;type_id, name, need, owned, missing&#125;]。

定义行：`116`

### `deduct_materials`

```python
def deduct_materials(plan: dict, mat_hangar_id: int) -> list[dict]
```

从材料机库逐个扣减，返回 [&#123;type_id, name, need, owned, deducted, missing&#125;]。

定义行：`134`

### `start_plan`

```python
def start_plan(plan: dict, *, mat_hangar_id: int | None, allow_short: bool=False, auto_bind: bool=True, char_name: str | None=None, facility: str | None=None) -> dict
```

启动一条计划：校验 → 扣减材料 → 绑定蓝图 → 写 started_at/in_progress。

定义行：`152`

### `start_plan_batch`

```python
def start_plan_batch(plans: list[dict], *, mat_hangar_id: int | None, allow_short: bool=False, char_name: str | None=None, facility: str | None=None) -> dict
```

批量启动（产线小助手/组）。逐条独立，单条失败不中断其余。

定义行：`236`

### `complete_plan`

```python
def complete_plan(plan: dict, *, conn=None) -> dict
```

ready/pending/in_progress → completed：入库成品 + 消耗绑定 BPC。

定义行：`264`

### `cancel_plan`

```python
def cancel_plan(plan: dict) -> dict
```

撤销启动：in_progress → pending，并返还已扣减材料到材料机库。

定义行：`336`

### `bind_blueprint`

```python
def bind_blueprint(plan_id: int, blueprint_id: int) -> bool
```

把库存蓝图绑定到计划。BPC 已被其他活跃计划占用时拒绝；BPO 可共享。

定义行：`398`

### `release_blueprint`

```python
def release_blueprint(plan_id: int) -> bool
```

计划取消/删除/回退时释放占用（清空 assigned_blueprint_id）。

定义行：`419`

### `get_assigned_blueprint_id`

```python
def get_assigned_blueprint_id(plan_id: int) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`428`

### `get_occupied_blueprint_ids`

```python
def get_occupied_blueprint_ids(db=None) -> set[int]
```

返回被活跃计划（非 completed/done）占用的 user_blueprints.id 集合。

定义行：`434`

### `find_available_blueprints`

```python
def find_available_blueprints(conn, blueprint_type_id: int) -> list[dict]
```

按蓝图类型列出库存蓝图（含占用标注/可用流程）。

定义行：`445`

### `consume_bpc_runs`

```python
def consume_bpc_runs(conn, bp_id: int, runs_used: int) -> dict
```

完成时消耗 BPC 剩余流程；BPO 无操作。

定义行：`483`

### `_split_bpc_consumption`

```python
def _split_bpc_consumption(quantity: int, runs: int, used: int) -> tuple[int, int | None]
```

纯函数：消耗 used 流程后返回应保留的 (数量, 每张剩余流程)。

定义行：`505`

### `_container`

```python
def _container()
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`531`

### `_occupied_ids`

```python
def _occupied_ids(conn) -> set[int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`537`

### `_auto_bind_blueprint`

```python
def _auto_bind_blueprint(plan: dict) -> int | None
```

自动选最优库存蓝图：BPO 优先 → ME 最高的够用 BPC。返回 user_blueprints.id 或 None。

定义行：`545`

# services.plan_decompose

> 源文件 `services/plan_decompose.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划递归拆解 — 把母项拆成子项产线（sub_level 逐级 +1）。

## 函数

### `best_inventory_blueprint`

```python
def best_inventory_blueprint(conn: Connection, blueprint_type_id: int) -> dict | None
```

从 user_blueprints 挑 ME 最优的库存蓝图 → &#123;me_level, te_level&#125;；无则 None。

定义行：`22`

### `decompose_plan`

```python
def decompose_plan(plan: dict, *, mat_hangar_id: int | None=None) -> list[dict]
```

递归拆解母项 → 子项产线行列表（不含母项自身）。

定义行：`37`

### `parent_needs`

```python
def parent_needs(conn: Connection, group_plans: list[dict]) -> dict[int, int]
```

组内全部母项（sub_level=0）对每个直接组件的总需求 &#123;type_id: need&#125;。

定义行：`63`

### `is_leaf_plan`

```python
def is_leaf_plan(plan: dict, all_plans: list[dict]) -> bool
```

该计划是否为叶子产线（组内无更深子项）。

定义行：`82`

### `collect_cascade_delete_ids`

```python
def collect_cascade_delete_ids(plans: list[dict], selected_ids: set[int]) -> set[int]
```

删除指定计划时级联删除同组更深子项（含传递层级）。

定义行：`99`

### `collect_group_members`

```python
def collect_group_members(all_plans: list[dict], selected: list[dict]) -> tuple[list[dict], list[dict]]
```

跨选中行聚合相关组的母项与子项（按 plan id 去重）→ (parents, children)。

定义行：`133`

### `_decompose`

```python
def _decompose(conn: Connection, type_id: int, needed_qty: float, depth: int, stock: dict[int, int], seen: set[int]) -> tuple[list[dict], int]
```

递归展开一层。返回 (子项产线行, 本层可被库存覆盖的产出量)。

定义行：`171`

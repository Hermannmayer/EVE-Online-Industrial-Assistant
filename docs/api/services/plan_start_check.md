# services.plan_start_check

> 源文件 `services/plan_start_check.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

产线启动条件判定 — 纯逻辑，无 DB/Qt。

供产线启动小助手判断"该行是否可启动 / 为何不可启动"：
  缺料、无材料机库、无可用蓝图、母项有子项未完成 → 按钮留白 + 状态栏原因。
母项（child_level==0）依赖子项产物，子项未完成则母项不可启动。

## 函数

### `_plan_group_id`

```python
def _plan_group_id(plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`22`

### `_plan_level`

```python
def _plan_level(plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`26`

### `is_parent`

```python
def is_parent(plan: dict) -> bool
```

母项：child_level==0 且有组（有子项才可能构成组）。

定义行：`30`

### `children_running`

```python
def children_running(plan: dict, all_plans: list[dict]) -> bool
```

母项同组内有 in_progress/running 子项 → True。子项自身永远 False。

定义行：`35`

### `pending_children_count`

```python
def pending_children_count(plan: dict, all_plans: list[dict]) -> int
```

母项未完成（pending/running/生产中）子项数，供「等待 N 条子项」展示。

定义行：`46`

### `plan_start_block_reason`

```python
def plan_start_block_reason(plan: dict, mat_hangar_id: int | None, all_plans: list[dict], *, shortfall_count: int=0, allow_short: bool=False) -> str | None
```

返回阻止启动的原因文本；None = 可启动。

定义行：`58`

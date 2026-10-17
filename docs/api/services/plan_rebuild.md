# services.plan_rebuild

> 源文件 `services/plan_rebuild.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划子项全量重放 — 把母项拆解从「静态快照」升级为「引用式 + 幂等重放」。

设计：
- 子项需求改为引用式：每个子项行记录被哪些母项引用（source_mother_ids），
  需求（demand）= 所有引用母项按各自当前 runs×parallels×ME 折算的用量之和。
- rebuild_children() 全量重放：读所有活跃母项 → 沿 BOM 全局传播需求 →
  与 DB 现有子项 diff 后单事务落库。天然幂等（输入不变则算集不变，diff 为空），
  自动支持：编辑母项后子项联动、共享组件跨母项合并为一行、删除母项后需求收缩。
- 不依赖 group_number 的唯一性；共享节点挂在首个引用母项的组下（阶段3升级为独立共享区）。

## 函数

### `_is_active`

```python
def _is_active(row: dict) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`33`

### `_is_locked`

```python
def _is_locked(row: dict) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`37`

### `_mother_key`

```python
def _mother_key(row: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`41`

### `_sub_level`

```python
def _sub_level(row: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`45`

### `_group_of`

```python
def _group_of(row: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

### `_parse_sources`

```python
def _parse_sources(row: dict) -> set[int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`53`

### `_in_scope`

```python
def _in_scope(sources: set[int], group_number: int, scope: set[int] | None, scope_groups: set[int]) -> bool
```

这一行是否落在本次写入作用域内（`rebuild_children(mother_ids=...)`）。

定义行：`60`

### `_collect_mothers`

```python
def _collect_mothers(all_rows: list[dict]) -> list[dict]
```

识别母项：sub_level=0 且（旧式 group>0 或被子项 source 引用/自身带 source 的拆解母项）。

定义行：`74`

### `_accumulate`

```python
def _accumulate(conn, nodes: dict[int, dict], first_mother: dict, type_id: int, qty: int, level: int, parent_type_id: int, existing_parallels: dict[int, int]) -> None
```

把 qty 记到 `type_id` 的需求上，并补全节点元数据。**这里不算 runs**。

定义行：`89`

### `plan_net_runs`

```python
def plan_net_runs(demand: int, output_per_run: int, available: int, parallels: int) -> tuple[int, int, int]
```

净需求 → `(并行数, 每条线轮数, 净需求线·轮数)`。**排产口径的唯一真源**。

定义行：`142`

### `_finalize_runs`

```python
def _finalize_runs(node: dict, stocks: dict[int, dict[int, int]]) -> None
```

把本轮收齐的 demand 折算成 runs（**每条产线的流程数**）+ 顺带定并行数，净口径不多造。

定义行：`191`

### `compute_child_forest`

```python
def compute_child_forest(conn, active_mothers: list[dict], stocks: dict[int, dict[int, int]], existing_parallels: dict[int, int]) -> dict[int, dict]
```

全局需求传播 → &#123;type_id: node&#125;。

定义行：`252`

### `rebuild_children`

```python
def rebuild_children(*, create: bool=False, prune: bool=False, mother_ids: set[int] | None=None) -> dict
```

按母项当前需求同步子项（增量，默认不创建/不删除——避免误删子项被自动加回）。

定义行：`337`

### `_resolve_name`

```python
def _resolve_name(type_id: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`533`

### `_field_diff`

```python
def _field_diff(row: dict, fields: dict) -> dict
```

返回 fields 中与本行当前值不同的子集（幂等：值未变则跳过，计 0）。

定义行：`539`

### `_inherited_solar_system`

```python
def _inherited_solar_system(mother: dict) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`553`

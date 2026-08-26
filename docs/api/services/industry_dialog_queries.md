# services.industry_dialog_queries

> 源文件 `services/industry_dialog_queries.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

行业弹窗专用数据查询收敛层。

把原先散落在 ui_pyside6/views/industry/*.py 中的
``get_container().db.connect(...)`` 直接 SQL 收敛到 services 层。

这些函数只接收 DatabaseManager（由 UI 从容器传入），保持同步调用，
不改变原有 UI 线程中的 DB 访问时机。

## 函数

### `get_character_usage`

```python
def get_character_usage(db) -> list[tuple[Any, Any, Any]]
```

按 char_name 统计活跃计划。

定义行：`41`

### `get_output_summary`

```python
def get_output_summary(db) -> list[dict[str, Any]] | None
```

查询所有生产计划并计算产出价值与溢出；无计划时返回 None。

定义行：`55`

### `get_blueprint_requirements`

```python
def get_blueprint_requirements(db) -> dict[str, Any]
```

查询活跃计划、展开蓝图需求并对比库存。

定义行：`86`

### `get_blueprint_picker_data`

```python
def get_blueprint_picker_data(db, product_type_id: int) -> tuple[int | None, list[dict[str, Any]]]
```

查询产品对应的制造蓝图类型及其可用库存蓝图。

定义行：`120`

### `get_child_parallel_data`

```python
def get_child_parallel_data(db, plans: list[dict], sub_plans: list[dict]) -> tuple[dict[int, int], dict[int, int], dict[int, str]]
```

子项并行弹窗初始化数据：母项需求 / 单轮产出 / 格式化时长。

定义行：`134`

### `get_mass_parallel_data`

```python
def get_mass_parallel_data(db, plans: list[dict], sub_plans: list[dict]) -> tuple[dict[int, int], dict[int, int], dict[int, int]]
```

大规模并行弹窗初始化数据：母项需求 / 单轮产出 / 单线总时长秒。

定义行：`155`

### `_child_demand_from_rows`

```python
def _child_demand_from_rows(sub_plans: list[dict], conn, plans: list[dict]) -> dict[int, int]
```

共享子项需求：优先读 v12 引用式 demand 列；老库按母项 parent_needs 推导。

定义行：`173`

### `get_materials_summary`

```python
def get_materials_summary(db) -> dict[str, Any] | None
```

查询活跃计划 BOM、库存与市场价；无活跃计划时返回 None。

定义行：`180`

### `get_max_group_number`

```python
def get_max_group_number(db) -> int
```

返回 production_plans 当前最大 group_number，无记录为 0。

定义行：`209`

### `get_subitem_plans`

```python
def get_subitem_plans(db, group_number: int, deeper_than: int) -> list[dict[str, Any]]
```

查询同组更深子项产线，按 sub_level DESC, id DESC。

定义行：`216`

### `get_item_name`

```python
def get_item_name(db, type_id: int) -> str
```

按旧 UI 语义查询 item 表名称：zh_name → en_name → str(type_id)。

定义行：`226`

### `get_system_name`

```python
def get_system_name(db, solar_system_id: int) -> str
```

查询星系显示名（中文 (英文)）。

定义行：`233`

### `set_plan_deposit_hangar`

```python
def set_plan_deposit_hangar(db, plan_id: int, hangar_id: int | None) -> None
```

更新计划的下线产出机库。

定义行：`241`

### `_query_blueprint_output`

```python
def _query_blueprint_output(conn, product_type_id: int) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`255`

### `_query_blueprint_duration_sec`

```python
def _query_blueprint_duration_sec(conn, blueprint_type_id) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`263`

### `_format_blueprint_duration`

```python
def _format_blueprint_duration(conn, blueprint_type_id) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`271`

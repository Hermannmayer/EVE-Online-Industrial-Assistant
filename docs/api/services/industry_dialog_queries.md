# services.industry_dialog_queries

> 源文件 `services/industry_dialog_queries.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

行业弹窗专用数据查询收敛层。

把原先散落在 ui_pyside6/views/industry/*.py 中的
``get_container().db.connect(...)`` 直接 SQL 收敛到 services 层。

这些函数只接收 DatabaseManager（由 UI 从容器传入），保持同步调用，
不改变原有 UI 线程中的 DB 访问时机。

## 函数

### `get_output_summary`

```python
def get_output_summary(db) -> list[dict[str, Any]] | None
```

查询所有生产计划并计算产出价值与溢出；无计划时返回 None。

定义行：`40`

### `get_blueprint_requirements`

```python
def get_blueprint_requirements(db) -> dict[str, Any]
```

查询活跃计划、展开蓝图需求并对比库存。

定义行：`73`

### `get_blueprint_picker_data`

```python
def get_blueprint_picker_data(db, plan: dict) -> dict[str, Any]
```

「绑定库存蓝图」弹窗的数据：该计划要绑的输入蓝图 + 库存里可选的行。

定义行：`113`

### `get_child_parallel_data`

```python
def get_child_parallel_data(db, plans: list[dict], sub_plans: list[dict]) -> tuple[dict[int, int], dict[int, int], dict[int, str], dict[int, int]]
```

子项并行弹窗初始化数据：母项需求 / 单轮产出 / 格式化时长 / 成品库存。

定义行：`145`

### `get_mass_parallel_data`

```python
def get_mass_parallel_data(db, plans: list[dict], sub_plans: list[dict]) -> tuple[dict[int, int], dict[int, int], dict[int, int], dict[int, int]]
```

大规模并行弹窗初始化数据：母项需求 / 单轮产出 / 单线总时长秒 / 成品库存。

定义行：`168`

### `_child_available_stock`

```python
def _child_available_stock(plans: list[dict], sub_plans: list[dict]) -> dict[int, int]
```

每个子项成品在**首个引用母项的制造机库**里的库存 &#123;product_type_id: 数量&#125;。

定义行：`189`

### `_first_mother_hangar`

```python
def _first_mother_hangar(child: dict, mothers: dict[int, dict], plans: list[dict]) -> int | None
```

子项对应的「首个引用母项」的材料机库 id（取不到返回 None）。

定义行：`217`

### `_child_demand_from_rows`

```python
def _child_demand_from_rows(sub_plans: list[dict], conn, plans: list[dict]) -> dict[int, int]
```

共享子项需求：优先读 v12 引用式 demand 列；老库按母项 parent_needs 推导。

定义行：`237`

### `get_materials_summary`

```python
def get_materials_summary(db) -> dict[str, Any] | None
```

查询活跃计划 BOM、库存与市场价；无活跃计划时返回 None。

定义行：`244`

### `get_max_group_number`

```python
def get_max_group_number(db) -> int
```

返回 production_plans 当前最大 group_number，无记录为 0。

定义行：`273`

### `get_subitem_plans`

```python
def get_subitem_plans(db, group_number: int, deeper_than: int) -> list[dict[str, Any]]
```

查询同组更深子项产线，按 sub_level DESC, id DESC。

定义行：`280`

### `get_item_name`

```python
def get_item_name(db, type_id: int) -> str
```

按旧 UI 语义查询 item 表名称：zh_name → en_name → str(type_id)。

定义行：`290`

### `get_system_name`

```python
def get_system_name(db, solar_system_id: int) -> str
```

查询星系显示名（中文 (英文)）。

定义行：`297`

### `set_plan_deposit_hangar`

```python
def set_plan_deposit_hangar(db, plan_id: int, hangar_id: int | None) -> None
```

更新计划的下线产出机库。

定义行：`305`

### `_query_blueprint_output`

```python
def _query_blueprint_output(conn, product_type_id: int) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`319`

### `_query_blueprint_duration_sec`

```python
def _query_blueprint_duration_sec(conn, blueprint_type_id) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`327`

### `_format_blueprint_duration`

```python
def _format_blueprint_duration(conn, blueprint_type_id) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`335`

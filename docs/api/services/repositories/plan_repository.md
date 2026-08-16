# services.repositories.plan_repository

> 源文件 `services/repositories/plan_repository.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划 CRUD 仓库

## 类

### `class PlanRepository`

生产计划表的增删改查

定义行：`8`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`11`
##### `ensure_table`

```python
def ensure_table(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`98`
##### `get_by_id`

```python
def get_by_id(self, plan_id: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`102`
##### `get_all`

```python
def get_all(self, status: str | None=None) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`107`
##### `find_by_group_product`

```python
def find_by_group_product(self, group_number: int, product_type_id: int) -> int | None
```

按分组号+产品查找已存在的子计划 id。

定义行：`117`
##### `save`

```python
def save(self, plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`126`
##### `_allowed_fields`

```python
def _allowed_fields(fields: dict) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`159`
##### `update`

```python
def update(self, plan_id: int, **fields) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`162`
##### `update_many`

```python
def update_many(self, plan_ids: list[int], **fields) -> int
```

批量更新多条计划的同一组字段（列名来自内部，参数化值）。返回受影响行数。

定义行：`172`
##### `update_batch`

```python
def update_batch(self, rows: list[tuple[int, dict]]) -> int
```

批量异构更新：rows = [(plan_id, &#123;field: value&#125;), ...]，单连接单事务。返回更新行数。

定义行：`184`
##### `insert_child_plan`

```python
def insert_child_plan(self, *, product_type_id: int, product_name: str, blueprint_type_id: int, runs: int, parallels: int, me_level: int, te_level: int, group_number: int, sub_level: int, mat_hangar_id: int | None, solar_system_id: int | None) -> int
```

插入一条拆解子计划（含分组/层级/机库字段）。

定义行：`200`
##### `delete_many`

```python
def delete_many(self, plan_ids: list[int]) -> int
```

批量删除计划（蓝图表关联清理由调用方 release_blueprint 处理）。返回删除行数。

定义行：`240`
##### `delete`

```python
def delete(self, plan_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`249`

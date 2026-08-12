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

定义行：`55`
##### `get_by_id`

```python
def get_by_id(self, plan_id: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`
##### `get_all`

```python
def get_all(self, status: str | None=None) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`64`
##### `save`

```python
def save(self, plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`74`
##### `update`

```python
def update(self, plan_id: int, **fields) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`106`
##### `update_many`

```python
def update_many(self, plan_ids: list[int], **fields) -> int
```

批量更新多条计划的同一组字段（列名来自内部，参数化值）。返回受影响行数。

定义行：`115`
##### `update_batch`

```python
def update_batch(self, rows: list[tuple[int, dict]]) -> int
```

批量异构更新：rows = [(plan_id, &#123;field: value&#125;), ...]，单连接单事务。返回更新行数。

定义行：`126`
##### `delete_many`

```python
def delete_many(self, plan_ids: list[int]) -> int
```

批量删除计划（蓝图表关联清理由调用方 release_blueprint 处理）。返回删除行数。

定义行：`141`
##### `delete`

```python
def delete(self, plan_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`150`

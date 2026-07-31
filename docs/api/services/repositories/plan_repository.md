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

定义行：`37`
##### `get_by_id`

```python
def get_by_id(self, plan_id: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`41`
##### `get_all`

```python
def get_all(self, status: str | None=None) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `save`

```python
def save(self, plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`56`
##### `update`

```python
def update(self, plan_id: int, **fields) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`88`
##### `delete`

```python
def delete(self, plan_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`97`

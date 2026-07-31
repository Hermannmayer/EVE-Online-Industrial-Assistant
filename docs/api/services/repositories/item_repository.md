# services.repositories.item_repository

> 源文件 `services/repositories/item_repository.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品基础数据查询仓库

## 类

### `class ItemRepository`

物品数据只读查询

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
##### `get_name`

```python
def get_name(self, type_id: int, conn: Connection | None=None) -> str
```

获取物品名称：矿物映射优先 → zh_name → en_name → str(type_id)

定义行：`14`
##### `get_volume`

```python
def get_volume(self, type_id: int) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`
##### `get_by_id`

```python
def get_by_id(self, type_id: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`28`
##### `search_by_name`

```python
def search_by_name(self, keyword: str, limit: int=50) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `count`

```python
def count(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

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
##### `get_by_name`

```python
def get_by_name(self, name: str) -> dict | None
```

按中/英文名精确查找单个物品。

定义行：`36`
##### `search_by_name`

```python
def search_by_name(self, keyword: str, limit: int=50) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`47`
##### `get_root_market_categories`

```python
def get_root_market_categories(self) -> list[tuple[int, str]]
```

根级市场分类 [(market_group_id, zh_name), ...]。

定义行：`60`
##### `get_market_descendants`

```python
def get_market_descendants(self, market_group_id: int) -> set[int]
```

递归获取指定市场分类下所有物品 type_id。

定义行：`68`
##### `get_planetary_product_ids`

```python
def get_planetary_product_ids(self) -> set[int]
```

行星开发相关物品 type_id（market_tree 行星/指挥中心分类及其子分类）。

定义行：`85`
##### `count`

```python
def count(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`107`

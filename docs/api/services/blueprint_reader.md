# services.blueprint_reader

> 源文件 `services/blueprint_reader.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图数据访问层 — 统一蓝图查询接口。

替代多处分散的 SELECT FROM blueprint_materials 查询。
依赖 blueprint.db 中的 blueprint_materials 表。

## 函数

### `blueprint_index_sql`

```python
def blueprint_index_sql() -> list[str]
```

蓝图表索引的 CREATE 语句（导入器与 schema 迁移共用这一处定义）。

定义行：`26`

### `get_blueprint_materials`

```python
def get_blueprint_materials(conn: sqlite3.Connection, blueprint_type_id: int, activity: str='manufacturing') -> list[tuple[int, int, int]]
```

获取蓝图所需材料列表。

定义行：`31`

### `get_blueprint_products`

```python
def get_blueprint_products(conn: sqlite3.Connection, product_type_id: int, activity: str='manufacturing') -> tuple[int, int, int] | None
```

根据产品 type_id 查找对应的蓝图信息。

定义行：`58`

## 类

### `class SqliteBlueprintReader`

BlueprintReader 适配 — 基于 sqlite 连接的蓝图查询（实现 domain.bom.BlueprintReader）。

定义行：`91`

#### 方法

##### `__init__`

```python
def __init__(self, conn)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`94`
##### `product`

```python
def product(self, product_type_id: int, activity: str='manufacturing') -> tuple[int, int] | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`97`
##### `materials`

```python
def materials(self, blueprint_type_id: int, activity: str='manufacturing') -> list[tuple[int, int, int]]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`103`

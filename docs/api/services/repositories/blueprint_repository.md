# services.repositories.blueprint_repository

> 源文件 `services/repositories/blueprint_repository.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图数据查询仓库

## 类

### `class BlueprintRepository`

蓝图只读查询

定义行：`6`

#### 方法

##### `__init__`

```python
def __init__(self, db)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`9`
##### `get_blueprint_for_product`

```python
def get_blueprint_for_product(self, product_type_id: int, activity: str='manufacturing') -> tuple | None
```

查找产出指定物品的蓝图 → (blueprint_type_id, output_qty, base_time) or None

定义行：`12`
##### `get_materials`

```python
def get_materials(self, blueprint_type_id: int, activity: str='manufacturing') -> list[tuple]
```

获取蓝图材料 → [(material_type_id, quantity, wastefactor), ...]

定义行：`24`
##### `get_all_product_ids`

```python
def get_all_product_ids(self, activity: str='manufacturing') -> list[int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `get_all_blueprint_product_ids`

```python
def get_all_blueprint_product_ids(self) -> set[int]
```

所有出现在 blueprint_products 中的产出物 type_id。

定义行：`43`
##### `get_t1_manufacturable_product_ids`

```python
def get_t1_manufacturable_product_ids(self) -> set[int]
```

T1 制造产物：有制造蓝图，且该蓝图不是发明产物。

定义行：`49`
##### `get_t2_manufacturable_product_ids`

```python
def get_t2_manufacturable_product_ids(self) -> set[int]
```

T2 发明产物：有制造蓝图，且该蓝图由发明产出。

定义行：`61`
##### `get_faction_manufacturable_product_ids`

```python
def get_faction_manufacturable_product_ids(self) -> set[int]
```

势力蓝图制造产物：制造产物名称匹配常见势力关键词。

定义行：`73`
##### `get_manufacturable_market_tree`

```python
def get_manufacturable_market_tree(self) -> list[dict]
```

可制造物品关联的市场分类树（id/parent/name 字典列表）。

定义行：`86`
##### `get_manufacturing_materials`

```python
def get_manufacturing_materials(self, product_type_id: int) -> tuple[int, list[tuple[int, int, str, str, float | None]]] | None
```

查询产品制造材料及最新卖价。

定义行：`110`

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
##### `get_bp_detail`

```python
def get_bp_detail(self, type_id: int) -> dict | None
```

获取蓝图详情（跨库 JOIN ref + bp）

定义行：`36`
##### `get_all_product_ids`

```python
def get_all_product_ids(self, activity: str='manufacturing') -> list[int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`50`

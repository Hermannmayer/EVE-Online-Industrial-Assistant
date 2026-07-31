# services.inventory_manager

> 源文件 `services/inventory_manager.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存管理数据层 — 机库 CRUD / 物品入库 / 加权平均成本 / 移动

## 函数

### `init_db`

```python
def init_db()
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

### `get_hangars`

```python
def get_hangars() -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`66`

### `create_hangar`

```python
def create_hangar(name: str) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`73`

### `rename_hangar`

```python
def rename_hangar(hangar_id: int, name: str) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`

### `delete_hangar`

```python
def delete_hangar(hangar_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`90`

### `get_items`

```python
def get_items(hangar_id: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`98`

### `get_item_price`

```python
def get_item_price(type_id: int) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`154`

### `get_inventory_cost_map`

```python
def get_inventory_cost_map(_db: DatabaseManager | None=None) -> dict[int, tuple[int, float]]
```

跨机库汇总各物品库存数量与加权平均成本（成本按数量加权）。

定义行：`162`

### `add_item`

```python
def add_item(hangar_id: int, type_id: int, quantity: int, cost_price: float=0) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`193`

### `remove_item`

```python
def remove_item(item_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`224`

### `update_quantity`

```python
def update_quantity(item_id: int, quantity: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`231`

### `move_items`

```python
def move_items(item_ids: list[int], to_hangar_id: int)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`243`

### `get_total_value`

```python
def get_total_value(hangar_id: int, price_type: str='sell', discount: float=0) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`275`

### `add_blueprint`

```python
def add_blueprint(hangar_id: int, blueprint_type_id: int, is_bpo: bool=True, me_level: int=0, te_level: int=0, runs: int=1, quantity: int=1, notes: str='') -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`307`

### `get_blueprints`

```python
def get_blueprints(hangar_id: int | None=None) -> list[dict]
```

获取用户蓝图列表，可指定机库或全部

定义行：`328`

### `update_blueprint`

```python
def update_blueprint(bp_id: int, **kwargs) -> bool
```

更新蓝图属性，kwargs 可含 is_bpo, me_level, te_level, runs, quantity, notes

定义行：`368`

### `delete_blueprint`

```python
def delete_blueprint(bp_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`384`

### `delete_blueprints_batch`

```python
def delete_blueprints_batch(ids: list[int]) -> int
```

批量删除蓝图，返回删除行数

定义行：`391`

### `move_blueprints_to_hangar`

```python
def move_blueprints_to_hangar(ids: list[int], hangar_id: int) -> int
```

批量移动蓝图到目标机库

定义行：`402`

### `update_blueprints_batch`

```python
def update_blueprints_batch(ids: list[int], **kwargs) -> int
```

批量更新蓝图属性（me_level, te_level, runs, cost_per_run 等）

定义行：`413`

### `get_blueprint_product_info`

```python
def get_blueprint_product_info(blueprint_type_id: int) -> dict | None
```

获取蓝图的产物信息（名称、产量、制造时间）

定义行：`430`

### `get_blueprint_product_info_batch`

```python
def get_blueprint_product_info_batch(bp_ids: list[int]) -> dict[int, dict]
```

批量获取蓝图产物信息，返回 &#123;blueprint_type_id: &#123;product_type_id, product_name, product_quantity, base_time&#125;&#125;

定义行：`460`

### `get_blueprint_materials_batch`

```python
def get_blueprint_materials_batch(bp_ids: list[int]) -> dict[int, list[tuple[int, int]]]
```

批量获取蓝图材料，返回 &#123;blueprint_type_id: [(material_type_id, quantity), ...]&#125;

定义行：`491`

### `check_blueprint_exists`

```python
def check_blueprint_exists(blueprint_type_id: int) -> bool
```

检查用户蓝图库中是否已存在指定类型的蓝图

定义行：`512`

### `get_blueprint_tech_levels`

```python
def get_blueprint_tech_levels()
```

从 reference.db 获取各蓝图的科技等级

定义行：`520`

### `get_blueprint_reaction_ids`

```python
def get_blueprint_reaction_ids() -> set[int]
```

获取所有反应公式的 blueprint_type_id

定义行：`557`

# services.inventory_manager

> 源文件 `services/inventory_manager.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存管理数据层 — 机库 CRUD / 物品入库 / 加权平均成本 / 移动

## 函数

### `_default_db`

```python
def _default_db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。

定义行：`14`

### `init_db`

```python
def init_db()
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`61`

### `get_hangars`

```python
def get_hangars() -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`78`

### `create_hangar`

```python
def create_hangar(name: str, solar_system_id: int | None=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`96`

### `rename_hangar`

```python
def rename_hangar(hangar_id: int, name: str) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`106`

### `update_hangar_system`

```python
def update_hangar_system(hangar_id: int, solar_system_id: int | None) -> bool
```

设置机库所在星系（None 清除）。

定义行：`113`

### `get_hangar_system_id`

```python
def get_hangar_system_id(hangar_id: int | None, *, _db: DatabaseManager | None=None) -> int | None
```

读取机库所在星系的 solar_system_id（无机库/未设置返回 None）。

定义行：`121`

### `get_hangar_name`

```python
def get_hangar_name(hangar_id: int | None) -> str
```

读取机库名称（无机库/未设置返回空串）。

定义行：`131`

### `get_default_mat_hangar_and_system`

```python
def get_default_mat_hangar_and_system() -> tuple[int | None, int | None]
```

返回 (默认材料机库 id, 其所在星系 id)。settings 未配置/读取失败 → (None, None)。

定义行：`143`

### `get_default_mat_hangar_system_id`

```python
def get_default_mat_hangar_system_id() -> int | None
```

从 settings.json 默认材料机库带出星系（无计划上下文的 SCI 依据）。

定义行：`162`

### `update_hangar_config`

```python
def update_hangar_config(hangar_id: int, facility_type: str | None, facility_tax: float | None, rigs: list[int] | None) -> bool
```

更新机库工业配置（设施类型/设施税/改件）。rigs 存 JSON 数组。

定义行：`167`

### `get_hangar_config`

```python
def get_hangar_config(hangar_id: int | None) -> dict
```

读取机库工业配置 &#123;facility_type, facility_tax, rigs: list[int]&#125;；无机库/未配置返回默认。

定义行：`183`

### `delete_hangar`

```python
def delete_hangar(hangar_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`203`

### `get_items`

```python
def get_items(hangar_id: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`211`

### `get_item_price`

```python
def get_item_price(type_id: int) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`296`

### `get_inventory_cost_map`

```python
def get_inventory_cost_map(_db: DatabaseManager | None=None) -> dict[int, tuple[int, float]]
```

跨机库汇总各物品库存数量与加权平均成本（成本按数量加权）。

定义行：`304`

### `add_item`

```python
def add_item(hangar_id: int, type_id: int, quantity: int, cost_price: float=0, *, conn=None) -> int
```

把 quantity 件物品加入机库，按加权平均成本合并。

定义行：`335`

### `set_item_quantity`

```python
def set_item_quantity(hangar_id: int, type_id: int, quantity: int, cost_price: float | None=None, *, conn=None) -> int
```

全量同步：把 (hangar_id, type_id) 的数量设为 quantity。

定义行：`373`

### `update_cost_price`

```python
def update_cost_price(item_id: int, cost_price: float) -> bool
```

直接覆盖该库存行的单位成本价（参数化 UPDATE，返回是否命中）。

定义行：`423`

### `get_hangar_stock`

```python
def get_hangar_stock(hangar_id: int) -> dict[int, int]
```

单机库库存快照 &#123;type_id: quantity&#125;（quantity > 0 才计入）。

定义行：`431`

### `get_hangar_cost_map`

```python
def get_hangar_cost_map(hangar_id: int) -> dict[int, float]
```

单机库物品成本快照 &#123;type_id: 加权平均成本&#125;。

定义行：`448`

### `deduct_item`

```python
def deduct_item(hangar_id: int, type_id: int, quantity: int, *, conn=None) -> int
```

从机库扣减 quantity，返回实际扣减量。

定义行：`464`

### `remove_item`

```python
def remove_item(item_id: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`500`

### `update_quantity`

```python
def update_quantity(item_id: int, quantity: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`507`

### `move_items`

```python
def move_items(item_ids: list[int], to_hangar_id: int)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`519`

### `move_quantity`

```python
def move_quantity(from_hangar_id: int, type_id: int, quantity: int, to_hangar_id: int) -> int
```

按数量把物品从源机库移到目标机库，成本沿用源库单位成本。

定义行：`551`

### `get_total_value`

```python
def get_total_value(hangar_id: int, price_type: str='sell', discount: float=0) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`574`

### `add_blueprint`

```python
def add_blueprint(hangar_id: int, blueprint_type_id: int, is_bpo: bool=True, me_level: int=0, te_level: int=0, runs: int=1, quantity: int=1, notes: str='', *, conn=None) -> int
```

新增蓝图。conn 传入时在同一连接执行且不提交（由调用方统一事务）。

定义行：`606`

### `get_blueprints`

```python
def get_blueprints(hangar_id: int | None=None) -> list[dict]
```

获取用户蓝图列表，可指定机库或全部

定义行：`635`

### `update_blueprint`

```python
def update_blueprint(bp_id: int, **kwargs) -> bool
```

更新蓝图属性，kwargs 可含 is_bpo, me_level, te_level, runs, quantity, notes

定义行：`675`

### `delete_blueprint`

```python
def delete_blueprint(bp_id: int, *, conn=None) -> bool
```

删除蓝图。conn 传入时在同一连接执行且不提交（由调用方统一事务）。

定义行：`691`

### `delete_blueprints_batch`

```python
def delete_blueprints_batch(ids: list[int]) -> int
```

批量删除蓝图，返回删除行数

定义行：`713`

### `move_blueprints_to_hangar`

```python
def move_blueprints_to_hangar(ids: list[int], hangar_id: int) -> int
```

批量移动蓝图到目标机库

定义行：`735`

### `update_blueprints_batch`

```python
def update_blueprints_batch(ids: list[int], **kwargs) -> int
```

批量更新蓝图属性（me_level, te_level, runs, cost_per_run 等）

定义行：`746`

### `get_blueprint_product_info`

```python
def get_blueprint_product_info(blueprint_type_id: int) -> dict | None
```

获取蓝图的产物信息（名称、产量、制造时间）

定义行：`763`

### `get_blueprint_product_info_batch`

```python
def get_blueprint_product_info_batch(bp_ids: list[int]) -> dict[int, dict]
```

批量获取蓝图产物信息，返回 &#123;blueprint_type_id: &#123;product_type_id, product_name, product_quantity, base_time&#125;&#125;

定义行：`793`

### `get_blueprint_materials_batch`

```python
def get_blueprint_materials_batch(bp_ids: list[int]) -> dict[int, list[tuple[int, int]]]
```

批量获取蓝图材料，返回 &#123;blueprint_type_id: [(material_type_id, quantity), ...]&#125;

定义行：`824`

### `check_blueprint_exists`

```python
def check_blueprint_exists(blueprint_type_id: int) -> bool
```

检查用户蓝图库中是否已存在指定类型的蓝图

定义行：`845`

### `get_blueprint_tech_levels`

```python
def get_blueprint_tech_levels()
```

从 reference.db 获取各蓝图的科技等级

定义行：`853`

### `get_blueprint_reaction_ids`

```python
def get_blueprint_reaction_ids() -> set[int]
```

获取所有反应公式的 blueprint_type_id

定义行：`890`

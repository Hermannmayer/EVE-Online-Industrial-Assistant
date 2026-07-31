# services.production_scheduler

> 源文件 `services/production_scheduler.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产排程优化 — 基于材料需求和生产计划的排程

## 函数

### `_get_plan`

```python
def _get_plan(conn: sqlite3.Connection, plan_id: int) -> dict | None
```

从 user.db 读取单条 production_plans 记录

定义行：`24`

### `_get_item_name`

```python
def _get_item_name(conn: sqlite3.Connection, type_id: int) -> str
```

从 name_resolver 获取物品名称（有 terminology 覆盖兜底）

定义行：`30`

### `_get_blueprint_for_product`

```python
def _get_blueprint_for_product(conn: sqlite3.Connection, product_type_id: int) -> tuple[int | None, int]
```

根据 product_type_id 找到 blueprint_type_id 和默认产量

定义行：`37`

### `_get_materials`

```python
def _get_materials(conn: sqlite3.Connection, blueprint_type_id: int) -> list[tuple[int, int]]
```

获取蓝图的 (material_type_id, base_quantity) 列表

定义行：`51`

### `_get_price`

```python
def _get_price(conn: sqlite3.Connection, type_id: int, hub: str='Jita') -> float
```

获取物品在指定 Hub 的卖价

定义行：`62`

### `_get_inventory_qty`

```python
def _get_inventory_qty(conn: sqlite3.Connection, type_id: int) -> float
```

获取用户库存中该 type_id 的总数量

定义行：`73`

### `analyze_production_plan`

```python
def analyze_production_plan(plan_id: int, char_config: dict | None=None, price_hub: str='Jita') -> dict
```

分析单个生产计划的材料需求和成本。

定义行：`87`

### `get_all_plans_summary`

```python
def get_all_plans_summary(char_config: dict | None=None, price_hub: str='Jita') -> list[dict]
```

获取所有生产计划的概览列表，按依赖关系排序。

定义行：`179`

### `suggest_production_order`

```python
def suggest_production_order(char_config: dict | None=None, price_hub: str='Jita') -> list[dict]
```

对所有 pending 状态的生产计划，按依赖关系排序建议生产顺序。

定义行：`216`

### `optimize_material_purchase`

```python
def optimize_material_purchase(plan_ids: list[int], price_hub: str='Jita', budget: float | None=None) -> dict
```

在有限预算下优化材料采购，优先购买关键材料。

定义行：`331`

# services.plan_aggregator

> 源文件 `services/plan_aggregator.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

计划聚合查询 — 为工业制造三张汇总表提供统一数据层

将 blueprint_dialog / materials_dialog / output_dialog 公用的
蓝图库存、材料库存、产出溢出计算提取到这里。

用法:
    from services.plan_aggregator import (
        expand_blueprint_requirements,
        check_user_blueprints,
        check_inventory,
        calculate_output_with_overflow,
    )

    with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
        plans = ...  # list[dict]
        bps = expand_blueprint_requirements(conn, plans)
        bp_inv = check_user_blueprints(conn, set(bps.keys()))

## 函数

### `_resolve_name`

```python
def _resolve_name(conn, type_id: int) -> str
```

委托给 name_resolver（有 terminology 覆盖兜底）

定义行：`37`

### `_resolve_bp_name`

```python
def _resolve_bp_name(conn, bp_type_id: int) -> str
```

查出蓝图名称（优先从 item 表）

定义行：`42`

### `_get_per_run_output`

```python
def _get_per_run_output(conn, bp_type_id: int) -> int
```

获取蓝图每次制造的产出数量

定义行：`58`

### `expand_blueprint_requirements`

```python
def expand_blueprint_requirements(conn, plans: list[dict], *, me_level: int=0) -> dict[int, dict[str, Any]]
```

收集每个生产计划顶层产物的蓝图需求（不递归展开 BOM 子项）。

定义行：`72`

### `check_user_blueprints`

```python
def check_user_blueprints(conn, bp_type_ids: set[int]) -> dict[int, dict[str, Any]]
```

查询用户蓝图库存，返回每个 blueprint_type_id 的拥有情况。

定义行：`134`

### `check_inventory`

```python
def check_inventory(conn, type_ids: set[int]) -> dict[int, int]
```

查询用户库存（所有机库合计），返回 &#123;type_id: total_quantity&#125;

定义行：`227`

### `get_market_prices`

```python
def get_market_prices(conn, type_ids: set[int], region_id: int=10000002) -> dict[int, dict[str, float]]
```

批量查询市场价，返回 &#123;type_id: &#123;"sell": float, "buy": float, "avg": float&#125;&#125;

定义行：`254`

### `get_batch_adjustment`

```python
def get_batch_adjustment(per_run_output: int, needed_qty: int) -> tuple[int, int, int]
```

计算批次调整 — 当蓝图产出为批量时，可能需要向上取整。

定义行：`287`

### `calculate_output_with_overflow`

```python
def calculate_output_with_overflow(conn, plans: list[dict], *, me_level: int=0, max_depth: int=4, region_id: int=10000002) -> list[dict[str, Any]]
```

计算所有计划的产出数据，含中间产品的 batch 溢出信息。

定义行：`311`

### `_format_overflow`

```python
def _format_overflow(details: list[dict]) -> str
```

格式化溢出信息为短文本

定义行：`396`

### `_pick_price`

```python
def _pick_price(price_map: dict[str, float], price_type: str) -> float
```

按价格类型取价；缺省回退另一个来源，均无数据返回 0.0

定义行：`413`

### `aggregate_procurement`

```python
def aggregate_procurement(conn, plans: list[dict], *, hangar_id: int | None=None, default_hangar_id: int | None=None, region_id: int=10000002, price_type: str='sell') -> tuple[list[dict], float, float]
```

聚合「备料中」计划的待采购材料并扣库存 → (rows, total_cost, total_volume)。

定义行：`422`

### `collect_direct_materials`

```python
def collect_direct_materials(conn, plans: list[dict]) -> dict[int, dict]
```

聚合各计划的直接材料（recipe 一层，非递归），排除由子项产线自制的组件。

定义行：`566`

# services.plan_aggregator

> 源文件 `services/plan_aggregator.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

计划聚合查询 — 为工业制造三张汇总表提供统一数据层

## 函数

### `_resolve_name`

```python
def _resolve_name(conn, type_id: int) -> str
```

委托给 name_resolver（有 terminology 覆盖兜底）

定义行：`41`

### `_resolve_bp_name`

```python
def _resolve_bp_name(conn, bp_type_id: int) -> str
```

查出蓝图名称（优先从 item 表）

定义行：`46`

### `_get_per_run_output`

```python
def _get_per_run_output(conn, bp_type_id: int) -> int
```

获取蓝图每次制造的产出数量

定义行：`62`

### `expand_blueprint_requirements`

```python
def expand_blueprint_requirements(conn, plans: list[dict], *, me_level: int=0) -> dict[int, dict[str, Any]]
```

收集每个生产计划顶层产物的蓝图需求（不递归展开 BOM 子项）。

定义行：`76`

### `expand_material_requirements`

```python
def expand_material_requirements(conn, plans: list[dict], *, me_level: int=0, max_depth: int=5) -> dict[int, dict[str, Any]]
```

展开 BOM 到叶子节点，返回所有原材料需求汇总。

定义行：`138`

### `check_user_blueprints`

```python
def check_user_blueprints(conn, bp_type_ids: set[int]) -> dict[int, dict[str, Any]]
```

查询用户蓝图库存，返回每个 blueprint_type_id 的拥有情况。

定义行：`237`

### `check_inventory`

```python
def check_inventory(conn, type_ids: set[int]) -> dict[int, int]
```

查询用户库存（所有机库合计），返回 &#123;type_id: total_quantity&#125;

定义行：`330`

### `get_market_prices`

```python
def get_market_prices(conn, type_ids: set[int], region_id: int=10000002) -> dict[int, dict[str, float]]
```

批量查询市场价，返回 &#123;type_id: &#123;"sell": float, "buy": float, "avg": float&#125;&#125;

定义行：`357`

### `get_batch_adjustment`

```python
def get_batch_adjustment(per_run_output: int, needed_qty: int) -> tuple[int, int, int]
```

计算批次调整 — 当蓝图产出为批量时，可能需要向上取整。

定义行：`390`

### `calculate_output_with_overflow`

```python
def calculate_output_with_overflow(conn, plans: list[dict], *, me_level: int=0, max_depth: int=4, region_id: int=10000002) -> list[dict[str, Any]]
```

计算所有计划的产出数据，含中间产品的 batch 溢出信息。

定义行：`414`

### `_format_overflow`

```python
def _format_overflow(details: list[dict]) -> str
```

格式化溢出信息为短文本

定义行：`535`

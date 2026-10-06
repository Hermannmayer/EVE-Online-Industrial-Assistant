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

定义行：`52`

### `_resolve_bp_name`

```python
def _resolve_bp_name(conn, bp_type_id: int) -> str
```

查出蓝图名称（优先从 item 表）

定义行：`57`

### `_get_per_run_output`

```python
def _get_per_run_output(conn, bp_type_id: int, activity: str=ACTIVITY_MANUFACTURING) -> int
```

获取蓝图每次作业的产出数量（默认制造；反应产物的产出挂在 `activity='reaction'` 行上）

定义行：`73`

### `_source_label`

```python
def _source_label(activity: str | None) -> str
```

「用途/来源」列文案 —— 这张蓝图在本计划里是干什么用的。

定义行：`97`

### `_bound_blueprint_type`

```python
def _bound_blueprint_type(conn, plan: dict) -> int | None
```

计划绑定的那张库存蓝图的 **blueprint_type_id**（未绑定/取不到 → None）。

定义行：`111`

### `plan_input_blueprint_type_id`

```python
def plan_input_blueprint_type_id(conn, plan: dict) -> int | None
```

本计划要绑的那张**输入蓝图** type_id（活动契约的取数实现；反查不到 → None）。

定义行：`135`

### `_science_input_blueprint`

```python
def _science_input_blueprint(conn, plan: dict, pid: int) -> int | None
```

科研行真正要消耗的那张蓝图 type_id（反查不到 → None，不编造）。

定义行：`163`

### `_science_needed_runs`

```python
def _science_needed_runs(plan: dict, activity: str) -> int
```

科研行的「所需流程数」（缺列按制造行同一套 defaults 兜 1，不编造不存在的量）。

定义行：`186`

### `_add_source`

```python
def _add_source(entry: dict, label: str) -> None
```

同一张蓝图被多条计划以不同用途需要时并起用途标签（同一用途不重复）。

定义行：`201`

### `_invention_input_suffix`

```python
def _invention_input_suffix(conn, activity: str, bp_tid: int) -> str
```

发明输入**不是蓝图**时补的括注 —— T3 发明的输入是古遗物，不是 T1 蓝图。

定义行：`208`

### `expand_blueprint_requirements`

```python
def expand_blueprint_requirements(conn, plans: list[dict], *, me_level: int=0) -> dict[int, dict[str, Any]]
```

收集每个生产计划**真正要消耗的那张蓝图**（不递归展开 BOM 子项）。

定义行：`221`

### `check_user_blueprints`

```python
def check_user_blueprints(conn, bp_type_ids: set[int]) -> dict[int, dict[str, Any]]
```

查询用户蓝图库存，返回每个 blueprint_type_id 的拥有情况。

定义行：`332`

### `check_inventory`

```python
def check_inventory(conn, type_ids: set[int]) -> dict[int, int]
```

查询用户库存（所有机库合计），返回 &#123;type_id: total_quantity&#125;

定义行：`425`

### `get_market_prices`

```python
def get_market_prices(conn, type_ids: set[int], region_id: int=10000002) -> dict[int, dict[str, float]]
```

批量查询市场价，返回 &#123;type_id: &#123;"sell": float, "buy": float, "avg": float&#125;&#125;

定义行：`452`

### `calculate_output_with_overflow`

```python
def calculate_output_with_overflow(conn, plans: list[dict], *, me_level: int=0, max_depth: int=4, region_id: int=10000002) -> list[dict[str, Any]]
```

计算所有计划的产出数据，含中间产品的 batch 溢出信息。

定义行：`485`

### `_format_overflow`

```python
def _format_overflow(details: list[dict]) -> str
```

格式化溢出信息为短文本

定义行：`581`

### `_pick_price`

```python
def _pick_price(price_map: dict[str, float], price_type: str) -> float
```

按价格类型取价；缺省回退另一个来源，均无数据返回 0.0

定义行：`598`

### `_spread`

```python
def _spread(price_map: dict[str, float], qty: float) -> float | None
```

(卖价 − 买价) × 数量 —— 同一 hub 的挂单价差，按采购量换算成金额。任一侧没有挂单 → `None`。

定义行：`607`

### `self_made_type_ids`

```python
def self_made_type_ids(plans: list[dict]) -> set[int]
```

会被「自制」覆盖的产物 id：**未完工的子项产线**的产物。

定义行：`627`

### `_plan_total_runs`

```python
def _plan_total_runs(plan: dict) -> int
```

计划的**字面**总作业数 = `runs × parallels`；`runs=0` 就是 0，不兜成 1。

定义行：`650`

### `_science_material_requirements`

```python
def _science_material_requirements(plan: dict) -> list[dict]
```

科研计划要买的材料（数据核心 / 解码器 / 拷贝与研究的耗材）[&#123;type_id, name, need&#125;]。

定义行：`661`

### `_cache_item_meta`

```python
def _cache_item_meta(conn, mid: int, names: dict, volumes: dict, zh_en: dict) -> None
```

补一份该材料的名称/体积缓存（制造、科研、强制启动缺口三条取料分支共用）。

定义行：`676`

### `aggregate_procurement`

```python
def aggregate_procurement(conn, plans: list[dict], *, hangar_id: int | None=None, default_hangar_id: int | None=None, region_id: int=10000002, price_type: str='sell', price_mult: float=1.0, self_made: set[int] | None=None) -> tuple[list[dict], float, float]
```

聚合「备料中」计划的待采购材料并扣库存 → (rows, total_cost, total_volume)。

定义行：`689`

### `collect_direct_materials`

```python
def collect_direct_materials(conn, plans: list[dict]) -> dict[int, dict]
```

聚合各计划的直接材料（recipe 一层，非递归），排除由子项产线自制的组件。

定义行：`855`

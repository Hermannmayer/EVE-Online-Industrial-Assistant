# services.research_calculator

> 源文件 `services/research_calculator.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

研究成本计算 — 拷贝(copying) / 发明(invention) 成本。

## 函数

### `_default_research_system_id`

```python
def _default_research_system_id() -> int
```

默认科研机库所在星系；未配置 → 默认制造材料机库 → Jita。

定义行：`25`

### `_installation_fee`

```python
def _installation_fee(activity: str, eiv: float, solar_system_id: int | None) -> float
```

研究活动安装费（EIV × SCI(活动, 设施星系) × 结构 + 税 + SCC）。

定义行：`48`

### `_prices`

```python
def _prices(type_ids: list[int]) -> dict[int, float]
```

批量取 adjusted_price（mkt 库）；缺失按 0。

定义行：`69`

### `_material_cost`

```python
def _material_cost(conn: Connection, prices: dict[int, float], blueprint_type_id: int, activity: str) -> float
```

蓝图某活动的材料总价（调整价 × 数量）。

定义行：`84`

### `research_cost_for_item`

```python
def research_cost_for_item(bp_conn: Connection, type_id: int, *, solar_system_id: int | None=None) -> float | None
```

单个物品的研究成本（拷贝或发明）；原图/无蓝图 → None。

定义行：`97`

### `research_costs_batch`

```python
def research_costs_batch(bp_conn: Connection, type_ids: list[int], *, solar_system_id: int | None=None) -> dict[int, float | None]
```

批量计算物品研究成本 &#123;type_id: cost|None&#125;（避免 N+1）。

定义行：`104`

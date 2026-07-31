# core.eve_formulas

> 源文件 `core/eve_formulas.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

EVE Online 游戏公式常量。

## 函数

### `resolve_item_name`

```python
def resolve_item_name(c, type_id: int) -> str
```

统一物品名称解析 — 已迁移至 services.name_resolver。

定义行：`59`

### `_mat_name`

```python
def _mat_name(mat_id: int, c) -> str
```

查询材料名称 — 已迁移至 services.name_resolver。

定义行：`66`

### `_hub_region_id`

```python
def _hub_region_id(hub: str | None) -> int
```

hub 名称 → region_id，None 或未知时默认 Jita

定义行：`73`

### `calc_refining_yield`

```python
def calc_refining_yield(skills: dict | None=None, *, is_player_facility: bool=False, station_base: float | None=None, implant_bonus: float=0.0) -> float
```

计算精炼产出率 (0.0~1.0)

定义行：`85`

### `calc_broker_rate`

```python
def calc_broker_rate(skills: dict, market_data: dict) -> float
```

计算经纪人费率 (%)。

定义行：`119`

### `calc_relist_discount`

```python
def calc_relist_discount(skills: dict) -> float
```

计算改单折扣 (%)。基础 50%，高级经纪人关系学每级 +5%，上限 100%。

定义行：`139`

### `calc_sales_tax_rate`

```python
def calc_sales_tax_rate(skills: dict) -> float
```

计算销售税率 (%)。基础 2%，会计学每级 -3%。

定义行：`145`

# core.eve_formulas

> 源文件 `core/eve_formulas.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

EVE Online 游戏公式常量。

## 函数

### `_hub_region_id`

```python
def _hub_region_id(hub: str | None) -> int
```

hub 名称 → region_id，None 或未知时默认 Jita

定义行：`59`

### `calc_refining_yield`

```python
def calc_refining_yield(skills: dict | None=None, *, is_player_facility: bool=False, station_base: float | None=None, implant_bonus: float=0.0) -> float
```

计算精炼产出率 (0.0~1.0)

定义行：`71`

### `calc_broker_rate`

```python
def calc_broker_rate(skills: dict, market_data: dict) -> float
```

计算经纪人费率 (%)。

定义行：`105`

### `calc_relist_discount`

```python
def calc_relist_discount(skills: dict) -> float
```

计算改单折扣 (%)。基础 50%，高级经纪人关系学每级 +5%，上限 100%。

定义行：`125`

### `calc_sales_tax_rate`

```python
def calc_sales_tax_rate(skills: dict) -> float
```

计算销售税率 (%)。基础 2%，会计学每级 -3%。

定义行：`131`

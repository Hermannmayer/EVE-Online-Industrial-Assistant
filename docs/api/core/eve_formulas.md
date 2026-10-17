# core.eve_formulas

> 源文件 `core/eve_formulas.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

EVE Online 游戏公式常量。

来源:
- 制造: https://wiki.eveuniversity.org/Manufacturing
- 贸易: https://wiki.eveuniversity.org/Trade

## 函数

### `_hub_region_id`

```python
def _hub_region_id(hub: str | None) -> int
```

hub 名称 → region_id，None 或未知时默认 Jita

定义行：`84`

### `calc_refining_yield`

```python
def calc_refining_yield(skills: dict | None=None, *, is_player_facility: bool=False, station_base: float | None=None, structure_type: str | None=None, security_mult: float=0.0, rig_mult: float=0.0, implant_bonus: float=0.0, ore_skill_level: int=0) -> float
```

计算精炼产出率 (0.0~1.0)

定义行：`96`

### `calc_broker_rate`

```python
def calc_broker_rate(skills: dict, market_data: dict) -> float
```

计算 NPC 空间站经纪人费率 (%)。

定义行：`158`

### `calc_relist_discount`

```python
def calc_relist_discount(skills: dict) -> float
```

计算改单折扣 (%)。基础 50%，高级经纪人关系学每级 +6 个百分点（V 级 = 80%）。

定义行：`177`

### `calc_sales_tax_rate`

```python
def calc_sales_tax_rate(skills: dict) -> float
```

计算销售税率 (%)。基础 7.5%，会计学每级 -11%（V 级 = 3.375%）。

定义行：`183`

### `calc_relist_fee`

```python
def calc_relist_fee(new_total: float, price_increase: float, broker_rate_pct: float, relist_discount_pct: float) -> float
```

改单费（ISK）—— 官方两段式（EVE Uni `Skills:Trade`「Advanced Broker Relations」）：

定义行：`189`

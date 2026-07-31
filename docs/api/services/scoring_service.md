# services.scoring_service

> 源文件 `services/scoring_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

## 函数

### `_hub_to_system_id`

```python
def _hub_to_system_id(hub: str) -> int | None
```

将贸易中心名称映射为太阳系 ID。

定义行：`43`

### `cache_key`

```python
def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`102`

### `get_cache`

```python
def get_cache(key: str) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`110`

### `set_cache`

```python
def set_cache(key: str, result: dict)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`114`

### `invalidate_cache`

```python
def invalidate_cache()
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`118`

### `_get_scoring_service`

```python
def _get_scoring_service() -> ScoringService
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`126`

### `resolve_char_config`

```python
def resolve_char_config(char_name: str | None=None, char_data: dict | None=None, skills: dict | None=None) -> dict
```

统一解析角色配置，返回 ScoringService 可用的 char_config dict。

定义行：`140`

### `get_price`

```python
def get_price(type_id: int, price_type: str, hub: str | None=None, _db: DatabaseManager | None=None) -> float | None
```

从 market_prices 获取指定区域的价格。
price_type: 'buy' → buy_price, 'sell' → sell_price
hub: 贸易中心名称, 如 'Jita', 'Amarr'；None 时返回任意区域
_db: 可选注入的 DatabaseManager；None 时使用模块级单例。

定义行：`187`

### `get_volume`

```python
def get_volume(type_id: int, vol_type: str='total', hub: str | None=None, _db: DatabaseManager | None=None) -> int
```

获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'

定义行：`229`

### `get_system_cost_index`

```python
def get_system_cost_index(system_id: int | None, activity: str='manufacturing', _db: DatabaseManager | None=None, hub: str='Jita') -> float
```

从数据库获取星系的制造成本指数(SCI)。system_id=None 时从 hub 推断。

定义行：`270`

### `get_adjusted_price`

```python
def get_adjusted_price(type_id: int, _db: DatabaseManager | None=None) -> float | None
```

获取 ESI adjusted price（EIV 计算用）。兜底 None → 用 sell_price。

定义行：`292`

### `calc_refining_value`

```python
def calc_refining_value(type_id: int, quantity: int=1, *, skills: dict | None=None, is_player_facility: bool=False, price_hub: str='Jita', yield_override: float | None=None, ore_skill: int=0) -> dict
```

计算物品的精炼产出及总价值

定义行：`319`

### `calc_manufacturing_score`

```python
def calc_manufacturing_score(type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', bp_me: int=0, bp_te: int=0, system_id: int | None=None, structure_bonus: float=0.0, structure_time_mod: float=1.0, is_alpha: bool=False) -> dict
```

模块级便利函数：复用模块级单例 ScoringService。

定义行：`1181`

### `calc_trade_score`

```python
def calc_trade_score(type_id: int, buy_hub: str='Jita', sell_hub: str='Jita', buy_price_type: str='buy', sell_price_type: str='sell', char_config: dict | None=None, quantity: int=1) -> dict
```

模块级便利函数：复用模块级单例 ScoringService。

定义行：`1214`

### `calc_reaction_score`

```python
def calc_reaction_score(type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', system_id: int | None=None, structure_bonus: float=0.0) -> dict
```

模块级便利函数：复用模块级单例 ScoringService。

定义行：`1235`

## 类

### `class ScoringCache`

线程安全的有界评分缓存，过期被动清理 + LRU 淘汰

定义行：`56`

#### 方法

##### `__init__`

```python
def __init__(self, max_size: int=500, ttl: int=1800)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`
##### `get`

```python
def get(self, key: str) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`65`
##### `set`

```python
def set(self, key: str, result: dict)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`78`
##### `invalidate`

```python
def invalidate(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`87`
##### `_evict_expired_locked`

```python
def _evict_expired_locked(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`91`
##### `__len__`

```python
def __len__(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`97`

### `class ScoringService`

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`425`

#### 方法

##### `__init__`

```python
def __init__(self, db: DatabaseManager, cache: ScoringCache, char_config: dict | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`426`
##### `_calc_broker_rate`

```python
def _calc_broker_rate(self, skills: dict, market_data: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`433`
##### `_calc_relist_discount`

```python
def _calc_relist_discount(self, skills: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`436`
##### `_calc_sales_tax_rate`

```python
def _calc_sales_tax_rate(self, skills: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`439`
##### `calculate_total_metrics`

```python
def calculate_total_metrics(per_run: dict, runs: int=1, parallels: int=1) -> dict
```

将 per-run 评分结果按 runs/parallels 缩放到计划总数值。

定义行：`445`
##### `calculate_plan_metrics`

```python
def calculate_plan_metrics(plan_data: dict, char_config: dict, *, mat_hub: str | None=None, sell_hub: str | None=None, price_type_mat: str | None=None, price_type_prod: str | None=None) -> dict
```

从一条生产计划数据计算所有派生指标。

定义行：`490`
##### `calculate_personal_margin`

```python
def calculate_personal_margin(result: dict, inv_map: dict[int, tuple[int, float]], runs: int=1, parallels: int=1) -> float
```

计算考虑库存成本的个人利润率（%）。

定义行：`594`
##### `calc_manufacturing_score`

```python
def calc_manufacturing_score(self, type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', bp_me: int=0, bp_te: int=0, system_id: int | None=None, structure_bonus: float=0.0, structure_time_mod: float=1.0, is_alpha: bool=False) -> dict
```

计算制造评分。

定义行：`656`
##### `calc_trade_score`

```python
def calc_trade_score(self, type_id: int, buy_hub: str='Jita', sell_hub: str='Jita', buy_price_type: str='buy', sell_price_type: str='sell', char_config: dict | None=None, quantity: int=1) -> dict
```

计算贸易评分。

定义行：`896`
##### `calc_reaction_score`

```python
def calc_reaction_score(self, type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', system_id: int | None=None, structure_bonus: float=0.0) -> dict
```

计算反应（Reaction）利润评分。

定义行：`981`

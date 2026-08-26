# services.scoring_service

> 源文件 `services/scoring_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

包含:
  - ScoringCache：线程安全、有界 TTL 缓存
  - 模块级便利函数：get_price / get_volume / get_system_cost_index / calc_*_score
    （评分链路取价直查 market.db market_prices，不经 PricingService）
  - ScoringService：可注入的评分服务类（同接口 + calc_reaction_score）；calc_*_score
    为薄委托 → scoring_facade 编排（读 DB/缓存）→ domain.scoring 纯算法
被 industry/trade 页各评分 Worker 消费。

## 函数

### `_hub_to_system_id`

```python
def _hub_to_system_id(hub: str) -> int | None
```

将贸易中心名称映射为太阳系 ID。

定义行：`33`

### `_default_db`

```python
def _default_db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。

定义行：`38`

### `cache_key`

```python
def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

### `invalidate_cache`

```python
def invalidate_cache()
```

清空模块级研究成本缓存（价格刷新后调用）。

定义行：`56`

### `get_price`

```python
def get_price(type_id: int, price_type: str, hub: str | None=None, _db: DatabaseManager | None=None) -> float | None
```

从 market_prices 获取指定区域的价格。
price_type: 'buy' → buy_price, 'sell' → sell_price
hub: 贸易中心名称, 如 'Jita', 'Amarr'；None 时返回任意区域
_db: 可选注入的 DatabaseManager；None 时使用模块级单例。

定义行：`70`

### `get_volume`

```python
def get_volume(type_id: int, vol_type: str='total', hub: str | None=None, _db: DatabaseManager | None=None) -> int
```

获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'

定义行：`112`

### `get_system_cost_index`

```python
def get_system_cost_index(system_id: int | None, activity: str='manufacturing', _db: DatabaseManager | None=None, hub: str='Jita') -> float
```

从数据库获取星系的制造成本指数(SCI)。system_id=None 时从 hub 推断。

定义行：`153`

### `get_adjusted_price`

```python
def get_adjusted_price(type_id: int, _db: DatabaseManager | None=None) -> float | None
```

获取 ESI adjusted price（EIV 计算用）。兜底 None → 用 sell_price。

定义行：`177`

### `_research_cost_cached`

```python
def _research_cost_cached(_db: DatabaseManager, type_id: int, *, solar_system_id: int | None=None) -> float
```

按 type_id + 设施星系计算研究成本（拷贝/发明），带进程内缓存；失败返回 0。

定义行：`204`

### `_clear_research_cost_cache`

```python
def _clear_research_cost_cache() -> None
```

清空研究成本缓存（价格刷新时调用）。

定义行：`228`

## 类

### `class ScoringService`

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`238`

#### 方法

##### `__init__`

```python
def __init__(self, db: DatabaseManager, cache: TtlLRUCache, char_config: dict | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`239`
##### `invalidate_cache`

```python
def invalidate_cache(self) -> None
```

清空评分缓存（价格刷新后调用，避免旧价格评分被复用）

定义行：`244`
##### `_calc_broker_rate`

```python
def _calc_broker_rate(self, skills: dict, market_data: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`252`
##### `_calc_relist_discount`

```python
def _calc_relist_discount(self, skills: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`255`
##### `_calc_sales_tax_rate`

```python
def _calc_sales_tax_rate(self, skills: dict) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`258`
##### `calculate_total_metrics`

```python
def calculate_total_metrics(per_run: dict, runs: int=1, parallels: int=1) -> dict
```

将 per-run 评分结果按 runs/parallels 缩放到计划总数值。

定义行：`264`
##### `calculate_plan_metrics`

```python
def calculate_plan_metrics(plan_data: dict, char_config: dict, *, mat_hub: str | None=None, sell_hub: str | None=None, price_type_mat: str | None=None, price_type_prod: str | None=None, system_id: int | None=None) -> dict
```

从一条生产计划数据计算所有派生指标。

定义行：`309`
##### `calculate_personal_margin`

```python
def calculate_personal_margin(result: dict, inv_map: dict[int, tuple[int, float]], runs: int=1, parallels: int=1, cost_overrides: dict[int, float] | None=None) -> float
```

计算考虑库存成本的个人利润率（%）。实现见 services.plan_metrics。

定义行：`461`
##### `child_manufacturing_cost`

```python
def child_manufacturing_cost(plan: dict, metrics: dict) -> float
```

一条子项产线的总制造价 = 材料成本 + 制造作业费。实现见 services.plan_metrics。

定义行：`474`
##### `adjust_mother_metrics`

```python
def adjust_mother_metrics(metrics: dict, sub_cost_map: dict[int, float], total_mult: int) -> tuple[float, float, float, dict[int, float]]
```

把拆解母项的自制子项按其制造价计入成本。实现见 services.plan_metrics。

定义行：`481`
##### `calc_manufacturing_score`

```python
def calc_manufacturing_score(self, type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', bp_me: int=0, bp_te: int=0, system_id: int | None=None, structure_bonus: float=0.0, structure_time_mod: float=1.0, structure_mat_saving: float=1.0, is_alpha: bool=False) -> dict
```

计算制造评分。

定义行：`493`
##### `calc_trade_score`

```python
def calc_trade_score(self, type_id: int, buy_hub: str='Jita', sell_hub: str='Jita', buy_price_type: str='buy', sell_price_type: str='sell', char_config: dict | None=None, quantity: int=1) -> dict
```

计算贸易评分。纯算法在 domain.scoring，编排在 services.scoring_facade。

定义行：`538`
##### `calc_reaction_score`

```python
def calc_reaction_score(self, type_id: int, char_config: dict, mat_source_hub: str='Jita', sell_hub: str='Jita', facility_tax_pct: float=0.0, price_type_mat: str='sell', price_type_prod: str='sell', system_id: int | None=None, structure_bonus: float=0.0) -> dict
```

计算反应（Reaction）利润评分。纯算法在 domain.scoring，编排在 services.scoring_facade。

定义行：`565`

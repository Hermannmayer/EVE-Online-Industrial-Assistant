# services.scoring_facade

> 源文件 `services/scoring_facade.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

评分编排门面。

职责：开连接 → 取蓝图/材料/名称/价格 → 组装输入 → 调 domain 纯函数 → 写缓存。

数据访问经 `services.scoring_service` 模块级函数（`_ss.get_price` 等）在调用时解析，
以保留测试对这些符号的 patch 语义（`@patch("services.scoring_service.get_price")`）。

## 函数

### `_preload_material_prices`

```python
def _preload_material_prices(db, mat_ids: list[int], price_type: str, hub: str | None) -> dict[tuple[int, str], float | None]
```

一次 IN 查询预取材料价格与 adjusted price（EIV）。

定义行：`56`

### `_char_config_fingerprint`

```python
def _char_config_fingerprint(char_config: dict | None) -> str
```

生成角色配置的稳定摘要，用于缓存 key，避免角色配置变更后命中旧评分。

定义行：`87`

### `calc_manufacturing_score`

```python
def calc_manufacturing_score(db, cache, *, type_id: int, char_config: dict | None, mat_source_hub: str, sell_hub: str, facility_tax_pct: float, price_type_mat: str, price_type_prod: str, bp_me: int, bp_te: int, system_id: int | None, structure_bonus: float, structure_time_mod: float, structure_mat_saving: float, is_alpha: bool, mat_price_mult: float=1.0, prod_price_mult: float=1.0, research_costs: dict[int, float | None] | None=None) -> dict[str, Any]
```

制造评分用例：编排 DB 读取 + 领域纯函数 + 缓存。

定义行：`98`

### `calc_trade_score`

```python
def calc_trade_score(db, cache, *, type_id: int, buy_hub: str, sell_hub: str, buy_price_type: str, sell_price_type: str, char_config: dict | None, quantity: int) -> dict[str, Any]
```

贸易评分用例：编排 DB 读取 + 领域纯函数 + 缓存。

定义行：`261`

### `calc_reaction_score`

```python
def calc_reaction_score(db, *, type_id: int, char_config: dict | None, mat_source_hub: str, sell_hub: str, facility_tax_pct: float, price_type_mat: str, price_type_prod: str, system_id: int | None, structure_bonus: float) -> dict[str, Any]
```

反应评分用例：编排 DB 读取 + 领域纯函数（反应无缓存）。

定义行：`327`

## 类

### `class _DbPriceProvider`

PriceProvider 适配 — 委托给 scoring_service 模块级定价函数（可被测试 patch）。

``preloaded``：本物品材料的一次性批量预取结果，键为 ``(type_id, "buy"/"sell"/"adjusted")``。
只装「一次查询就能确定」的键，查不到的一律回落模块级单条函数 —— 跨区域降级、
无价格、旧库缺列等语义全部保持原样。

定义行：`24`

#### 方法

##### `__init__`

```python
def __init__(self, db, preloaded: dict[tuple[int, str], float | None] | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`32`
##### `get_price`

```python
def get_price(self, type_id: int, price_type: str, hub: str | None=None) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `get_volume`

```python
def get_volume(self, type_id: int, vol_type: str='total', hub: str | None=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`42`
##### `get_system_cost_index`

```python
def get_system_cost_index(self, system_id: int | None, activity: str='manufacturing', hub: str='Jita') -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`45`
##### `get_adjusted_price`

```python
def get_adjusted_price(self, type_id: int) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`48`

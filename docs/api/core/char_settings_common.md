# core.char_settings_common

> 源文件 `core/char_settings_common.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

人物设置共享常量与公式。

## 函数

### `calc_broker_fee`

```python
def calc_broker_fee(skills: dict, faction_standing: float, corp_standing: float, base_rate: float=1.0) -> float
```

计算经纪人费率 (%)。委托 core.eve_formulas.calc_broker_rate。

定义行：`155`

### `calc_relist_discount`

```python
def calc_relist_discount(skills: dict) -> float
```

计算改单折扣 (%)。委托 core.eve_formulas。

定义行：`166`

### `calc_sales_tax`

```python
def calc_sales_tax(skills: dict, base_tax: float=2.0) -> float
```

计算销售税率 (%)。委托 core.eve_formulas。

定义行：`173`

### `calc_max_orders`

```python
def calc_max_orders(skills: dict, base_orders: int=15) -> int
```

计算最大订单数。

定义行：`183`

### `format_pct`

```python
def format_pct(value: float) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`192`

### `apply_skill_queue_finished`

```python
def apply_skill_queue_finished(levels: dict[int, int], queue: list[dict], now: str) -> dict[int, int]
```

把技能队列里已练完的条目叠加到 `/skills` 的结果上。

定义行：`196`

### `merge_esi_skill_levels`

```python
def merge_esi_skill_levels(existing: dict[str, int], esi: dict[str, int], panel_names: list[str]) -> dict[str, int]
```

把 ESI 等级落到「面板能显示的名字 ∪ 配置里已有的名字」上。

定义行：`216`

### `union_skill_levels`

```python
def union_skill_levels(characters: dict, esi: dict[str, int], panel_names: list[str]) -> dict[str, int]
```

新导入角色的初始技能集 = 面板全集 ∪ 其它角色用过的技能名，等级取自 ESI。

定义行：`231`

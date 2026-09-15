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

定义行：`111`

### `calc_relist_discount`

```python
def calc_relist_discount(skills: dict) -> float
```

计算改单折扣 (%)。委托 core.eve_formulas。

定义行：`122`

### `calc_sales_tax`

```python
def calc_sales_tax(skills: dict, base_tax: float=2.0) -> float
```

计算销售税率 (%)。委托 core.eve_formulas。

定义行：`129`

### `calc_max_orders`

```python
def calc_max_orders(skills: dict, base_orders: int=15) -> int
```

计算最大订单数。

定义行：`139`

### `format_pct`

```python
def format_pct(value: float) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`148`

# services.refining_service

> 源文件 `services/refining_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

精炼价值计算

数据来源：reference.db reprocessing_materials（可精炼物料与产出）、
market.db 价格（经 PricingService）。产率公式 calc_refining_yield 在 core.eve_formulas。
被估算页 refine_worker 消费。

## 类

### `class RefiningService`

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`13`

#### 方法

##### `__init__`

```python
def __init__(self, db, pricing_service=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`14`
##### `filter_refinable`

```python
def filter_refinable(self, items: list[dict]) -> list[dict]
```

过滤出有精炼材料数据的物品。

定义行：`18`
##### `calc_value`

```python
def calc_value(self, type_id, quantity=1, *, skills=None, is_player_facility=False, price_hub='Jita', yield_override=None, ore_skill=0) -> dict
```

完整实现（从 scoring_service.py 迁移）

定义行：`32`

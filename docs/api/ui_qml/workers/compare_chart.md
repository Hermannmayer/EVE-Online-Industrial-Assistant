# ui_qml.workers.compare_chart

> 源文件 `ui_qml/workers/compare_chart.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

对比后台计算 — CompareWorker + 物品搜索/名称辅助函数

## 函数

### `search_items`

```python
def search_items(query: str) -> list[dict]
```

按名称/ID 搜索物品

定义行：`12`

### `item_name`

```python
def item_name(type_id: int) -> str
```

获取物品中文名（name_resolver 有 terminology 覆盖兜底）

定义行：`24`

## 类

### `class CompareWorker`（继承 `QThread`）

后台对比计算 Worker

定义行：`29`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict], mode: str, cfg: dict, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `cancel`

```python
def cancel(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`43`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `_calc_mfg`

```python
def _calc_mfg(self, tid: int, row: dict, char_cfg: dict | None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`82`
##### `_calc_trade`

```python
def _calc_trade(self, tid: int, row: dict, char_cfg: dict | None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`122`
##### `_calc_reaction`

```python
def _calc_reaction(self, tid: int, row: dict, char_cfg: dict | None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`146`

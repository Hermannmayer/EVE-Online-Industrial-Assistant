# ui_qml.workers.batch_price_workers

> 源文件 `ui_qml/workers/batch_price_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

批量查价的线程与搜索助手（原先在 `ui_pyside6/views/batch_price_dialog.py`）。

## 函数

### `_search_items`

```python
def _search_items(queries: list[str]) -> list[dict]
```

批量搜索物品，返回 [&#123;type_id, name, raw_query&#125;]

定义行：`115`

## 类

### `class BatchPriceWorker`（继承 `QThread`）

批量查价工作线程

定义行：`8`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict], parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`15`
##### `cancel`

```python
def cancel(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`
##### `_query_one`

```python
def _query_one(self, item: dict) -> dict
```

查询单个物品价格

定义行：`43`

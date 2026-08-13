# ui_pyside6.workers.all_items_workers

> 源文件 `ui_pyside6/workers/all_items_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

全物品市场 — 后台 Worker（市场树 / 物品列表 / 搜索）

## 函数

### `_fetch`

```python
def _fetch(sql, rid: int, params=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`

## 类

### `class TreeW`（继承 `QThread`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`48`

#### 方法

##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`51`

### `class ItemsW`（继承 `QThread`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`59`

#### 方法

##### `__init__`

```python
def __init__(self, ids=None, rid: int=0, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`62`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`67`

### `class SearchItemsW`（继承 `QThread`）

按名称/ID 搜索物品

定义行：`76`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, rid: int, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`81`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`

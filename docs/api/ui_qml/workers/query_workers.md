# ui_qml.workers.query_workers

> 源文件 `ui_qml/workers/query_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

查询页的取数线程（搜索 / 候选）。

原先在 `ui_pyside6/views/query/query_search.py`，QML 侧要用同一份，故拆出来。

## 类

### `class SearchWorker`（继承 `QThread`）

后台数据库搜索

定义行：`16`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, region_id: int=10000002, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`22`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`27`
##### `_db_search`

```python
def _db_search(self, query: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`38`
##### `_db_search_basic`

```python
def _db_search_basic(self, query: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`41`

### `class SuggestionWorker`（继承 `QThread`）

后台候选搜索

定义行：`45`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`50`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`54`

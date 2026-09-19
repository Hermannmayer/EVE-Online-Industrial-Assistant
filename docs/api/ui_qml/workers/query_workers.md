# ui_qml.workers.query_workers

> 源文件 `ui_qml/workers/query_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

查询页的取数线程（候选）。

原先在 `ui_pyside6/views/query/query_search.py`，QML 侧要用同一份，故拆出来。

**只剩候选一条**：结果表已按用户要求删除，页面形态变成「输入即出全部匹配，点一条出详情」，
所以按名字跑整表搜索的 `SearchWorker` 也随之删除（它连带让
`ui_data_service.query_search_items` / `_basic` 变成死代码，一并清掉）。

## 类

### `class SuggestionWorker`（继承 `QThread`）

后台候选搜索

定义行：`16`

#### 方法

##### `__init__`

```python
def __init__(self, query: str, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`21`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`

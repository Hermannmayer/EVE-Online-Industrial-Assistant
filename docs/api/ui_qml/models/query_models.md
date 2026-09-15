# ui_qml.models.query_models

> 源文件 `ui_qml/models/query_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

查询页的表格模型与展示规则（零 QtWidgets）。

原先都在 `ui_pyside6/views/query/query_search.py` —— 那个文件里还混着
SuggestionPopup（Widgets 悬浮候选）与页面级动作；随批次 6.0 把 QML 侧也要用的
部分拆到这里：列定义、表格模型、行格式化。

## 函数

### `format_search_rows`

```python
def format_search_rows(rows: list, is_fallback: bool) -> list[dict]
```

将数据库返回的行格式化为表格模型所需的字典列表

定义行：`155`

## 类

### `class QueryTableModel`（继承 `QAbstractTableModel`）

查询结果表格模型

定义行：`33`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`42`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`48`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`51`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`54`
##### `_get_display`

```python
def _get_display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`101`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`118`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`127`
##### `get_row`

```python
def get_row(self, row_idx: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`144`

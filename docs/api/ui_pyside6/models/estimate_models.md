# ui_pyside6.models.estimate_models

> 源文件 `ui_pyside6/models/estimate_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

估价页面 — 表格模型

## 类

### `class EstimateTableModel`（继承 `QAbstractTableModel`）

估价表格模型

定义行：`25`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`28`
##### `set_discount`

```python
def set_discount(self, discount: float)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`35`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`43`
##### `_recalc_totals`

```python
def _recalc_totals(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`50`
##### `add_row`

```python
def add_row(self, row_data: dict)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`60`
##### `remove_row`

```python
def remove_row(self, row_idx: int)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`71`
##### `clear_all`

```python
def clear_all(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`77`
##### `get_rows`

```python
def get_rows(self) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`89`
##### `flags`

```python
def flags(self, index)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`92`
##### `setData`

```python
def setData(self, index, value, role=Qt.ItemDataRole.EditRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`99`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`115`
##### `_get_display`

```python
def _get_display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`148`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`169`
##### `sort`

```python
def sort(self, column, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`179`

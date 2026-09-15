# ui_qml.models.watchlist_models

> 源文件 `ui_qml/models/watchlist_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

关注列表的列定义与表格模型（零 QtWidgets）。

原先在 `ui_pyside6/views/watchlist_view.py`，QML 侧复用同一份展示规则。

## 类

### `class WatchlistTableModel`（继承 `QAbstractTableModel`）

关注列表表格模型

定义行：`31`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`34`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`39`
##### `set_price_changes`

```python
def set_price_changes(self, changes: dict[int, dict])
```

设置价格变化数据用于行高亮

定义行：`44`
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

定义行：`131`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`161`

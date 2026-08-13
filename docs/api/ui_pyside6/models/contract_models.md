# ui_pyside6.models.contract_models

> 源文件 `ui_pyside6/models/contract_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同市场 — 表格模型 + 客户端过滤器（列表 / 物品）

## 类

### `class ContractTableModel`（继承 `QAbstractTableModel`）

合同列表表格模型

定义行：`61`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`64`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`70`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`76`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`79`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`82`
##### `_get_display`

```python
def _get_display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`124`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`153`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`162`
##### `get_row`

```python
def get_row(self, idx: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`176`

### `class ContractItemTableModel`（继承 `QAbstractTableModel`）

合同内物品表格模型

定义行：`195`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`198`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`202`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`207`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`210`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`213`
##### `_get_display`

```python
def _get_display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`242`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`263`

### `class ContractFilterProxy`（继承 `QSortFilterProxyModel`）

合同列表实时过滤器 — 按名称/价格/买卖类型

定义行：`269`

#### 方法

##### `__init__`

```python
def __init__(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`272`
##### `set_search_text`

```python
def set_search_text(self, text: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`280`
##### `set_price_range`

```python
def set_price_range(self, min_p: float, max_p: float) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`284`
##### `set_buy_sell`

```python
def set_buy_sell(self, mode: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`289`
##### `filterAcceptsRow`

```python
def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`293`

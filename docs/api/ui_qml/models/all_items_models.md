# ui_qml.models.all_items_models

> 源文件 `ui_qml/models/all_items_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

全物品市场 — 表格模型 + 排序代理

## 函数

### `display_text`

```python
def display_text(row: dict, key: str) -> str
```

单元格的显示文本（千分位 / `DASH` 占位）。

定义行：`47`

## 类

### `class AModel`（继承 `QAbstractTableModel`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`74`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`75`
##### `set_rows`

```python
def set_rows(self, r)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`80`
##### `set_cols`

```python
def set_cols(self, c)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`85`
##### `rowCount`

```python
def rowCount(self, p=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`90`
##### `columnCount`

```python
def columnCount(self, p=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`93`
##### `data`

```python
def data(self, idx, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`96`
##### `headerData`

```python
def headerData(self, s, o, r=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`134`

### `class Proxy`（继承 `QSortFilterProxyModel`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`140`

#### 方法

##### `lessThan`

```python
def lessThan(self, left, right)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`141`

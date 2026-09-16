# ui_qml.models.inventory_helpers

> 源文件 `ui_qml/models/inventory_helpers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

仓库页面 — 公共数据模型和常量

包含 InvTableModel 和 BlueprintTableModel。

## 类

### `class InvTableModel`（继承 `QAbstractTableModel`）

机库物品表格模型

定义行：`22`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`27`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`35`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`38`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`41`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`
##### `item_at`

```python
def item_at(self, row: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`91`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`94`
##### `_sort_key`

```python
def _sort_key(self, column: int) -> Callable[[dict], Any] | None
```

列的排序键（纯函数、不碰状态）。`None` = 该列不可排。

定义行：`104`
##### `reapply_sort`

```python
def reapply_sort(self) -> None
```

按**当前**排序设置重排 `self._items`。

定义行：`116`

### `class BlueprintTableModel`（继承 `QAbstractTableModel`）

蓝图表格模型

定义行：`140`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`157`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`164`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`167`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`170`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`244`
##### `row_at`

```python
def row_at(self, row: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`249`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`252`
##### `_sort_key`

```python
def _sort_key(self, column: int) -> Callable[[dict], Any] | None
```

列的排序键（纯函数、不碰状态）。`None` = 该列不可排。

定义行：`262`
##### `reapply_sort`

```python
def reapply_sort(self) -> None
```

按**当前**排序设置重排 `self._rows`。

定义行：`279`

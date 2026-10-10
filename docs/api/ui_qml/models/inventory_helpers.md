# ui_qml.models.inventory_helpers

> 源文件 `ui_qml/models/inventory_helpers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

仓库页面 — 公共数据模型和常量

包含 InvTableModel 和 BlueprintTableModel。

## 函数

### `item_gap`

```python
def item_gap(row: dict) -> int
```

缺口 = max(0, 规划占用 − 库存数量)。纯函数。

定义行：`22`

### `item_locked_isk`

```python
def item_locked_isk(row: dict) -> float
```

占用资金 = 单个成本记录 × 库存数量（成本价缺失/为 0 → 0）。纯函数。

定义行：`27`

### `price_unreliable`

```python
def price_unreliable(row: dict) -> bool
```

这一行的卖单价是否**有价但立不住**（三态里的 False；无价 None 不算）。纯函数。

定义行：`41`

### `price_credible_text`

```python
def price_credible_text(row: dict) -> str
```

「估值可信」列的显示串：无价 → `-`，不可信 → 警示，可信 → `可`。

定义行：`49`

### `blueprint_run_profit`

```python
def blueprint_run_profit(row: dict) -> float | None
```

每流程利润 = 销售收入 − 材料成本（任一侧缺失 → None）。

定义行：`61`

### `_profit_sort_key`

```python
def _profit_sort_key(row: dict) -> float
```

「每流程利润」的排序键：缺失沉底（与「利润率」列同口径）。

定义行：`74`

## 类

### `class InvTableModel`（继承 `QAbstractTableModel`）

机库物品表格模型

定义行：`85`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`101`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`109`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`112`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`115`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`176`
##### `item_at`

```python
def item_at(self, row: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`181`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`184`
##### `_sort_key`

```python
def _sort_key(self, column: int) -> Callable[[dict], Any] | None
```

列的排序键（纯函数、不碰状态）。`None` = 该列不可排。

定义行：`194`
##### `reapply_sort`

```python
def reapply_sort(self) -> None
```

按**当前**排序设置重排 `self._items`。

定义行：`208`

### `class BlueprintTableModel`（继承 `QAbstractTableModel`）

蓝图表格模型

定义行：`232`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`251`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`258`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`261`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`264`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`348`
##### `row_at`

```python
def row_at(self, row: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`353`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`356`
##### `_sort_key`

```python
def _sort_key(self, column: int) -> Callable[[dict], Any] | None
```

列的排序键（纯函数、不碰状态）。`None` = 该列不可排。

定义行：`366`
##### `reapply_sort`

```python
def reapply_sort(self) -> None
```

按**当前**排序设置重排 `self._rows`。

定义行：`385`

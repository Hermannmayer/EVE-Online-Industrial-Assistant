# ui_qml.models.trade_rank_model

> 源文件 `ui_qml/models/trade_rank_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

跨区域价差排行表的 QML 模型。

与 `AllItemsQmlModel` 同一套路：命名角色（`text` / `fg` / `iconUrl` / `alignRight`）
交给 QML，展示规则留在 Python 侧。**不继承 `all_items_models.AModel`** ——
它的 `data()` 绑死了 `BCOLS` 的字段键与千分位格式，且被全物品页共用，改它会连带改那边。

排序**不走 `all_items_models.Proxy`**：那个把每格转成字符串再 `float(replace(...))`
解析回来，本表稳定在 1.2 万行量级，会白格式化两万多次。这里直接按原始数值排。

## 函数

### `format_order_change`

```python
def format_order_change(per_day: float | None) -> str
```

挂单变化的显示文案。正数 = 挂单在减少（有人在吃单）。

定义行：`73`

### `_cell_text`

```python
def _cell_text(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`

## 类

### `class TradeRankQmlModel`（继承 `QAbstractTableModel`）

A → B 全品类价差排行：一个物品一行。

定义行：`103`

#### 方法

##### `__init__`

```python
def __init__(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`106`
##### `set_rows`

```python
def set_rows(self, rows: list[dict]) -> None
```

整体替换并套用当前排序（结果集变了要重排）。

定义行：`114`
##### `row_at`

```python
def row_at(self, r: int) -> dict
```

第 r 行的原始数据（桥据此取 type_id 加购物车）。

定义行：`120`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`124`
##### `rowCount`

```python
def rowCount(self, parent: QModelIndex | None=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`127`
##### `columnCount`

```python
def columnCount(self, parent: QModelIndex | None=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`130`
##### `headerData`

```python
def headerData(self, section: int, orientation: Qt.Orientation, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`133`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`144`
##### `_fg`

```python
def _fg(row: dict, col: int) -> str
```

只在「每方利润」「B侧挂单变化」两列给色，其余交给 QML 默认前景色。

定义行：`170`
##### `sortColumn`

```python
def sortColumn(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`188`
##### `sortDescending`

```python
def sortDescending(self) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`191`
##### `_sort_key`

```python
def _sort_key(self, row: dict)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`194`
##### `sort`

```python
def sort(self, column: int, order: Qt.SortOrder=Qt.SortOrder.AscendingOrder) -> None
```

点表头排序：**必须走模型重置**，不能只发 `layoutAboutToBeChanged/layoutChanged`。

定义行：`208`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

主题切换后补发 dataChanged（两列的颜色是算出来的字符串）。

定义行：`224`

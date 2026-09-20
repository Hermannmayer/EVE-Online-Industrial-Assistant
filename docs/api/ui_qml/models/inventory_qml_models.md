# ui_qml.models.inventory_qml_models

> 源文件 `ui_qml/models/inventory_qml_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

仓库页两张表的 QML 适配。

- `InvQmlModel`：机库物品（8 列）。数量类列右对齐、图标列取物品 PNG、
  「规划占用」带 tooltip。展示规则照搬 `InvTableModel.data()`。
- `BlueprintQmlModel`：蓝图（11 列）。「类型」列在被活跃计划占用时标橙、
  「利润率」列按正负染绿红。展示规则照搬 `BlueprintTableModel.data()`。

两个模型都补了 `set_rows`：原版每次刷新都**新建**模型实例
（`self._model = InvTableModel(items)`），QML 侧需要一个稳定实例 + 整体换数据。
换完必须 `reapply_sort()` —— 排序状态归模型所有（桥只读它画表头箭头），
刷新后不重排就会「表头还亮着 ▲、内容已经变回原始顺序」。

## 类

### `class InvQmlModel`（继承 `InvTableModel`）

机库物品表：命名角色 + 可整体换行。

定义行：`65`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict] | None=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`72`
##### `set_rows`

```python
def set_rows(self, items: list[dict]) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`76`
##### `rows`

```python
def rows(self) -> list[dict]
```

底层行数据（只读用途：桥排序后要按 id 找回选中行）。

定义行：`87`
##### `set_selection`

```python
def set_selection(self, rows: set[int]) -> None
```

把选中行灌进模型，只通知受影响的那段行。

定义行：`91`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`105`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`108`
##### `_display`

```python
def _display(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`131`

### `class BlueprintQmlModel`（继承 `BlueprintTableModel`）

蓝图表：命名角色 + 可整体换行。

定义行：`152`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict] | None=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`158`
##### `set_rows`

```python
def set_rows(self, rows: list[dict]) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`162`
##### `rows`

```python
def rows(self) -> list[dict]
```

底层行数据（只读用途：桥排序后要按 id 找回选中行）。

定义行：`173`
##### `set_selection`

```python
def set_selection(self, rows: set[int]) -> None
```

把选中行灌进模型，只通知受影响的那段行。

定义行：`177`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`191`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`194`
##### `_display`

```python
def _display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`224`
##### `_name`

```python
def _name(row: dict) -> str
```

与父类同一套取名口径（terminology 覆盖优先）。

定义行：`259`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`270`

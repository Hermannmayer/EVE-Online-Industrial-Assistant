# ui_pyside6.models.industry_models

> 源文件 `ui_pyside6/models/industry_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业制造 — Table Model 类

## 函数

### `_fmt_dhms`

```python
def _fmt_dhms(seconds) -> str
```

把秒格式化为 d/h/m

定义行：`9`

### `_remaining`

```python
def _remaining(p: dict, now: datetime | None=None) -> int | None
```

计划剩余秒（进行中）；非进行中/无 started_at 返回 None

定义行：`22`

### `_sort_key`

```python
def _sort_key(value)
```

列排序键：数值（含 bool）按大小、文本按小写，类型混合也不崩。

定义行：`29`

## 类

### `class PlanTableModel`（继承 `QAbstractTableModel`）

19 列生产计划模型 — 支持 checkbox、类别、图标、行内编辑、排序

定义行：`42`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`106`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`112`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`115`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`120`
##### `_display_text`

```python
def _display_text(self, p: dict, c: int) -> str
```

列 0~18 的 DisplayRole 文本

定义行：`131`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`200`
##### `flags`

```python
def flags(self, index)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`211`
##### `setData`

```python
def setData(self, index, value, role=Qt.ItemDataRole.EditRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`220`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`242`
##### `set_plans`

```python
def set_plans(self, plans: list[dict]) -> None
```

替换所有数据 — 保持同一个 model 实例，避免 setModel 清除选中

定义行：`258`
##### `get_plan`

```python
def get_plan(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`265`
##### `tick`

```python
def tick(self) -> list[int]
```

倒计时 tick：遍历进行中行算剩余；≤0 内存置 ready；对变动行 emit dataChanged。

定义行：`268`

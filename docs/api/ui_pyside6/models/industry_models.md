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

定义行：`14`

### `_remaining`

```python
def _remaining(p: dict, now: datetime | None=None) -> int | None
```

计划剩余秒（进行中）；非进行中/无 started_at 返回 None

定义行：`27`

## 类

### `class RankTableModel`（继承 `QAbstractTableModel`）

利润排行表模型

定义行：`34`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`39`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`43`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`72`
##### `get_row`

```python
def get_row(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`77`

### `class PlanTableModel`（继承 `QAbstractTableModel`）

18 列生产计划模型 — 支持 checkbox、图标、行内编辑、排序

定义行：`81`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`143`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`149`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`152`
##### `_load_icon`

```python
def _load_icon(self, type_id: int) -> QPixmap | None
```

从缓存或磁盘加载 32px 图标，失败返回 None

定义行：`157`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`177`
##### `_display_text`

```python
def _display_text(self, p: dict, c: int) -> str
```

列 0~17 的 DisplayRole 文本

定义行：`207`
##### `_foreground`

```python
def _foreground(self, p: dict, c: int)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`273`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`303`
##### `flags`

```python
def flags(self, index)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`314`
##### `setData`

```python
def setData(self, index, value, role=Qt.ItemDataRole.EditRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`323`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`350`
##### `set_plans`

```python
def set_plans(self, plans: list[dict]) -> None
```

替换所有数据 — 保持同一个 model 实例，避免 setModel 清除选中

定义行：`366`
##### `get_plan`

```python
def get_plan(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`373`
##### `tick`

```python
def tick(self) -> list[int]
```

倒计时 tick：遍历进行中行算剩余；≤0 内存置 ready；对变动行 emit dataChanged。

定义行：`376`

### `class MaterialTableModel`（继承 `QAbstractTableModel`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`408`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`411`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`415`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`418`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`421`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`435`

### `class ProcurementTableModel`（继承 `QAbstractTableModel`）

代采购表模型

定义行：`441`

#### 方法

##### `__init__`

```python
def __init__(self, items: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`451`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`455`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`458`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`461`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`495`
##### `get_item`

```python
def get_item(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`500`

### `class ProductionTableModel`（继承 `QAbstractTableModel`）

生产执行跟踪表模型 — 面向 production_plans 表的字段

定义行：`504`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`521`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`525`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`528`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`531`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`556`
##### `get_plan`

```python
def get_plan(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`561`

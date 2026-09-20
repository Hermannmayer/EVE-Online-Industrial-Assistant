# ui_qml.models.contract_models

> 源文件 `ui_qml/models/contract_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同市场 —— 三个子页各自的表格模型 + 物品明细模型。

**为什么是「一个模型 + 三份视图定义」而不是三个模型类**：三张表的行数据同源
（`services.contract_service` 的三个入口给出的都是扁平 dict），差别只在「显示哪几列、
怎么格式化、什么颜色」。写成三个类会把同一套 `set_rows`/`sort`/`roleNames` 抄三遍。

列定义与取值规则集中在本模块 —— 桥暴露给 QML 的列宽、QML 表格的 delegate 宽度、
点击命中区三处必须取同一份，各算一次必然错位。

## 函数

### `_valued`

```python
def _valued(row: dict) -> bool
```

内容物市价算得出来吗（有物品、且至少一件有价）。

定义行：`40`

### `_isk`

```python
def _isk(value: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`45`

### `_isk_signed`

```python
def _isk_signed(value: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

### `_pct_signed`

```python
def _pct_signed(value: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`55`

### `_m3`

```python
def _m3(value: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`

### `_count`

```python
def _count(value: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`63`

### `_remaining`

```python
def _remaining(seconds: Any) -> str
```

剩余时间 —— 合同最要紧的一列，跨天给「N天M小时」，一天内给「M小时」。

定义行：`67`

### `_place`

```python
def _place(station: Any, system: Any, security: Any) -> str
```

站点列 —— 站名与星系都给（同名站点遍布新伊甸，只给站名会认错地方）。

定义行：`82`

### `_render_auction`

```python
def _render_auction(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`107`

### `_render_exchange`

```python
def _render_exchange(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`148`

### `_render_courier`

```python
def _render_courier(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`202`

## 类

### `class ContractView`

一张合同表的列定义与取值规则。

定义行：`91`

### `class ContractTableModel`（继承 `QAbstractTableModel`）

一张合同表 —— 外观由传入的 `ContractView` 决定。

定义行：`268`

#### 方法

##### `__init__`

```python
def __init__(self, view: ContractView, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`271`
##### `view`

```python
def view(self) -> ContractView
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`279`
##### `set_rows`

```python
def set_rows(self, rows: list[dict]) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`282`
##### `notifyReset`

```python
def notifyReset(self) -> None
```

把当前行原样重播一次（触发模型重置）。

定义行：`289`
##### `get_row`

```python
def get_row(self, idx: int) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`301`
##### `rowCount`

```python
def rowCount(self, parent=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`304`
##### `columnCount`

```python
def columnCount(self, parent=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`307`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`310`
##### `_fg`

```python
def _fg(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`313`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`321`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`341`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`351`

### `class ContractItemTableModel`（继承 `QAbstractTableModel`）

合同内物品明细（含市场单价与小计）。

定义行：`430`

#### 方法

##### `__init__`

```python
def __init__(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`433`
##### `set_rows`

```python
def set_rows(self, rows: list[dict]) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`437`
##### `rowCount`

```python
def rowCount(self, parent=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`442`
##### `columnCount`

```python
def columnCount(self, parent=None) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`445`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`448`
##### `_display`

```python
def _display(self, row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`451`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`468`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`486`

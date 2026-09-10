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

21 列生产计划模型 — 支持 checkbox、类别、图标、行内编辑、排序；末两列为科研（成功率/解码器）

定义行：`42`

#### 方法

##### `__init__`

```python
def __init__(self, plans: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`110`
##### `toggle_collapse`

```python
def toggle_collapse(self, group_id: int) -> None
```

切换指定组的折叠状态

定义行：`119`
##### `_is_visible`

```python
def _is_visible(self, plan: dict) -> bool
```

判断行是否可见（未被折叠隐藏）

定义行：`128`
##### `_is_shared_root_collapsed`

```python
def _is_shared_root_collapsed(self) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`141`
##### `_visible_plans`

```python
def _visible_plans(self) -> list[dict]
```

返回过滤后的可见行列表

定义行：`144`
##### `_has_children`

```python
def _has_children(self, group_id: int) -> bool
```

判断指定 group 是否有子项（含 -1 共享区）。

定义行：`148`
##### `_row_map`

```python
def _row_map(self, filtered_row: int) -> int
```

过滤行号 → 原始行号映射

定义行：`158`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`169`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`174`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`179`
##### `_display_text`

```python
def _display_text(self, p: dict, c: int) -> str
```

列 0~18 的 DisplayRole 文本

定义行：`191`
##### `_success_rate_text`

```python
def _success_rate_text(p: dict) -> str
```

成功率列：用户手填优先（实填值），否则显示评分算出的值并标「预计」。

定义行：`288`
##### `_decryptor_text`

```python
def _decryptor_text(p: dict) -> str
```

解码器列：发明行显示解码器名（无 → —）。

定义行：`317`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`329`
##### `flags`

```python
def flags(self, index)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`340`
##### `setData`

```python
def setData(self, index, value, role=Qt.ItemDataRole.EditRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`350`
##### `sort`

```python
def sort(self, column: int, order=Qt.SortOrder.AscendingOrder)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`394`
##### `set_plans`

```python
def set_plans(self, plans: list[dict]) -> None
```

替换所有数据 — 保持同一个 model 实例，避免 setModel 清除选中

定义行：`410`
##### `get_plan`

```python
def get_plan(self, row: int) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`417`
##### `tick`

```python
def tick(self) -> list[int]
```

倒计时 tick：遍历进行中行算剩余；≤0 内存置 ready；对变动行 emit dataChanged。

定义行：`421`

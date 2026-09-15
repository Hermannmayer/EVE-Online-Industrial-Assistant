# ui_qml.models.trade_qml_model

> 源文件 `ui_qml/models/trade_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

跨区域价格对比表的 QML 适配。

与 `QueryQmlModel` / `PlanQmlModel` 同一套路：`TradeHubTableModel` 的展示规则
（价差% 染色、图标列、右对齐）保持不变，这里只补**命名角色**并让行数据可整体替换
（原版模型是构造时传 `rows` 的不可变形态，QML 侧需要一个稳定实例）。

## 函数

### `_icon_url`

```python
def _icon_url(type_id: Any) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`106`

## 类

### `class TradeHubQmlModel`（继承 `TradeHubTableModel`）

跨区域价格表：命名角色 + 可整体替换行。

定义行：`41`

#### 方法

##### `__init__`

```python
def __init__(self, rows: list[dict] | None=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`44`
##### `set_rows`

```python
def set_rows(self, rows: list[dict]) -> None
```

整体替换行（原版每次分析都新建模型，QML 侧复用同一实例）。

定义行：`47`
##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`53`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`56`
##### `_display`

```python
def _display(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

主题切换后补发 dataChanged（价差% 的颜色是算出来的字符串）。

定义行：`95`

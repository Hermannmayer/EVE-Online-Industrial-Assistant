# ui_qml.models.watchlist_qml_model

> 源文件 `ui_qml/models/watchlist_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

关注列表（价格监控）表的 QML 适配。

`WatchlistTableModel` 的展示规则（买卖价染色、价差% 橙、价格变化/阈值触发的行底色、
金额列右对齐 + 等宽）保持不变，这里只补**命名角色**。

底色带 alpha（价格变化用 50/255 的绿/红叠加），所以必须是 `#aarrggbb` 形式 ——
QML 的 `color` 能解析它，而 `#rrggbb` 会丢掉透明度、把整行糊成实心色。

## 函数

### `_tint`

```python
def _tint(name: str) -> str
```

带透明度的主题色的 `#aarrggbb` 形式。

定义行：`52`

## 类

### `class WatchlistQmlModel`（继承 `WatchlistTableModel`）

关注列表：命名角色（行数据与刷新仍走父类）。

定义行：`61`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`64`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`67`
##### `_fg`

```python
def _fg(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`96`
##### `_bg`

```python
def _bg(self, row: dict, row_index: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`108`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

主题切换 / 价格变化后补发 dataChanged（颜色都是算出来的字符串）。

定义行：`135`

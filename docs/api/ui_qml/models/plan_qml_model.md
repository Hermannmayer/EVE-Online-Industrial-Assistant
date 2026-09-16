# ui_qml.models.plan_qml_model

> 源文件 `ui_qml/models/plan_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

`PlanTableModel` → QML 可消费形式。

与 `estimate_qml_model` 同一套适配思路（QML 只认命名角色、渲染不了 `QPixmap`），
但生产计划表有 21 列且每列的渲染方式都不同，因此这里**不按列开角色**，而是把
Widgets 版 delegate 的展示职责折成几个「按索引取值」的角色：

| 角色 | 说明 |
|---|---|
| `text` | 该单元格的显示文本（等价 `DisplayRole`，逐列计算） |
| `fg` | 该单元格的前景色，空串 = 用默认色 |
| `bg` | 该单元格的底色（类别染色），空串 = 无 |
| `iconUrl` | 该单元格的图标（`file://` URL），空串 = 无 |
| `iconColor` | SVG 图标的染色值 |
| `checked` | 备料勾选列的勾选态 |
| … | 见 `ROLE_NAMES` |

关键点：角色名是固定的，但 `data()` 拿得到完整 index，**列信息在取值时才算**，
所以一个 `text` 角色就能覆盖 21 列，QML delegate 里不必写 21 路 switch。

颜色以**已解析的 hex 字符串**返回而非 token 名：QML 侧拿 token 名字符串做属性查表
（`Theme[name]`）无法参与依赖追踪，主题切换时不会重绘；改为表在主题变更时调
`refresh_colors()` 统一补发 `dataChanged`（见 `PlanTable._on_theme_changed`）。
hex 本身仍全部来自 `ui_qml.theme.registry`，不违反「配色只在 theme」的铁律。

## 函数

### `phosphor_url`

```python
def phosphor_url(filename: str, color: str, size: int=16) -> str
```

Phosphor SVG 的 `image://phosphor/...` URL（颜色与尺寸编进查询串）。

定义行：`100`

### `_png_url`

```python
def _png_url(type_id: Any) -> str
```

物品图标（磁盘上的 PNG）URL。

定义行：`113`

### `_token`

```python
def _token(name: str) -> str
```

按 token 名取当前主题色值。

定义行：`123`

### `_tint`

```python
def _tint(name: str) -> str
```

类别色 → 带透明度的 `#AARRGGBB`（QML 的 color 认这个格式）。

定义行：`134`

## 类

### `class PlanQmlModel`（继承 `PlanTableModel`）

生产计划模型 + QML 命名角色。数据/排序/折叠逻辑全在父类。

定义行：`143`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`149`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`154`
##### `_plan_at`

```python
def _plan_at(self, row: int) -> dict
```

过滤行号 → 行 dict（折叠时经 `_row_map` 映射）。

定义行：`200`
##### `_fg`

```python
def _fg(self, p: dict, c: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`207`
##### `_icon_url`

```python
def _icon_url(self, p: dict, c: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`245`
##### `_fold_state`

```python
def _fold_state(self, p: dict) -> str
```

产品列的折叠态：`""` 无可折叠 | `expanded` | `collapsed`。

定义行：`255`
##### `_display_text`

```python
def _display_text(self, p: dict, c: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`270`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

主题切换后重算所有单元格颜色（`fg`/`bg`/`iconColor` 是已解析的 hex）。

定义行：`278`
##### `refresh_status_column`

```python
def refresh_status_column(self) -> None
```

只重发**状态列** —— 缺料标注变了时用，不为一行把全表刷一遍。

定义行：`285`
##### `sort`

```python
def sort(self, column: int, order: Qt.SortOrder=Qt.SortOrder.AscendingOrder) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`302`
##### `sort_column`

```python
def sort_column(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`307`
##### `sort_ascending`

```python
def sort_ascending(self) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`311`

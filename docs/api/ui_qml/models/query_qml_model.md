# ui_qml.models.query_qml_model

> 源文件 `ui_qml/models/query_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品查询结果表的 QML 适配。

QML 的 `TableView` 只认**命名角色**（没有 DisplayRole/ForegroundRole 那套约定），
而这张表的展示规则已经写在 `QueryTableModel.data()` 里 —— 本类只做
「角色名 → 那一次 data() 取值的等价计算」的映射，不复制任何业务逻辑，
`set_rows` / `sort` / `get_row` 全部沿用父类实现。

与 `PlanQmlModel` 同一套路（见该文件头部说明）。

## 函数

### `_token`

```python
def _token(name: str) -> str
```

按 token 名取当前主题色值。

定义行：`57`

### `icon_url`

```python
def icon_url(type_id: Any) -> str
```

物品图标（磁盘上的 PNG）URL；没有缓存文件时返回空串。

定义行：`62`

## 类

### `class QueryQmlModel`（继承 `QueryTableModel`）

给 `QueryTableModel` 补命名角色，供 QML `TableView` + delegate 使用。

定义行：`72`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`75`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`78`
##### `_fg`

```python
def _fg(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`109`
##### `_bg`

```python
def _bg(row: dict, row_index: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`117`
##### `sort_column`

```python
def sort_column(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`125`
##### `sort_ascending`

```python
def sort_ascending(self) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`129`
##### `refresh_colors`

```python
def refresh_colors(self) -> None
```

主题切换后补发 dataChanged —— 颜色是算出来的字符串，QML 绑定不会自己重算。

定义行：`132`

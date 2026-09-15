# ui_qml.models.compare_models

> 源文件 `ui_qml/models/compare_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

对比结果的数据模型与格式化（零 QtWidgets）。

`CompareTableModel` 原先在 `ui_pyside6/views/compare/compare_models.py`，
同一文件里还混着对话框的 QSS 构建；随批次 6.0 把「模型 + 纯格式化」拆出来，
因为 QML 侧（`ui_qml/models/compare_qml_model.py`）也要用这一份展示规则。
QSS 那一半留在原处（它只服务 Widgets 对话框）。

## 函数

### `_format_isk`

```python
def _format_isk(value: float) -> str
```

格式化 ISK 金额

定义行：`164`

## 类

### `class CompareTableModel`（继承 `QAbstractTableModel`）

对比结果表格模型

定义行：`43`

#### 方法

##### `__init__`

```python
def __init__(self, mode: str='mfg')
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `_get_cols`

```python
def _get_cols(self) -> list[tuple]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`52`
##### `set_mode`

```python
def set_mode(self, mode: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`
##### `set_rows`

```python
def set_rows(self, rows: list[dict])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`65`
##### `rowCount`

```python
def rowCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`70`
##### `columnCount`

```python
def columnCount(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`73`
##### `data`

```python
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`76`
##### `headerData`

```python
def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`140`
##### `get_export_data`

```python
def get_export_data(self) -> list[list]
```

导出 CSV 数据

定义行：`146`

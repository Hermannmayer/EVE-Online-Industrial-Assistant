# ui_qml.models.estimate_qml_model

> 源文件 `ui_qml/models/estimate_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

把 `ui_pyside6` 的表格模型适配成 QML 可消费的形式。

**这是所有表格迁移的样板。** QML 的 `TableView` 与 QWidgets 的 `QTableView`
对模型的要求差两点，本模块就是补这两点：

1. **QML 只认命名角色**：QWidgets 用 `Qt.DisplayRole`/`DecorationRole` 这类枚举，
   QML 的 delegate 却要写 `model.name`、`model.qtyText`，因此必须提供 `roleNames()`。
2. **QML 渲染不了 `QPixmap`**：`DecorationRole` 返回的 `QPixmap` 在 QML 里拿不到，
   这里改为给**图标文件的 URL**（图标本来就是磁盘上的 PNG，QML 的 `Image`
   直接吃 URL，还能用 QML 自带的图片缓存）。

做法是**继承**原模型而不是包装：原模型的 `_rows`/`_recalc_totals`/`sort` 等逻辑
全部复用，QWidgets 视图（`data(DisplayRole)` 等）也照常工作——迁移期两个视图
可以共用同一个模型实例。

## 函数

### `_icon_url`

```python
def _icon_url(type_id: Any) -> str
```

图标文件 URL；文件不存在返回空串。

定义行：`55`

## 类

### `class EstimateQmlModel`（继承 `EstimateTableModel`）

估价表格模型 + QML 命名角色。逻辑全在父类，这里只补角色。

定义行：`69`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`74`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`77`
##### `sort`

```python
def sort(self, column: int, order: Qt.SortOrder=Qt.SortOrder.AscendingOrder) -> None
```

排序后行号全变，必须让 QML 重新拉取 rowIndex。

定义行：`111`

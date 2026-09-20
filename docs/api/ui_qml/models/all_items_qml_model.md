# ui_qml.models.all_items_qml_model

> 源文件 `ui_qml/models/all_items_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

全物品市场表的 QML 适配（阶段 4b）。

对照 Widgets 版 `ui_pyside6/models/all_items_models.py::AModel` —— **展示规则一行都不重写**：
千分位、破折号占位（`DASH`）、收益等级（`_tag`）染色、利润率正负染色、金额列右对齐、
图标列的 `DecorationRole`，全部仍走父类 `data()`，本类只补**命名角色**（QML 读不到
Qt 那几个无名角色）。

排序同样仍走既有的 `Proxy`（`QSortFilterProxyModel` + 自定义 `lessThan`：收益列按
S>A>B>C>D>✗ 的等级排，其余按去掉千分位后的数值排）。`QSortFilterProxyModel` 会把源模型的
`roleNames()` 转发下去，所以 QML 直接把**代理**当 model 用即可 —— 排序口径一份都不用重写。

## 类

### `class AllItemsQmlModel`（继承 `AModel`）

全物品表：命名角色（文本与配色仍由父类算）。

定义行：`43`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`

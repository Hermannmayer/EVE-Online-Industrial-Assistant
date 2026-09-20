# ui_qml.models.compare_qml_model

> 源文件 `ui_qml/models/compare_qml_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

对比结果表的 QML 适配（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/compare/compare_models.py::CompareTableModel` ——
**展示规则一行都不重写**：ISK 缩写、利润率百分号、状态中文、利润正负染色、
金额列右对齐、物品列图标，全部仍走父类 `data()`，本类只补**命名角色**。

子类化而不是另写一份，是因为这些规则原本就只该有一份实现：另写一份
`compare_rows()` 就多出一个「改了 Widgets 版忘了改 QML 版」的分裂点。
与 `WatchlistQmlModel` 同一套路。

`roleNames()` 里的 `text` 角色同时供 `HorizontalHeaderView` 的 `textRole` 使用
（表头与单元格共用一个角色名，Qt 的 header 只读它拿不到的列标题，无妨）。

## 类

### `class CompareQmlModel`（继承 `CompareTableModel`）

对比结果表：命名角色（行数据与展示规则仍走父类）。

定义行：`47`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`50`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`53`

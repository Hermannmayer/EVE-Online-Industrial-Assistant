# ui_qml.models.contract_qml_models

> 源文件 `ui_qml/models/contract_qml_models.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同页两张表的 QML 适配。

- `ContractQmlModel` / `ContractItemQmlModel`：给既有模型补**命名角色**，
  展示规则（价格绿、抵押橙、状态按语义染色、金额列右对齐 + 等宽）保持不动；
- 过滤仍走既有的 `ContractFilterProxy` —— `QSortFilterProxyModel` 会把源模型的
  `roleNames()` 转发下去，所以 QML 直接把**代理**当 model 用即可，
  过滤逻辑一份都不用重写。

## 类

### `class ContractQmlModel`（继承 `ContractTableModel`）

合同列表：命名角色。

定义行：`50`

#### 方法

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
##### `_fg`

```python
def _fg(row: dict, col: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`79`

### `class ContractItemQmlModel`（继承 `ContractItemTableModel`）

合同内物品：命名角色（数量列右对齐）。

定义行：`94`

#### 方法

##### `roleNames`

```python
def roleNames(self) -> dict[int, bytes]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`97`
##### `data`

```python
def data(self, index: QModelIndex, role: int=Qt.ItemDataRole.DisplayRole) -> Any
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`100`

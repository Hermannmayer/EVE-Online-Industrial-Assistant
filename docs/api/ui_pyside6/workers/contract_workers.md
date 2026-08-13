# ui_pyside6.workers.contract_workers

> 源文件 `ui_pyside6/workers/contract_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同市场 — 后台 Worker 线程

## 类

### `class ContractFetchWorker`（继承 `QThread`）

后台拉取公开合同数据

定义行：`8`

#### 方法

##### `__init__`

```python
def __init__(self, regions: list[str] | None=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`13`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`17`

### `class ContractLoadWorker`（继承 `QThread`）

后台从数据库加载合同列表

定义行：`27`

#### 方法

##### `__init__`

```python
def __init__(self, region_id: int, contract_type: str, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`32`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`37`

### `class ContractItemsLoadWorker`（继承 `QThread`）

后台从数据库加载合同物品

定义行：`55`

#### 方法

##### `__init__`

```python
def __init__(self, contract_id: int, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`60`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`64`

# ui_pyside6.workers.init_workers

> 源文件 `ui_pyside6/workers/init_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

初始化步骤 Worker — QThread 包装 InitService，供 InitWizard 使用

## 类

### `class InitServiceWorker`（继承 `QThread`）

QThread wrapper — 在后台线程运行 InitService，支持全流程或单步执行

定义行：`15`

#### 方法

##### `__init__`

```python
def __init__(self, step_keys: list[str] | None=None, parent: QThread | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`30`
##### `run`

```python
def run(self)
```

在后台线程中执行初始化

定义行：`35`
##### `_relay_signals`

```python
def _relay_signals(self)
```

将 InitService 的 Qt 信号转发到本 Worker 的信号

定义行：`41`
##### `cancel`

```python
def cancel(self)
```

取消初始化

定义行：`54`
##### `retry`

```python
def retry(self, step_key: str)
```

重试单个步骤

定义行：`58`
##### `retry_all_failed`

```python
def retry_all_failed(self)
```

重试所有失败步骤

定义行：`62`
##### `skip`

```python
def skip(self, step_key: str) -> bool
```

跳过非关键步骤

定义行：`66`
##### `get_status`

```python
def get_status(self) -> dict
```

获取步骤状态快照

定义行：`70`
##### `get_errors`

```python
def get_errors(self) -> dict[str, str]
```

获取错误信息

定义行：`74`
##### `check_network`

```python
async def check_network(self) -> bool
```

检查网络连通性

定义行：`78`

### `class _SingleStepWorker`（继承 `InitServiceWorker`）

单个初始化步骤的专用 Worker 基类

定义行：`85`

#### 方法

##### `__init__`

```python
def __init__(self, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`88`

### `class ItemsWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`92`

### `class PricesWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`96`

### `class BlueprintsWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`100`

### `class ImplantsWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`104`

### `class IconsWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`108`

### `class IndustryWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`112`

### `class SdeDataWorker`（继承 `_SingleStepWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`116`

# services.init_service

> 源文件 `services/init_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

初始化流程控制器 — 状态管理 + 进度信号 + 重试/跳过

## 函数

### `_noop`

```python
def _noop(*args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`

### `is_step_satisfied`

```python
def is_step_satisfied(step_key: str) -> bool
```

检查某步骤是否已就绪（数据是否存在）

定义行：`93`

### `get_missing_steps`

```python
def get_missing_steps() -> list[InitStep]
```

返回所有未就绪的步骤（check_all 只跑一次，避免 8 次重复查询）

定义行：`101`

### `get_missing_count`

```python
def get_missing_count() -> int
```

返回未就绪的步骤数

定义行：`109`

## 类

### `class InitStep`

单个初始化步骤的元信息

定义行：`39`

### `class StepStatus`（继承 `Enum`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`49`

### `class InitService`（继承 `QObject`）

初始化流程控制器

定义行：`119`

#### 方法

##### `__init__`

```python
def __init__(self, parent: QObject | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`143`
##### `start`

```python
def start(self, step_keys: list[str] | None=None)
```

开始初始化

定义行：`167`
##### `retry`

```python
def retry(self, step_key: str)
```

重试单个失败步骤

定义行：`191`
##### `retry_all_failed`

```python
def retry_all_failed(self)
```

重试所有失败步骤

定义行：`199`
##### `skip`

```python
def skip(self, step_key: str) -> bool
```

跳过非关键步骤。返回 True 表示跳过成功。

定义行：`209`
##### `cancel`

```python
def cancel(self)
```

取消当前执行（并行时取消所有正在运行的步骤）

定义行：`222`
##### `get_status`

```python
def get_status(self) -> dict[str, StepStatus]
```

返回所有步骤的当前状态

定义行：`228`
##### `get_errors`

```python
def get_errors(self) -> dict[str, str]
```

返回所有失败步骤的错误消息

定义行：`232`
##### `reset`

```python
def reset(self)
```

重置所有步骤为 PENDING

定义行：`236`
##### `check_network`

```python
async def check_network(self) -> bool
```

检查 ESI 连通性（带重试：网络抖动/慢响应不误判为不可用）。

定义行：`248`
##### `_run_sequence`

```python
async def _run_sequence(self, keys: list[str])
```

按依赖图并行执行步骤列表。

定义行：`279`
##### `_run_one`

```python
async def _run_one(self, key: str)
```

单个步骤任务：等依赖 → 网络检查 → 执行 → 上报（可并行运行）

定义行：`321`
##### `_ensure_net_once`

```python
async def _ensure_net_once(self) -> bool
```

网络检查单飞：并发请求合并为一次 check_network，结果共享。

定义行：`381`
##### `_prepare_ref_db_for_parallel`

```python
def _prepare_ref_db_for_parallel()
```

并行前准备 reference.db：WAL + 长 busy_timeout。

定义行：`388`
##### `_deps_satisfied`

```python
def _deps_satisfied(self, step: InitStep) -> bool
```

检查前置步骤是否已完成。

定义行：`408`
##### `_run_step`

```python
async def _run_step(self, key: str) -> tuple[bool, str]
```

实际执行一个初始化步骤

定义行：`426`
##### `_inject_progress_callback`

```python
def _inject_progress_callback(self, key: str)
```

设置进度回调环境变量（给 write_progress 使用）

定义行：`487`
##### `_emit_step_started`

```python
def _emit_step_started(self, key: str, name: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`496`
##### `_emit_step_progress`

```python
def _emit_step_progress(self, key: str, percent: int, message: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`503`
##### `_emit_step_completed`

```python
def _emit_step_completed(self, key: str, success: bool, message: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`510`
##### `_emit_all_completed`

```python
def _emit_all_completed(self, success: bool, summary: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`517`
##### `_emit_network`

```python
def _emit_network(self, ok: bool, message: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`524`

# core.single_instance

> 源文件 `core/single_instance.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Single-instance lock using PID file.

## 函数

### `try_lock`

```python
def try_lock(force: bool=False) -> bool
```

Attempt to acquire the single-instance lock.

定义行：`9`

### `_is_pid_alive`

```python
def _is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`39`

### `_win32_is_pid_alive`

```python
def _win32_is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`51`

### `unlock`

```python
def unlock()
```

Release the single-instance lock.

定义行：`72`

### `show_message`

```python
def show_message()
```

Print a notice to stderr that another instance is already running.

定义行：`80`

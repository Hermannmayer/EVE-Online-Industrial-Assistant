# core.single_instance

> 源文件 `core/single_instance.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Single-instance lock using PID file.

## 函数

### `_resolve`

```python
def _resolve(lock_file: Path | str | None) -> Path
```

None → 默认 instance.lock;str → Path 归一化(Path(Path) 幂等)。

定义行：`22`

### `_mutex_name`

```python
def _mutex_name(target: Path) -> str
```

锁文件路径 → 命名互斥体名。

定义行：`27`

### `_acquire_mutex`

```python
def _acquire_mutex(name: str) -> bool | None
```

获取 Windows 命名互斥体。

定义行：`37`

### `_release_mutex`

```python
def _release_mutex(name: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`67`

### `try_lock`

```python
def try_lock(force: bool=False, lock_file: Path | str | None=None) -> bool
```

Attempt to acquire the single-instance lock.

定义行：`79`

### `_try_exclusive_acquire`

```python
def _try_exclusive_acquire(own_pid: int, target: Path) -> bool | None
```

原子创建锁文件（O_EXCL），消除 check-then-act 竞态。

定义行：`139`

### `_safe_unlink`

```python
def _safe_unlink(target: Path)
```

删除锁文件；删除失败（句柄被占用）时不抛出。

定义行：`160`

### `_is_pid_alive`

```python
def _is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`168`

### `_win32_is_pid_alive`

```python
def _win32_is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`180`

### `unlock`

```python
def unlock(lock_file: Path | str | None=None)
```

Release the single-instance lock.

定义行：`201`

### `show_message`

```python
def show_message()
```

Print a notice to stderr that another instance is already running.

定义行：`215`

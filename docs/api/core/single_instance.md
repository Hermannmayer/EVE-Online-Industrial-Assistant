# core.single_instance

> 源文件 `core/single_instance.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

Single-instance lock using PID file.

默认锁文件为 `~/.eve-assistant/instance.lock`(Main.py 使用)。可传入自定义
`lock_file` 加独立锁,例如 dev.py 用 `~/.eve-assistant/dev.lock`——启动器与
应用实例的锁必须分离,二者才能共存。

## 函数

### `_resolve`

```python
def _resolve(lock_file: Path | str | None) -> Path
```

None → 默认 instance.lock;str → Path 归一化(Path(Path) 幂等)。

定义行：`25`

### `_mutex_name`

```python
def _mutex_name(target: Path) -> str
```

锁文件路径 → 命名互斥体名。

定义行：`30`

### `_acquire_mutex`

```python
def _acquire_mutex(name: str) -> bool | None
```

获取 Windows 命名互斥体。

定义行：`40`

### `_release_mutex`

```python
def _release_mutex(name: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`70`

### `try_lock`

```python
def try_lock(force: bool=False, lock_file: Path | str | None=None) -> bool
```

Attempt to acquire the single-instance lock.

定义行：`82`

### `_try_exclusive_acquire`

```python
def _try_exclusive_acquire(own_pid: int, target: Path) -> bool | None
```

原子创建锁文件（O_EXCL），消除 check-then-act 竞态。

定义行：`150`

### `_safe_unlink`

```python
def _safe_unlink(target: Path)
```

删除锁文件；删除失败（句柄被占用）时不抛出。

定义行：`171`

### `_is_pid_alive`

```python
def _is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`179`

### `_win32_is_pid_alive`

```python
def _win32_is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`191`

### `unlock`

```python
def unlock(lock_file: Path | str | None=None)
```

Release the single-instance lock.

定义行：`212`

### `show_message`

```python
def show_message()
```

Print a notice to stderr that another instance is already running.

定义行：`231`

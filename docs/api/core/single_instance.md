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

定义行：`16`

### `try_lock`

```python
def try_lock(force: bool=False, lock_file: Path | str | None=None) -> bool
```

Attempt to acquire the single-instance lock.

定义行：`21`

### `_acquire`

```python
def _acquire(own_pid: int, target: Path) -> bool
```

写入锁文件；失败时降级为允许运行，避免 Windows 瞬时锁冲突导致启动崩溃。

定义行：`56`

### `_safe_unlink`

```python
def _safe_unlink(target: Path)
```

删除锁文件；删除失败（句柄被占用）时不抛出。

定义行：`66`

### `_is_pid_alive`

```python
def _is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`74`

### `_win32_is_pid_alive`

```python
def _win32_is_pid_alive(pid: int) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`

### `unlock`

```python
def unlock(lock_file: Path | str | None=None)
```

Release the single-instance lock.

定义行：`107`

### `show_message`

```python
def show_message()
```

Print a notice to stderr that another instance is already running.

定义行：`120`

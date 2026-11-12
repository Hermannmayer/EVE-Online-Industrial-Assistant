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

定义行：`29`

### `_mutex_name`

```python
def _mutex_name(target: Path) -> str
```

锁文件路径 → 命名互斥体名。

定义行：`34`

### `_acquire_mutex`

```python
def _acquire_mutex(name: str) -> bool | None
```

获取 Windows 命名互斥体。

定义行：`44`

### `_release_mutex`

```python
def _release_mutex(name: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`74`

### `try_lock`

```python
def try_lock(force: bool=False, lock_file: Path | str | None=None) -> bool
```

Attempt to acquire the single-instance lock.

定义行：`88`

### `_try_exclusive_acquire`

```python
def _try_exclusive_acquire(own_pid: int, target: Path) -> bool | None
```

原子创建锁文件（O_EXCL），消除 check-then-act 竞态。

定义行：`156`

### `_safe_unlink`

```python
def _safe_unlink(target: Path)
```

删除锁文件；删除失败（句柄被占用）时不抛出。

定义行：`177`

### `_is_pid_alive`

```python
def _is_pid_alive(pid: int) -> bool
```

探活：pid 对应的进程是否还在。

定义行：`185`

### `_win32_is_pid_alive`

```python
def _win32_is_pid_alive(pid: int) -> bool
```

Win32 探活：打不开句柄要区分「进程不存在」与「权限不足」。

定义行：`210`

### `_win32_process_start_time`

```python
def _win32_process_start_time(pid: int) -> float | None
```

pid 对应进程的创建时刻（epoch 秒）；非 Windows 或查不到时返回 None。

定义行：`242`

### `_lock_payload`

```python
def _lock_payload(pid: int) -> str
```

锁文件内容：`&#123;pid&#125;:&#123;os.name&#125;:&#123;进程创建时刻&#125;`（取不到创建时刻时第三段写 `-`）。

定义行：`297`

### `_parse_lock`

```python
def _parse_lock(data: str) -> tuple[int, float | None]
```

解析锁文件内容 → `(pid, 创建时刻或 None)`。

定义行：`303`

### `_is_reused_pid`

```python
def _is_reused_pid(pid: int, stored_start: float | None) -> bool
```

锁里的 pid 虽然活着，但它**不是**写锁的那个进程吧？—— PID 复用判定。

定义行：`320`

### `unlock`

```python
def unlock(lock_file: Path | str | None=None)
```

Release the single-instance lock.

定义行：`336`

### `show_message`

```python
def show_message()
```

Print a notice to stderr that another instance is already running.

定义行：`355`

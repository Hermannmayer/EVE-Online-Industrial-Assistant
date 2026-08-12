# services.db_locks

> 源文件 `services/db_locks.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

并行初始化时对同一 SQLite 库的写操作串行化。

## 函数

### `get_db_write_lock`

```python
def get_db_write_lock(alias: str) -> asyncio.Lock
```

返回指定库的写锁（惰性创建，同一事件循环内所有写者共享）

定义行：`18`

### `reset_db_locks`

```python
def reset_db_locks() -> None
```

清空所有写锁（每次 asyncio.run 前调用，避免跨事件循环复用）

定义行：`27`

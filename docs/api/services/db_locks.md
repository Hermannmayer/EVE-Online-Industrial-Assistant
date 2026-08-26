# services.db_locks

> 源文件 `services/db_locks.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

并行初始化时对同一 SQLite 库的写操作串行化。

多个步骤并行下载时会写同一数据库（reference.db 有 items/implants/rigs/
industry/sde_data 五个写者）。WAL + busy_timeout 已缓解锁冲突，但大事务
并发写仍可能互相阻塞（database is locked）。这里提供 per-DB 的
asyncio.Lock，下载器在写库阶段显式获取，网络拉取 / YAML 解析保持并行。

注意：asyncio.Lock 惰性绑定首次使用的事件循环。初始化重试会新建
asyncio.run()，跨循环复用同一把锁会抛 "bound to a different event loop"。
因此每次 asyncio.run 前必须调 reset_db_locks()（由 InitService.start 负责）。

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

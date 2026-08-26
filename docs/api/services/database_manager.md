# services.database_manager

> 源文件 `services/database_manager.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

DatabaseManager — 多库连接管理器（连接复用版）

封装三个独立数据库的连接管理，支持 ATTACH DATABASE 跨库查询。
同一线程内相同配置的连接自动复用，避免重复打开和 ATTACH 开销。

用法:
    db = DatabaseManager()
    with db.connect('user', 'ref', 'mkt') as conn:
        cursor = conn.execute("SELECT * FROM ref.item i JOIN mkt.market_prices mp ...")

## 函数

### `get_db`

```python
def get_db() -> DatabaseManager
```

获取全局 DatabaseManager 单例

定义行：`201`

## 类

### `class DatabaseManager`

线程安全的多数据库连接管理器（连接复用版）

同一线程内，相同 (primary, attach) 配置的连接会自动复用，
避免重复打开物理连接和执行 ATTACH DATABASE。

定义行：`56`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`63`
##### `_get_cache`

```python
def _get_cache(self) -> dict[str, sqlite3.Connection]
```

获取当前线程的连接缓存字典

定义行：`68`
##### `_cache_key`

```python
def _cache_key(primary: str, attach: tuple[str, ...]) -> str
```

生成连接配置的唯一缓存 key：primary:sorted_unique_attach

定义行：`76`
##### `_get_or_create`

```python
def _get_or_create(self, primary: DB_ALIAS, attach: tuple[str, ...]) -> sqlite3.Connection
```

从缓存获取连接，不存在则创建并缓存

定义行：`81`
##### `_ensure_init`

```python
def _ensure_init(self, db_alias: str)
```

确保目标数据库存在并已初始化

定义行：`122`
##### `connect`

```python
def connect(self, primary: DB_ALIAS, *attach: DB_ALIAS) -> Generator[sqlite3.Connection]
```

获取连接（自动复用），ATTACH 需要的辅助库。

定义行：`129`
##### `connect_ref`

```python
def connect_ref(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接参考数据库

定义行：`154`
##### `connect_mkt`

```python
def connect_mkt(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接市场数据库

定义行：`160`
##### `connect_user`

```python
def connect_user(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接用户数据库

定义行：`166`
##### `direct_connect`

```python
def direct_connect(self, db_alias: DB_ALIAS) -> sqlite3.Connection
```

直接连接（不经过 context manager，不走缓存），用于 Worker/后台线程等简单场景。

定义行：`171`
##### `close_all`

```python
def close_all(self)
```

关闭当前线程的所有缓存连接（应用退出时调用）

定义行：`185`

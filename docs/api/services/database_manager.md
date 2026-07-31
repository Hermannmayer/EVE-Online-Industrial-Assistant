# services.database_manager

> 源文件 `services/database_manager.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

DatabaseManager — 多库连接管理器（连接复用版）

## 函数

### `get_db`

```python
def get_db() -> DatabaseManager
```

获取全局 DatabaseManager 单例

定义行：`237`

## 类

### `class DatabaseManager`

线程安全的多数据库连接管理器（连接复用版）

定义行：`52`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`59`
##### `_get_cache`

```python
def _get_cache(self) -> dict[str, sqlite3.Connection]
```

获取当前线程的连接缓存字典

定义行：`64`
##### `_cache_key`

```python
def _cache_key(primary: str, attach: tuple[str, ...]) -> str
```

生成连接配置的唯一缓存 key：primary:sorted_unique_attach

定义行：`72`
##### `_get_or_create`

```python
def _get_or_create(self, primary: DB_ALIAS, attach: tuple[str, ...]) -> sqlite3.Connection
```

从缓存获取连接，不存在则创建并缓存

定义行：`77`
##### `_ensure_init`

```python
def _ensure_init(self, db_alias: str)
```

确保目标数据库存在并已初始化

定义行：`118`
##### `connect`

```python
def connect(self, primary: DB_ALIAS, *attach: DB_ALIAS) -> Generator[sqlite3.Connection]
```

获取连接（自动复用），ATTACH 需要的辅助库。

定义行：`125`
##### `connect_ref`

```python
def connect_ref(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接参考数据库

定义行：`150`
##### `connect_mkt`

```python
def connect_mkt(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接市场数据库

定义行：`156`
##### `connect_user`

```python
def connect_user(self) -> Generator[sqlite3.Connection]
```

便捷方法：连接用户数据库

定义行：`162`
##### `direct_connect`

```python
def direct_connect(self, db_alias: DB_ALIAS) -> sqlite3.Connection
```

直接连接（不经过 context manager，不走缓存），用于 Worker/后台线程等简单场景。

定义行：`167`
##### `close_all`

```python
def close_all(self)
```

关闭当前线程的所有缓存连接（应用退出时调用）

定义行：`177`
##### `get_item_with_price`

```python
def get_item_with_price(self, type_id: int) -> dict | None
```

获取物品信息及其市场价格（跨库 JOIN）

定义行：`189`
##### `get_bp_detail`

```python
def get_bp_detail(self, type_id: int) -> dict | None
```

获取蓝图详情（跨库 JOIN ref + bp）

定义行：`201`
##### `get_market_summary`

```python
def get_market_summary(self, type_id: int) -> dict | None
```

获取市场汇总（跨库 JOIN ref + mkt + bp）

定义行：`216`

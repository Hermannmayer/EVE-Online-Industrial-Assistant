# core.cache

> 源文件 `core/cache.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

通用 LRU + TTL 缓存 — 线程安全，支持过期被动清理和 LRU 淘汰

## 类

### `class TtlLRUCache`

线程安全的有界缓存，过期被动清理 + LRU 淘汰

定义行：`11`

#### 方法

##### `__init__`

```python
def __init__(self, max_size: int=500, ttl_seconds: int=1800)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`14`
##### `get`

```python
def get(self, key: str) -> Any | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`
##### `set`

```python
def set(self, key: str, value: Any)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`33`
##### `invalidate`

```python
def invalidate(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`42`
##### `_evict_expired_locked`

```python
def _evict_expired_locked(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `__len__`

```python
def __len__(self) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`52`

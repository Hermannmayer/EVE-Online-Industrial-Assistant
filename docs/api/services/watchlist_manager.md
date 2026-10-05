# services.watchlist_manager

> 源文件 `services/watchlist_manager.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

关注列表数据层 — 价格监控 CRUD / 阈值设置 / 价格变化检测

## 函数

### `_db`

```python
def _db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。

定义行：`8`

### `init_db`

```python
def init_db()
```

初始化关注列表表

定义行：`37`

### `add_to_watchlist`

```python
def add_to_watchlist(type_id: int, region_id: int=10000002, note: str='', buy_threshold: float | None=None, sell_threshold: float | None=None) -> int
```

添加物品到关注列表，返回新记录 id

定义行：`46`

### `remove_from_watchlist`

```python
def remove_from_watchlist(item_id: int) -> bool
```

删除关注列表中的物品

定义行：`74`

### `get_watchlist`

```python
def get_watchlist() -> list[dict]
```

获取所有关注物品，JOIN item 表获取名称和市场价格

定义行：`83`

### `update_watchlist_item`

```python
def update_watchlist_item(item_id: int, note: str | None=None, buy_threshold: float | None=None, sell_threshold: float | None=None) -> bool
```

更新关注物品的备注或阈值

定义行：`129`

### `check_price_changes`

```python
def check_price_changes() -> list[dict]
```

遍历关注列表，对比当前 market_prices 与上次记录的价格。
返回有变化的物品列表：[(type_id, 名称, 原买价, 新买价, 原卖价, 新卖价), ...]
同时更新 last_buy_price / last_sell_price。

定义行：`158`

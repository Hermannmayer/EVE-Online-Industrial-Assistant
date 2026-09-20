# services.asset_snapshot_service

> 源文件 `services/asset_snapshot_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品查询页空闲态仪表盘 —— 资产快照采集/查询与钱包余额读写。

纯服务层（无 Qt）。资产折线图的数据源，5 条线取数来源如下（勿再猜）：

- ``inventory``（库存材料金额）= 遍历全部机库求和
  ``inventory_manager.get_total_value(hangar_id, price_type="sell")["market_total"]``
- ``orders``（挂单金额）= ``SELECT SUM(price * volume_remain) FROM open_orders``
- ``line_value``（运行中产线价值）= **只取制造中产线**（``category=='manufacturing'`` 且
  ``status IN ('in_progress','running')``）的材料占用 × **卖单价**，见 ``_line_value()``。
  与「仓库管理」里的「规划占用」**口径不同**：那个只算命中的库存物料，
  这里算计划的**完整材料需求**（缺料也算进去）。
- ``wallet``（钱包余额）= ``get_wallet_balance()``（settings.json，用户手填 + 订单变动自动增减）
- ``total``（总资产）= ``inventory + orders + line_value + wallet``

每天一行（``asset_snapshots.snap_date`` 唯一），当天重复记录覆盖不累积。
日期一律由 **SQLite 侧** ``date('now','localtime')`` 决定（与
``schema_migrations.price_snapshots.snapshot_time`` 同源），不混用 Python 的
``date.today()`` —— 二者跨时区/跨零点会给出不同日期，而 upsert 冲突键正是这一列。

基线表（``asset_snapshots`` / ``open_orders`` / ``order_events``）既由 schema 迁移创建给
存量库（v16→v17 建前两张表，v17→v18 加 ``line_value`` 列并建 ``order_events``），
也在本模块入口 ``CREATE TABLE IF NOT EXISTS`` 兜底给测试/新库 —— 复用
``inventory_manager.SCHEMA`` 的既有约定，两边都用 ``IF NOT EXISTS``，重复执行幂等。
``ALTER TABLE`` 不在此处，仍只走迁移。

## 函数

### `_default_db`

```python
def _default_db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器）。

定义行：`97`

### `_ensure_schema`

```python
def _ensure_schema(conn) -> None
```

在给定连接上创建基线表（IF NOT EXISTS，幂等）。

定义行：`102`

### `ensure_schema`

```python
def ensure_schema() -> None
```

确保基线表存在（给外部调用方/新库兜底）。

定义行：`107`

### `_inventory_value`

```python
def _inventory_value() -> float
```

inventory 线：遍历全部机库按卖单价估值求和。

定义行：`113`

### `_orders_value`

```python
def _orders_value() -> float
```

orders 线：逐行 ``price * volume_remain`` 求和（卖单用 sell 语义价、买单同理，直接取自身 price）。

定义行：`122`

### `_sell_prices`

```python
def _sell_prices(type_ids: set[int]) -> dict[int, float]
```

market.db 里这批 type_id 的 Jita 卖单价（缺失/为 0 的不进结果）。

定义行：`130`

### `_line_value`

```python
def _line_value() -> float
```

line_value 线：**制造中**产线的材料占用 × 卖单价。

定义行：`143`

### `record_snapshot`

```python
def record_snapshot(wallet: float | None=None) -> dict
```

采集当日资产快照并 upsert（同日重复覆盖，不累积）。

定义行：`203`

### `load_series`

```python
def load_series(days: int=90) -> list[dict]
```

按日期升序返回最近 ``days`` 天内的快照序列。

定义行：`237`

### `adjust_wallet_balance`

```python
def adjust_wallet_balance(delta: float) -> float
```

按订单变动增减钱包余额（返回调整后的值）。

定义行：`257`

### `get_wallet_balance`

```python
def get_wallet_balance() -> float
```

wallet 线：读 settings.json 里的钱包余额；缺失/非数值一律 0.0。

定义行：`268`

### `set_wallet_balance`

```python
def set_wallet_balance(value: float) -> None
```

写回钱包余额（read-modify-write，保留 settings.json 其余键）。

定义行：`277`

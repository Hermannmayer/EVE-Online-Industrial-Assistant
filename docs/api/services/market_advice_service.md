# services.market_advice_service

> 源文件 `services/market_advice_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

交易建议 —— 单个物品「挂单还是吃单」的只读判定（纯计算 + 只读查询）。

数据源与口径（三张表都在 `market.db`）：

- `market_prices`：每个 `(type_id, region_id)` 一行**挂单价** —— `buy_price` 是最高买单价、
  `sell_price` 是最低卖单价。同一 key 有多行时取 `fetch_time` 最新的一行（与市场浏览器同口径）。
- `price_history`：日级**成交**数据。`dayVolume` = 近 7 个**日历天**（`[今天 - 6, 今天]`）的
  `volume` 之和 ÷ 7，窗口内没有记录的日子按 0 成交计入分母；窗口里**一条记录都没有** → `None`
  （「没记录」不等于「0 成交」，不拿 0 冒充）。
- `market_volume_snapshots`：每日快照，`orderVolume` 取该物品**最新一天**的 `sell_volume`
  （卖单挂单量）。没有快照行 → `None`；快照里的 0 是真的「队列为空」，照实回 0。

费率**不在这里发明**：默认值取自 `core.eve_formulas.BROKER_FEE_BASE` / `SALES_TAX_BASE`，
且只走参数 —— 本模块**不读角色设置**，保持纯函数式。物品名走
`services.name_resolver.resolve_item_name`（terminology 覆盖 → `ref.item.zh_name` → type_id）。

判定顺序：`no_data` → `avoid_thin` → `two_sided` / `take_orders`；修正项见
`TREND_DOWN_PCT` / `TREND_UP_PCT` / `TURN_DAYS_WARN`。

**两处口径收口**（规则原文没写死，这里取更保守的一侧）：

1. 「拿不到买价 / 卖价」按**任一侧**缺价执行：只有卖价没有买价时算不出价差，给半边的吃单
   建议只会误导 → 一律 `no_data`，`reasons` 写明缺的是哪一侧。价格缺行与价格为 0 同义
   （0 不是可成交的价），字段回 `None` 而不是 0。
2. `trend_30d` 修正只加在**可操作**的三个 verdict 上：`no_data` 的两条建议是规则 1 的固定
   文案「先跑一次『更新价格』」，往后面接「尽快出手」是自相矛盾的。

## 函数

### `_price`

```python
def _price(value: float | None) -> float | None
```

价格列取值：NULL 或 ≤ 0 都当「没有这个报价」→ `None`（0 不是可成交的价）。

定义行：`71`

### `_spread_pct`

```python
def _spread_pct(buy: float, sell: float) -> float | None
```

价差 % = (卖价 − 买价) ÷ 卖价 × 100；卖价 ≤ 0 算不出 → `None`（不除零）。

定义行：`79`

### `_round_trip_fee_pct`

```python
def _round_trip_fee_pct(broker_pct: float, sales_tax_pct: float) -> float
```

来回一次挂单的费用率 % = 买侧经纪人费 + 卖侧经纪人费 + 卖出的销售税。

定义行：`86`

### `_turn_days`

```python
def _turn_days(order_volume: float | None, day_volume: float | None) -> float | None
```

卖完当前卖单队列要几天 = 挂单量 ÷ 日均成交量。

定义行：`91`

### `_isk`

```python
def _isk(value: float | None) -> str
```

ISK 金额文案；`None` 如实写「无报价」。

定义行：`101`

### `_pct`

```python
def _pct(value: float | None) -> str
```

百分比文案；`None`（未知）如实写「未知」，不拿 0 冒充。

定义行：`114`

### `_table_exists`

```python
def _table_exists(conn: sqlite3.Connection, name: str) -> bool
```

`market.db` 里有没有这张表（从没「更新价格」过的库缺表，不是错误）。

定义行：`124`

### `_load_quotes`

```python
def _load_quotes(conn: sqlite3.Connection, type_id: int, region_id: int) -> tuple[float | None, float | None]
```

`(最高买价, 最低卖价)`；缺行 / 缺表 / 价格列为 0 → 对应侧给 `None`。

定义行：`134`

### `_load_day_volume`

```python
def _load_day_volume(conn: sqlite3.Connection, type_id: int, region_id: int, days: int) -> float | None
```

近 `days` 个日历天的日均成交量（成交量之和 ÷ days）；窗口内一条记录都没有 → `None`。

定义行：`148`

### `_load_order_volume`

```python
def _load_order_volume(conn: sqlite3.Connection, type_id: int, region_id: int) -> float | None
```

最新一天的卖单挂单量；没有快照行（或列为 NULL）→ `None`。

定义行：`164`

### `_resolve_name`

```python
def _resolve_name(conn: sqlite3.Connection, type_id: int) -> str
```

物品名：terminology 覆盖 → `ref.item.zh_name` / `en_name` → type_id 字符串。

定义行：`178`

### `get_trade_advice`

```python
def get_trade_advice(type_id: int, region_id: int=JITA_RID, *, trend_30d: float | None=None, broker_pct: float | None=None, sales_tax_pct: float | None=None, min_daily_volume: float=10.0, _db=None) -> dict
```

单个物品的「挂单还是吃单」建议（只读；字段与口径见模块 docstring）。

定义行：`195`

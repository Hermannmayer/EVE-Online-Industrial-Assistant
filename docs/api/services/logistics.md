# services.logistics

> 源文件 `services/logistics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
数据来源：硬编码 TRADE_HUB_DISTANCES 距离表、reference.db item.volume、
market.db market_prices（经 PricingService）。被贸易页 TransportWorker 消费。

## 函数

### `_default_db`

```python
def _default_db()
```

惰性获取 DatabaseManager（经容器）。

定义行：`24`

### `_default_pricing`

```python
def _default_pricing()
```

惰性获取 PricingService（经容器）。

定义行：`29`

### `get_distance_jumps`

```python
def get_distance_jumps(source: str, destination: str) -> int | None
```

获取两个贸易中心之间的跳跃数，未知路线返回 None

定义行：`55`

### `estimate_freight_cost`

```python
def estimate_freight_cost(volume_m3: float, distance_jumps: int, collateral: float, price_per_jump: float=500000, price_per_m3: float=200, use_public_freight: bool=True) -> dict
```

估算跨区域货物运输的运费。

定义行：`60`

### `calc_transport_profit`

```python
def calc_transport_profit(type_id: int, buy_hub: str, sell_hub: str, buy_price_type: str, sell_price_type: str, quantity: int, distance_jumps: int, char_config: dict | None=None, use_public_freight: bool=True) -> dict
```

计算跨区域运输的净利润（包含运费和贸易费用）。

定义行：`142`

### `list_trade_hub_distances`

```python
def list_trade_hub_distances() -> list[dict]
```

返回所有贸易中心对的跳跃距离，供 UI 使用

定义行：`290`

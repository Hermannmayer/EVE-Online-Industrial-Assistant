# services.logistics

> 源文件 `services/logistics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
数据来源：硬编码 TRADE_HUB_DISTANCES 距离表、reference.db item.volume、
market.db market_prices（经 PricingService）。

⚠️ **当前没有 UI 调用方**：市场贸易页的「运输利润」Tab 已删除（2026-09），
`estimate_freight_cost` / `calc_transport_profit` 保留待合同市场接入；
`compute_jumps` 仍被 `services/contract_service.py` 使用。

## 函数

### `_default_db`

```python
def _default_db()
```

惰性获取 DatabaseManager（经容器）。

定义行：`32`

### `_default_pricing`

```python
def _default_pricing()
```

惰性获取 PricingService（经容器）。

定义行：`37`

### `_load_gate_graph`

```python
def _load_gate_graph() -> tuple[dict[int, set[int]], dict[int, float]]
```

从 reference.db 建星系邻接表 + 安全等级表。

定义行：`78`

### `compute_jumps`

```python
def compute_jumps(origin_system_id: int, destination_system_id: int, mode: str='shortest', min_security: float | None=None) -> int | None
```

两个星系之间的跳跃数；不可达返回 None。

定义行：`117`

### `get_distance_jumps`

```python
def get_distance_jumps(source: str, destination: str) -> int | None
```

两个**贸易中心**之间的跳跃数（按高安路线 —— 跑货实际会飞的那条）。

定义行：`171`

### `estimate_freight_cost`

```python
def estimate_freight_cost(volume_m3: float, distance_jumps: int, collateral: float, price_per_jump: float=500000, price_per_m3: float=200, use_public_freight: bool=True) -> dict
```

估算跨区域货物运输的运费。

定义行：`185`

### `calc_transport_profit`

```python
def calc_transport_profit(type_id: int, buy_hub: str, sell_hub: str, buy_price_type: str, sell_price_type: str, quantity: int, distance_jumps: int, char_config: dict | None=None, use_public_freight: bool=True) -> dict
```

计算跨区域运输的净利润（包含运费和贸易费用）。

定义行：`267`

### `list_trade_hub_distances`

```python
def list_trade_hub_distances() -> list[dict]
```

返回所有贸易中心对的跳跃距离（走高安路线），供 UI 使用。

定义行：`415`

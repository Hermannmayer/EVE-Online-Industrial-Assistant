# services.logistics

> 源文件 `services/logistics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
数据来源：硬编码 TRADE_HUB_DISTANCES 距离表、reference.db item.volume、
market.db market_prices（经 PricingService）。

⚠️ **`compute_jumps` / 距离工具仍在使用**：`services/contract_service.py` 用它给合同每行算跳数，
`list_trade_hub_distances` 供 UI 距离表。原运费估算（`estimate_freight_cost`）与运输利润
（`calc_transport_profit`）没有 UI 调用方，已按 2026-10-17 审计 04-4 删除；将来接合同市场时再按需加回。

## 函数

### `_default_db`

```python
def _default_db()
```

惰性获取 DatabaseManager（经容器）。

定义行：`22`

### `_load_gate_graph`

```python
def _load_gate_graph() -> tuple[dict[int, set[int]], dict[int, float]]
```

从 reference.db 建星系邻接表 + 安全等级表。

定义行：`70`

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

定义行：`174`

### `list_trade_hub_distances`

```python
def list_trade_hub_distances() -> list[dict]
```

返回所有贸易中心对的跳跃距离（走高安路线），供 UI 使用。

定义行：`188`

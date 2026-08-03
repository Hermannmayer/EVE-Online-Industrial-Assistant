# services.npc_seller

> 源文件 `services/npc_seller.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图 NPC 卖家查询 — 从 ESI 卖单中筛出 NPC 公司的卖单。

## 函数

### `filter_npc_sell_orders`

```python
def filter_npc_sell_orders(orders: list[dict], npc_corp_ids: set[int]) -> list[dict]
```

从 ESI 市场卖单里筛出 NPC 公司的卖单。

定义行：`11`

### `load_npc_corp_ids`

```python
def load_npc_corp_ids(conn: Connection) -> set[int]
```

reference.db 中全部 NPC 公司 id 集合。

定义行：`26`

### `load_corp_names`

```python
def load_corp_names(conn: Connection) -> dict[int, str]
```

corp_id → 显示名（zh 优先 → en → str(id)）。

定义行：`32`

### `resolve_stations`

```python
def resolve_stations(conn: Connection, location_ids: set[int]) -> dict[int, tuple[str, str]]
```

location_id → (空间站名, 星系名)。NPC 空间站的 location_id 即 station.station_id。

定义行：`38`

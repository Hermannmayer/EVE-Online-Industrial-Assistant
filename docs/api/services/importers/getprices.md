# services.importers.getprices

> 源文件 `services/importers/getprices.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

市场价格拉取 — 4 大贸易中心订单簿 + 成交量历史

两阶段：
  1. 先拉 /markets/prices/（1次请求，极快）做兜底
  2. 并发拉取 4 区域订单，用真实买卖价覆盖

## 函数

### `write_progress`

```python
def write_progress(cur: int, total: int, phase: str='')
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`100`

### `init_db`

```python
async def init_db()
```

确保 market_prices 和 market_volume_snapshots 表存在（幂等）

定义行：`110`

### `fetch_baseline_prices`

```python
async def fetch_baseline_prices() -> dict[int, dict]
```

/markets/prices/ — 1次请求，极快。

定义行：`157`

### `fetch_plex_global_book`

```python
async def fetch_plex_global_book() -> dict[int, dict]
```

用 Global PLEX Market（region `PLEX_REGION_ID`）的真实盘口覆盖 PLEX 兜底价。

定义行：`185`

### `_fetch_order_pages_detailed`

```python
async def _fetch_order_pages_detailed(client: APIClient, region_id: int, order_type: str, total_pages: int) -> tuple[list, bool]
```

并发拉取一个区域指定方向的所有订单页（全局限流 ≤20 req/s）。

定义行：`233`

### `fetch_order_pages`

```python
async def fetch_order_pages(client: APIClient, region_id: int, order_type: str, total_pages: int) -> list
```

并发拉取一个区域指定方向的所有订单页（兼容旧签名，只返回数据）。

定义行：`271`

### `discover_pages`

```python
async def discover_pages(client: APIClient, targets: list[tuple[str, int]] | None=None) -> dict
```

并发获取所有流的总页数（8次请求）

定义行：`277`

### `fetch_orders_detailed`

```python
async def fetch_orders_detailed(regions: list[tuple[str, int]] | None=None) -> tuple[dict[int, dict[int, dict]], set[int]]
```

4 区域实时订单，按 region_id → type_id 组织，并返回完整拉取成功的区域。

定义行：`307`

### `fetch_orders`

```python
async def fetch_orders(regions: list[tuple[str, int]] | None=None) -> dict[int, dict[int, dict]]
```

兼容旧签名：只返回 &#123;region_id: &#123;type_id: &#123;...&#125;&#125;&#125;。

定义行：`367`

### `_complete_regions_only`

```python
def _complete_regions_only(order_prices: dict[int, dict[int, dict]], complete_regions: set[int] | None) -> dict[int, dict[int, dict]]
```

只保留「买卖两方向全部页都成功」的区域，供成交量快照写入（02-06）。

定义行：`373`

### `save_snapshot`

```python
async def save_snapshot(all_regions: dict[int, dict[int, dict]])
```

保存各区域当日成交量快照

定义行：`387`

### `save_prices`

```python
async def save_prices(baseline: dict[int, dict], order_prices: dict[int, dict[int, dict]], region_ids: list[int] | None=None, complete_regions: set[int] | None=None) -> int
```

写入各区域价格（仅覆盖指定区域）。

定义行：`419`

### `_history_is_fresh`

```python
def _history_is_fresh(fetched_at: str | None, cutoff: datetime) -> bool
```

`fetched_at` 是否落在 TTL 内（缺失/解析失败一律当作过期 → 重拉）。

定义行：`473`

### `_pending_history_tasks`

```python
async def _pending_history_tasks(region_ids: list[int], type_ids: set[int], cutoff: datetime) -> list[tuple[int, int, str | None]]
```

算出本轮要拉的 `(region_id, type_id)`：没有记录、或记录早于 TTL 的才算；
再按「该区域**有挂单** ∪ **已有历史**」丢掉注定返回空的组合（BL-013）。

定义行：`486`

### `_fetch_history_with_limit`

```python
async def _fetch_history_with_limit(client: APIClient, region_id: int, type_id: int, etag: str | None=None) -> tuple[list[dict] | None | object, str | None]
```

经 `GLOBAL_ESI_LIMITER` 拉单条市场历史（带 ETag 条件请求，02-07）。

定义行：`560`

### `_save_histories`

```python
async def _save_histories(entries: dict[tuple[int, int], tuple[list[tuple], str | None]], date_cutoff: str) -> int
```

批量写入历史：先按 `(type_id, region_id)` 裁掉 `date_cutoff` 之前的行，再 `INSERT OR REPLACE`。

定义行：`583`

### `_touch_histories`

```python
async def _touch_histories(pairs: list[tuple[int, int]], fetched_at: str) -> int
```

304 命中时只把 `fetched_at` 续到本轮 —— 不重写 410 行行情（省 43KB/条，02-07）。

定义行：`611`

### `_material_type_ids`

```python
def _material_type_ids() -> set[int]
```

被制造/反应蓝图当材料用的 type（实测 1646 个 distinct）。

定义行：`625`

### `fetch_and_save_histories`

```python
async def fetch_and_save_histories(regions: list[tuple[str, int]], progress_cb: Callable[[int, str], None] | None=None) -> int
```

按 TTL 增量拉取「产物 ∪ 材料」+「PLEX 全域」的市场历史，写入 market.db.price_history。

定义行：`639`

### `save_global_price_snapshot`

```python
async def save_global_price_snapshot(baseline: dict[int, dict], day: str | None=None) -> int
```

把 `/markets/prices/` 的**全服统一价**按天存一条（只存锚定集合）。

定义行：`776`

### `main`

```python
async def main(regions: list[tuple[str, int]] | None=None, progress_cb: Callable[[int, str], None] | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`814`

### `fetch_baseline_only`

```python
async def fetch_baseline_only(progress_cb: Callable[[int, str], None] | None=None)
```

快速基础价格兜底 — 仅拉 /markets/prices/（1 次请求）。

定义行：`892`

### `run_price_update`

```python
def run_price_update(regions: list[str] | None=None, progress_cb: Callable[[int, str], None] | None=None)
```

运行价格更新。

定义行：`914`

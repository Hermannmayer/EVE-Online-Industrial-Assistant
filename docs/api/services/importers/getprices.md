# services.importers.getprices

> 源文件 `services/importers/getprices.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

市场价格拉取 — 4 大贸易中心订单簿 + 成交量历史

## 函数

### `write_progress`

```python
def write_progress(cur: int, total: int, phase: str='')
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`34`

### `init_db`

```python
async def init_db()
```

确保 market_prices 和 market_volume_snapshots 表存在（幂等）

定义行：`44`

### `fetch_baseline_prices`

```python
async def fetch_baseline_prices() -> dict[int, dict]
```

/markets/prices/ — 1次请求，极快

定义行：`84`

### `_fetch_order_pages_detailed`

```python
async def _fetch_order_pages_detailed(client: APIClient, region_id: int, order_type: str, total_pages: int) -> tuple[list, bool]
```

并发拉取一个区域指定方向的所有订单页（全局限流 ≤20 req/s）。

定义行：`103`

### `fetch_order_pages`

```python
async def fetch_order_pages(client: APIClient, region_id: int, order_type: str, total_pages: int) -> list
```

并发拉取一个区域指定方向的所有订单页（兼容旧签名，只返回数据）。

定义行：`141`

### `discover_pages`

```python
async def discover_pages(client: APIClient, targets: list[tuple[str, int]] | None=None) -> dict
```

并发获取所有流的总页数（8次请求）

定义行：`147`

### `fetch_orders_detailed`

```python
async def fetch_orders_detailed(regions: list[tuple[str, int]] | None=None) -> tuple[dict[int, dict[int, dict]], set[int]]
```

4 区域实时订单，按 region_id → type_id 组织，并返回完整拉取成功的区域。

定义行：`177`

### `fetch_orders`

```python
async def fetch_orders(regions: list[tuple[str, int]] | None=None) -> dict[int, dict[int, dict]]
```

兼容旧签名：只返回 &#123;region_id: &#123;type_id: &#123;...&#125;&#125;&#125;。

定义行：`245`

### `save_snapshot`

```python
async def save_snapshot(all_regions: dict[int, dict[int, dict]])
```

保存各区域当日成交量快照

定义行：`251`

### `save_prices`

```python
async def save_prices(baseline: dict[int, dict], order_prices: dict[int, dict[int, dict]], region_ids: list[int] | None=None, complete_regions: set[int] | None=None) -> int
```

写入各区域价格（仅覆盖指定区域）。

定义行：`283`

### `main`

```python
async def main(regions: list[tuple[str, int]] | None=None, progress_cb: Callable[[int, str], None] | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`337`

### `fetch_baseline_only`

```python
async def fetch_baseline_only(progress_cb: Callable[[int, str], None] | None=None)
```

快速基础价格兜底 — 仅拉 /markets/prices/（1 次请求）。

定义行：`376`

### `run_price_update`

```python
def run_price_update(regions: list[str] | None=None)
```

运行价格更新。

定义行：`398`

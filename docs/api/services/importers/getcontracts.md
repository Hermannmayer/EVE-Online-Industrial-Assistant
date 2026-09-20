# services.importers.getcontracts

> 源文件 `services/importers/getcontracts.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

公开合同拉取 — 4 大贸易中心公开合同 + 合同内物品

ESI 端点：
  GET /contracts/public/&#123;region_id&#125;/  — 分页，每页 500 条
  GET /contracts/public/items/&#123;contract_id&#125;/  — 合同内物品详情

两阶段：
  1. 并发拉取各区域的合同列表（分页）
  2. 对每个合同并发拉取其物品列表
  3. 批量写入数据库

## 函数

### `init_db`

```python
async def init_db()
```

初始化合同相关数据库表。

定义行：`40`

### `_contract_tables_are_stale`

```python
async def _contract_tables_are_stale(db: aiosqlite.Connection) -> bool
```

已有 public_contracts 表但缺现结构标记列 → 是旧结构，需要重建。

定义行：`119`

### `_fetch_contract_pages_detailed`

```python
async def _fetch_contract_pages_detailed(session, region_id: int) -> tuple[list[dict], bool]
```

拉取一个区域的全部公开合同（分页）。

定义行：`129`

### `fetch_contract_pages`

```python
async def fetch_contract_pages(session: aiohttp.ClientSession, region_id: int) -> list[dict]
```

拉取一个区域的全部公开合同（兼容旧签名，只返回列表）。

定义行：`197`

### `_fetch_contract_items_detailed`

```python
async def _fetch_contract_items_detailed(session, contract_ids: list[int]) -> tuple[dict[int, list[dict]], set[int]]
```

并发拉取多个合同的物品列表。

定义行：`203`

### `fetch_contract_items`

```python
async def fetch_contract_items(session: aiohttp.ClientSession, contract_ids: list[int]) -> dict[int, list[dict]]
```

并发拉取多个合同的物品列表（兼容旧签名，只返回 dict）。

定义行：`248`

### `save_contract_list`

```python
async def save_contract_list(region_id: int, contracts: list[dict], complete: bool, fetch_time: str) -> int
```

写入一个星域的合同列表 —— 拉完立刻落库，不等物品。

定义行：`254`

### `save_items_batch`

```python
async def save_items_batch(items: dict[int, list[dict]], fetched_at: str) -> int
```

写入一批合同的物品，并回填 `items_fetched_at`。

定义行：`342`

### `_save_issuer_names`

```python
async def _save_issuer_names(items: list[dict]) -> int
```

`[&#123;id, name, category&#125;]` → `contract_issuers`，返回写入条数。

定义行：`398`

### `_fetch_issuer_names_async`

```python
async def _fetch_issuer_names_async(ids: list[int], should_stop: Callable[[], bool] | None=None) -> int
```

批量取名并落库。

定义行：`416`

### `run_issuer_name_fill`

```python
def run_issuer_name_fill(ids: list[int], should_stop: Callable[[], bool] | None=None) -> int
```

同步入口（供 QThread worker 调用）。返回写入的名字条数。

定义行：`459`

### `list_contracts_needing_items`

```python
def list_contracts_needing_items(region_id: int, contract_type: str, limit: int=500, contract_ids: list[int] | None=None) -> list[int]
```

待取物品的合同，按合同价降序（贵的先补，先看到有价值的行）。

定义行：`475`

### `_fill_items_async`

```python
async def _fill_items_async(contract_ids: list[int], progress_cb: Callable[[int, int], None] | None, should_stop: Callable[[], bool] | None) -> int
```

分批拉物品 + **分批回写**（不是最后一次性写）。返回写入的物品行数。

定义行：`526`

### `run_items_fill`

```python
def run_items_fill(contract_ids: list[int], progress_cb: Callable[[int, int], None] | None=None, should_stop: Callable[[], bool] | None=None) -> int
```

同步入口（供 QThread worker 调用）。

定义行：`558`

### `_fetch_and_save_list`

```python
async def _fetch_and_save_list(region_ids: list[int], progress_cb: Callable[[int, str], None] | None=None) -> dict[int, int]
```

阶段 A：只拉合同列表，**每个星域拉完立刻落库**，不等物品。

定义行：`571`

### `run_contract_update`

```python
def run_contract_update(region_ids: list[int] | None=None, progress_cb: Callable[[int, str], None] | None=None) -> dict[int, int]
```

拉取合同**列表**（不含物品）—— UI 的「拉取合同」按钮走这条。

定义行：`599`

### `main`

```python
async def main(regions: list[tuple[str, int]] | None=None)
```

CLI 主流程：拉列表 → 落库（不含物品；物品用 `run_items_fill` 单独补）。

定义行：`617`

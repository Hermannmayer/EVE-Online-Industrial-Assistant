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

### `write_progress`

```python
def write_progress(cur: int, total: int, phase: str='')
```

写入进度文件供 UI 读取

定义行：`52`

### `init_db`

```python
async def init_db()
```

初始化合同相关数据库表

定义行：`63`

### `_fetch_contract_pages_detailed`

```python
async def _fetch_contract_pages_detailed(session, region_id: int) -> tuple[list[dict], bool]
```

拉取一个区域的全部公开合同（分页）。

定义行：`112`

### `fetch_contract_pages`

```python
async def fetch_contract_pages(session: aiohttp.ClientSession, region_id: int) -> list[dict]
```

拉取一个区域的全部公开合同（兼容旧签名，只返回列表）。

定义行：`180`

### `_fetch_contract_items_detailed`

```python
async def _fetch_contract_items_detailed(session, contract_ids: list[int]) -> tuple[dict[int, list[dict]], set[int]]
```

并发拉取多个合同的物品列表。

定义行：`186`

### `fetch_contract_items`

```python
async def fetch_contract_items(session: aiohttp.ClientSession, contract_ids: list[int]) -> dict[int, list[dict]]
```

并发拉取多个合同的物品列表（兼容旧签名，只返回 dict）。

定义行：`231`

### `save_contracts`

```python
async def save_contracts(all_contracts: dict[int, list[dict]], all_items: dict[int, list[dict]], region_ids: list[int], complete_regions: set[int] | None=None) -> tuple[int, int]
```

批量写入合同和物品数据。

定义行：`237`

### `main`

```python
async def main(regions: list[tuple[str, int]] | None=None)
```

主流程：拉取合同并存入数据库

定义行：`352`

### `run_contract_update`

```python
def run_contract_update(regions: list[str] | None=None)
```

运行合同更新。

定义行：`415`

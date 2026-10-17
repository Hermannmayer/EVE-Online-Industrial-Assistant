# services.importers.sde_loader

> 源文件 `services/importers/sde_loader.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

SDE 扩展数据加载器 — 将 16 个新表写入 reference.db

功能:
  - metaGroups.yaml         → meta_group 表 + item.meta_group_id
  - categories.yaml         → category 表 + item.category_id (via groupIDs.yaml)
  - typeMaterials.yaml      → reprocessing_materials 表
  - dogmaAttributes.yaml    → dogma_attribute 表
  - dogmaEffects.yaml       → dogma_effect 表
  - iconIDs.yaml            → icon_ids 表
  - staStations.yaml        → station 表（旧源 bsd/staStations.yaml；新源 npcStations.yaml
                              无 stationName → 写库走 COALESCE 保留旧站名，见 sde_cache B 段）
  - stationOperations.yaml  → station_operation 表
  - operationServices.yaml  → station_operation_service 表
  - stationServices.yaml    → station_service 表
  - researchAgents.yaml     → research_agent 表
  - npcCorporations.yaml    → npc_corporation 表
  - agents.yaml             → agent 表
  - universe/               → solar_system 表（星系名/安全等级/**区域归属**）

## 函数

### `_ref_db`

```python
async def _ref_db()
```

reference.db 写库上下文：per-DB 写锁 + 连接。

定义行：`46`

### `_ensure_dict`

```python
def _ensure_dict(data)
```

Normalize BSD YAML data (list or dict) to dict keyed by ID

定义行：`58`

### `initialize_database`

```python
async def initialize_database()
```

创建 16 个新表 + item 表新增列

定义行：`74`

### `write_meta_groups`

```python
async def write_meta_groups()
```

写入 meta_group 表 + 更新 item.meta_group_id

定义行：`119`

### `write_type_materials`

```python
async def write_type_materials()
```

写入 reprocessing_materials 表

定义行：`184`

### `write_dogma_attributes`

```python
async def write_dogma_attributes()
```

写入 dogma_attribute 表

定义行：`217`

### `write_icon_ids`

```python
async def write_icon_ids()
```

写入 icon_ids 表

定义行：`250`

### `write_categories`

```python
async def write_categories()
```

写入 category 表 + 更新 item.category_id

定义行：`281`

### `_station_rows`

```python
def _station_rows(sta_raw) -> list[tuple]
```

SDE station YAML → station 表行；兼容旧列表格式与新源字典格式。

定义行：`351`

### `write_stations`

```python
async def write_stations()
```

写入 station + station_operation + station_operation_service + station_service 表

定义行：`397`

### `_ensure_region_zh_column`

```python
async def _ensure_region_zh_column(db: aiosqlite.Connection) -> bool
```

reference.db（可重建缓存）**一次性**补 `region.zh_name` 列；补了 → True。

定义行：`507`

### `write_region_names`

```python
async def write_region_names(progress_cb: Callable[[int, str], None] | None=None) -> int
```

补齐 `region.zh_name`（CCP 官方中文星域名），返回写入条数。

定义行：`525`

### `_solar_system_columns`

```python
async def _solar_system_columns(db) -> set[str]
```

`solar_system` 表现有列（兼容极老/测试用的最小 schema）。

定义行：`572`

### `_region_backfill_rows`

```python
def _region_backfill_rows(existing: list[tuple[int, int | None, int | None]], geo: dict[int, tuple[int | None, int | None]]) -> list[tuple[int | None, int | None, int]]
```

只挑「库里 NULL 且 SDE 能给」的行 → `[(region_id, constellation_id, solar_system_id)]`。

定义行：`578`

### `_backfill_universe_region_ids`

```python
async def _backfill_universe_region_ids(progress_cb=None) -> int
```

历史库增量回填 `solar_system.region_id/constellation_id`（只补 NULL，不重导其它表）。

定义行：`597`

### `write_universe`

```python
async def write_universe(progress_cb=None)
```

写入 solar_system 表（星系名/安全等级/**区域归属**）。

定义行：`644`

### `write_research`

```python
async def write_research()
```

写入 research_agent + npc_corporation + agent 表

定义行：`716`

### `write_dogma_effects`

```python
async def write_dogma_effects()
```

写入 dogma_effect 表

定义行：`815`

### `_run_writers`

```python
async def _run_writers(writers, progress_cb)
```

逐表写入（单表失败不影响其他）

定义行：`868`

### `run_core`

```python
async def run_core(progress_cb=None)
```

SDE 扩展数据（不依赖 item 表）— universe/stations/research/dogma/materials。

定义行：`885`

### `run_item_data`

```python
async def run_item_data(progress_cb=None)
```

SDE 扩展数据（依赖 item 表）— meta_groups/categories + 蓝图名称补拉。

定义行：`900`

### `main`

```python
async def main(progress_cb=None)
```

主流程：确保 SDE 缓存就绪 → 初始化数据库 → 逐表写入（单表失败不影响其他）

定义行：`915`

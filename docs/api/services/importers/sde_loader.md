# services.importers.sde_loader

> 源文件 `services/importers/sde_loader.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

SDE 扩展数据加载器 — 将 16 个新表写入 reference.db

## 函数

### `_ref_db`

```python
async def _ref_db()
```

reference.db 写库上下文：per-DB 写锁 + 连接。

定义行：`36`

### `_ensure_dict`

```python
def _ensure_dict(data)
```

Normalize BSD YAML data (list or dict) to dict keyed by ID

定义行：`48`

### `initialize_database`

```python
async def initialize_database()
```

创建 16 个新表 + item 表新增列

定义行：`64`

### `write_meta_groups`

```python
async def write_meta_groups()
```

写入 meta_group 表 + 更新 item.meta_group_id

定义行：`98`

### `write_type_materials`

```python
async def write_type_materials()
```

写入 reprocessing_materials 表

定义行：`160`

### `write_dogma_attributes`

```python
async def write_dogma_attributes()
```

写入 dogma_attribute 表

定义行：`193`

### `write_icon_ids`

```python
async def write_icon_ids()
```

写入 icon_ids 表

定义行：`226`

### `write_categories`

```python
async def write_categories()
```

写入 category 表 + 更新 item.category_id

定义行：`257`

### `write_stations`

```python
async def write_stations()
```

写入 station + station_operation + station_operation_service + station_service 表

定义行：`324`

### `write_universe`

```python
async def write_universe(progress_cb=None)
```

写入 solar_system 表（星系名/安全等级）

定义行：`416`

### `write_research`

```python
async def write_research()
```

写入 research_agent + npc_corporation + agent 表

定义行：`464`

### `write_dogma_effects`

```python
async def write_dogma_effects()
```

写入 dogma_effect 表

定义行：`551`

### `_run_writers`

```python
async def _run_writers(writers, progress_cb)
```

逐表写入（单表失败不影响其他）

定义行：`601`

### `run_core`

```python
async def run_core(progress_cb=None)
```

SDE 扩展数据（不依赖 item 表）— universe/stations/research/dogma/materials。

定义行：`618`

### `run_item_data`

```python
async def run_item_data(progress_cb=None)
```

SDE 扩展数据（依赖 item 表）— meta_groups/categories + 蓝图名称补拉。

定义行：`633`

### `main`

```python
async def main(progress_cb=None)
```

主流程：确保 SDE 缓存就绪 → 初始化数据库 → 逐表写入（单表失败不影响其他）

定义行：`648`

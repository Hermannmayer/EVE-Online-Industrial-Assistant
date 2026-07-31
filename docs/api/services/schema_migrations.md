# services.schema_migrations

> 源文件 `services/schema_migrations.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

集中式数据库 Schema 版本管理 — PRAGMA user_version

## 函数

### `_migrate_mkt_v1_to_v2`

```python
def _migrate_mkt_v1_to_v2(db_path: str) -> str
```

v1→v2: market_prices 新增 adjusted_price 列（EIV 计算用）

定义行：`38`

### `_migrate_mkt_v2_to_v3`

```python
def _migrate_mkt_v2_to_v3(db_path: str) -> str
```

v2→v3: market_prices(fetch_time) 索引 — 加速 MAX(fetch_time) 与按时间过滤（主线程查询）

定义行：`53`

### `_migrate_user_v1_to_v2`

```python
def _migrate_user_v1_to_v2(db_path: str) -> str
```

v1→v2: user_blueprints 新增 cost_per_run 列

定义行：`64`

### `_migrate_user_v2_to_v3`

```python
def _migrate_user_v2_to_v3(db_path: str) -> str
```

v2→v3: production_plans 新增各扩展列

定义行：`79`

### `_migrate_bp_v1_to_v2`

```python
def _migrate_bp_v1_to_v2(db_path: str) -> str
```

v1→v2: blueprint_materials 新增 wastefactor 列

定义行：`102`

### `_add_columns`

```python
def _add_columns(db_path: str, table: str, columns: list[tuple[str, str]]) -> int
```

批量 ADD COLUMN，忽略已存在的列。返回实际新增的列数。

定义行：`139`

### `_get_version`

```python
def _get_version(db_path: str) -> int
```

读取 PRAGMA user_version

定义行：`158`

### `_set_version`

```python
def _set_version(db_path: str, version: int)
```

写入 PRAGMA user_version

定义行：`168`

### `ensure_schema`

```python
def ensure_schema(db_alias: str) -> dict
```

检查并迁移单个库的 schema。

定义行：`183`

### `ensure_all_schemas`

```python
def ensure_all_schemas() -> dict[str, dict]
```

遍历所有 4 个库，执行必要的 schema 迁移。

定义行：`228`

### `get_db_version`

```python
def get_db_version(db_alias: str) -> int | None
```

读取当前库的磁盘版本号（诊断用）

定义行：`241`

### `get_expected_version`

```python
def get_expected_version(db_alias: str) -> int | None
```

返回代码中定义的预期版本号（诊断用）

定义行：`252`

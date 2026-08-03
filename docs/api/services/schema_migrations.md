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

定义行：`55`

### `_migrate_user_v1_to_v2`

```python
def _migrate_user_v1_to_v2(db_path: str) -> str
```

v1→v2: user_blueprints 新增 cost_per_run 列

定义行：`68`

### `_migrate_user_v2_to_v3`

```python
def _migrate_user_v2_to_v3(db_path: str) -> str
```

v2→v3: production_plans 新增各扩展列

定义行：`85`

### `_migrate_user_v3_to_v4`

```python
def _migrate_user_v3_to_v4(db_path: str) -> str
```

v3→v4: production_plans 新增生产执行列（绑定蓝图/材料机库/缺口）

定义行：`114`

### `_migrate_user_v4_to_v5`

```python
def _migrate_user_v4_to_v5(db_path: str) -> str
```

v4→v5: hangars/production_plans 加 solar_system_id，并补 v2→v3 遗漏的 facility_cost_mult。

定义行：`140`

### `_migrate_user_v5_to_v6`

```python
def _migrate_user_v5_to_v6(db_path: str) -> str
```

v5→v6: hangars 加设施类型/设施税/改件 JSON 列（机库级工业配置）

定义行：`165`

### `_migrate_user_v6_to_v7`

```python
def _migrate_user_v6_to_v7(db_path: str) -> str
```

v6→v7: plan_blueprint_bindings 多蓝图绑定表（一条计划绑定多张库存蓝图）

定义行：`185`

### `_migrate_user_v7_to_v8`

```python
def _migrate_user_v7_to_v8(db_path: str) -> str
```

v7→v8: 回填 production_plans 空星系快照（从材料机库带出）。

定义行：`200`

### `_migrate_bp_v1_to_v2`

```python
def _migrate_bp_v1_to_v2(db_path: str) -> str
```

v1→v2: blueprint_materials 新增 wastefactor 列

定义行：`230`

### `_table_exists`

```python
def _table_exists(conn: sqlite3.Connection, table: str) -> bool
```

检查连接中是否存在指定表

定义行：`274`

### `_add_columns`

```python
def _add_columns(db_path: str, table: str, columns: list[tuple[str, str]]) -> int
```

批量 ADD COLUMN，忽略已存在的列。返回实际新增的列数。

定义行：`283`

### `_get_version`

```python
def _get_version(db_path: str) -> int
```

读取 PRAGMA user_version

定义行：`304`

### `_set_version`

```python
def _set_version(db_path: str, version: int)
```

写入 PRAGMA user_version

定义行：`314`

### `ensure_schema`

```python
def ensure_schema(db_alias: str) -> dict
```

检查并迁移单个库的 schema。

定义行：`329`

### `ensure_all_schemas`

```python
def ensure_all_schemas() -> dict[str, dict]
```

遍历所有 4 个库，执行必要的 schema 迁移。

定义行：`381`

### `get_db_version`

```python
def get_db_version(db_alias: str) -> int | None
```

读取当前库的磁盘版本号（诊断用）

定义行：`394`

### `get_expected_version`

```python
def get_expected_version(db_alias: str) -> int | None
```

返回代码中定义的预期版本号（诊断用）

定义行：`405`

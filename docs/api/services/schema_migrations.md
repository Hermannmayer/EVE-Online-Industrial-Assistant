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

定义行：`46`

### `_migrate_mkt_v2_to_v3`

```python
def _migrate_mkt_v2_to_v3(db_path: str) -> str
```

v2→v3: market_prices(fetch_time) 索引 — 加速 MAX(fetch_time) 与按时间过滤（主线程查询）

定义行：`63`

### `_migrate_user_v1_to_v2`

```python
def _migrate_user_v1_to_v2(db_path: str) -> str
```

v1→v2: user_blueprints 新增 cost_per_run 列

定义行：`76`

### `_migrate_user_v2_to_v3`

```python
def _migrate_user_v2_to_v3(db_path: str) -> str
```

v2→v3: production_plans 新增各扩展列

定义行：`110`

### `_migrate_user_v3_to_v4`

```python
def _migrate_user_v3_to_v4(db_path: str) -> str
```

v3→v4: production_plans 新增生产执行列（绑定蓝图/材料机库/缺口）

定义行：`122`

### `_migrate_user_v4_to_v5`

```python
def _migrate_user_v4_to_v5(db_path: str) -> str
```

v4→v5: hangars/production_plans 加 solar_system_id，并补 v2→v3 遗漏的 facility_cost_mult。

定义行：`148`

### `_migrate_user_v5_to_v6`

```python
def _migrate_user_v5_to_v6(db_path: str) -> str
```

v5→v6: hangars 加设施类型/设施税/改件 JSON 列（机库级工业配置）

定义行：`173`

### `_migrate_user_v6_to_v7`

```python
def _migrate_user_v6_to_v7(db_path: str) -> str
```

v6→v7: plan_blueprint_bindings 多蓝图绑定表（一条计划绑定多张库存蓝图）

定义行：`193`

### `_migrate_user_v7_to_v8`

```python
def _migrate_user_v7_to_v8(db_path: str) -> str
```

v7→v8: 回填 production_plans 空星系快照（从材料机库带出）。

定义行：`208`

### `_migrate_user_v8_to_v9`

```python
def _migrate_user_v8_to_v9(db_path: str) -> str
```

v8→v9: 对缺失 v2 扩展列的 production_plans 重新补列。

定义行：`238`

### `_migrate_user_v9_to_v10`

```python
def _migrate_user_v9_to_v10(db_path: str) -> str
```

v9→v10: production_plans 新增 deducted_materials 列（启动扣减快照，撤销精确返还）。

定义行：`256`

### `_migrate_user_v11_to_v12`

```python
def _migrate_user_v11_to_v12(db_path: str) -> str
```

v11→v12: production_plans 增引用式子项需求列（共享合并 / 母项联动重算）。

定义行：`273`

### `_migrate_user_v10_to_v11`

```python
def _migrate_user_v10_to_v11(db_path: str) -> str
```

v10→v11: price_snapshots 表从 UI 层收口到集中迁移。

定义行：`292`

### `_migrate_bp_v1_to_v2`

```python
def _migrate_bp_v1_to_v2(db_path: str) -> str
```

v1→v2: blueprint_materials 新增 wastefactor 列

定义行：`318`

### `_table_exists`

```python
def _table_exists(conn: sqlite3.Connection, table: str) -> bool
```

检查连接中是否存在指定表

定义行：`366`

### `_add_columns`

```python
def _add_columns(db_path: str, table: str, columns: list[tuple[str, str]]) -> int
```

批量 ADD COLUMN，忽略已存在的列。返回实际新增的列数。

定义行：`375`

### `_open`

```python
def _open(db_path: str) -> sqlite3.Connection
```

打开连接（带 busy_timeout，容忍启动期短暂写锁/被强杀后的句柄未释放）

定义行：`396`

### `_get_version`

```python
def _get_version(db_path: str) -> int
```

读取 PRAGMA user_version

定义行：`403`

### `_set_version`

```python
def _set_version(db_path: str, version: int)
```

写入 PRAGMA user_version

定义行：`413`

### `_backup_db`

```python
def _backup_db(db_path: str) -> str | None
```

迁移前对库做一致快照（VACUUM INTO），返回备份文件路径；失败返回 None。

定义行：`423`

### `_cleanup_old_backups`

```python
def _cleanup_old_backups(backup_dir: str, pattern: str, keep: int=BACKUP_KEEP) -> None
```

保留最近 keep 份备份，删除更早的。删除失败仅告警，不阻断。

定义行：`451`

### `_rebuild_table`

```python
def _rebuild_table(db_path: str, table: str, create_sql: str, copy_columns: list[str]) -> None
```

大变动迁移：重建表结构并保留数据（改列类型/拆表/合并/重命名列）。

定义行：`468`

### `ensure_schema`

```python
def ensure_schema(db_alias: str) -> dict
```

检查并迁移单个库的 schema。

定义行：`505`

### `ensure_all_schemas`

```python
def ensure_all_schemas() -> dict[str, dict]
```

遍历所有 4 个库，执行必要的 schema 迁移。

定义行：`563`

### `get_db_version`

```python
def get_db_version(db_alias: str) -> int | None
```

读取当前库的磁盘版本号（诊断用）

定义行：`576`

### `get_expected_version`

```python
def get_expected_version(db_alias: str) -> int | None
```

返回代码中定义的预期版本号（诊断用）

定义行：`587`

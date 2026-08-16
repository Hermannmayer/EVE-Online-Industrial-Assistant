# Schema 迁移规范

集中式 Schema 管理在 `services/schema_migrations.py`，通过 `PRAGMA user_version` 做版本追踪。
**所有表结构变更必须在迁移函数中完成，禁止在业务代码里写 `ALTER TABLE` / `DROP TABLE`。**

## 版本机制

- 版本号：整数，从 1 开始，每变更 +1（`DB_SCHEMA_VERSIONS[库别名] += 1`）。
- 迁移注册：`_MIGRATIONS[库别名][旧版本] = 迁移函数`，函数签名 `(db_path: str) -> str`，返回人类可读描述。
- `PRAGMA user_version = 0` 视为"未知旧库"，启动时从 v1 起补跑全部迁移（迁移函数必须幂等）。
- 库磁盘版本 > 代码版本时跳过（视为降级/手改，告警不迁移）。
- 启动时 `ensure_all_schemas()`（Main.py）依次迁移 4 个库。

## 自动备份（迁移前快照）

`ensure_schema` 检测到需要迁移时，会先对库做一致快照：

- 位置：`<库目录>/backups/`（如 `database/backups/user-20260816-124100.db`）。
- 方式：SQLite `VACUUM INTO`，WAL 一致、不阻塞。
- 保留：最近 `BACKUP_KEEP = 5` 份，更早自动清理。
- 失败：仅告警、不阻断迁移（备份是保险，不是前置依赖）。

**手动恢复**（迁移出问题或需回滚时）：

```bash
# 1. 完全退出程序
# 2. 确认目标备份（看 mtime）
ls database/backups/
# 3. 用备份覆盖当前库（可先另存当前损坏库作现场）
cp database/backups/user-20260816-124100.db database/user.db
# 4. 重新启动，程序会按快照版本继续迁移
```

## 加列变更

只新增列（最常见场景）→ 用 `_add_columns`，幂等（列已存在自动跳过）：

```python
def _migrate_user_vN_to_vN1(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "production_plans"):
            return "production_plans 表不存在，跳过"
    finally:
        conn.close()
    net = _add_columns(db_path, "production_plans", [("new_col", "REAL DEFAULT 0")])
    return f"production_plans 新增列 (新增 {net} 列)"
```

## 大变动（改列类型 / 拆表 / 合并 / 重命名列）

SQLite 的 `ALTER TABLE` 只支持加列，大变动必须"建新表 → 复制 → 换名"。
用 `_rebuild_table`（单事务，失败自动回滚，数据完好，幂等）：

```python
def _migrate_xxx_vN_to_vN1(db_path: str) -> str:
    _rebuild_table(
        db_path,
        table="production_plans",
        create_sql="""
            CREATE TABLE production_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_type_id INTEGER NOT NULL,
                -- ...新结构...
                new_col TEXT NOT NULL DEFAULT ''
            )
        """,
        copy_columns=["id", "product_type_id", "status", "notes"],  # 从旧表带过的列
    )
    return "production_plans 重建：新增 new_col"
```

要求：

- `create_sql` 建的表名必须与原表同名。
- `copy_columns` 的列在新表必须存在（旧列类型变更可在 SELECT 时用 CAST 包裹，但 `_rebuild_table` 接受的是列名列表，复杂转换请手写迁移）。
- 涉及外键/索引/触发器时，`create_sql` 中一并重建（SQLite 的 `RENAME` 不会自动迁移索引）。
- 未在 `copy_columns` 里的旧列会丢失 —— 新增列填默认值，`copy_columns` 之外的旧数据不保留，请确认。

## 注册清单（每次变更必做）

1. `DB_SCHEMA_VERSIONS[库] += 1`
2. 新增 `_MIGRATIONS[库][旧版本] = 迁移函数`
3. `tests/conftest.py` 中对应库的 `PRAGMA user_version` 同步到最新（`_create_temp_databases` 及各 `_create_user_vX` 构造）
4. 补迁移测试（`tests/test_schema_migrations.py`）：旧版本库迁移到最新 + 幂等 + 缺表跳过

## 测试要求

迁移测试遵循现有模式：`tmp_path` + `monkeypatch.setitem(sm._DB_PATH_MAP, "user", str(db_path))`，
构造旧版本库 → 断言迁移后列/索引/版本号正确 → 二次运行断言 `applied == []`。
迁移会触发自动备份到 `tmp_path/backups/`（跟随库文件目录），断言备份存在且为迁移前版本。

# services.db_backup

> 源文件 `services/db_backup.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

用户数据的本地备份与导出。

**只备份 `user.db`** —— 那才是用户自己的东西（生产计划 / 机库 / 库存 / 蓝图绑定 /
ESI 令牌 / 快照台账）。`reference.db` 与 `blueprint.db` 是可重下发的 SDE 缓存、
`market.db` 是行情缓存，重建即可，备份它们只是白占空间（单个几百 MB）。

**备份目录单独一层** `<库目录>/backups/user/`，与 `schema_migrations` 的「迁移前快照」
（`<库目录>/backups/<name>-<ts>.db`，保留 5 份）**分开**：两边的保留策略各管各的，
否则用户设「保留 3 份」会把迁移快照一起清掉、迁移回滚就没得退了。

两个调用方（`services/` 里新建模块的门槛，见 CLAUDE.md「克制条款」第 1 条）：
- `ui_qml/bridge/settings_bridge.py` —— 设置页的「立即备份 / 导出」
- `ui_qml/shell_window.py` —— 启动时「每天一次」的自动备份

## 函数

### `user_db_path`

```python
def user_db_path() -> str
```

user.db 路径 —— **调用时**读，不 import 模块常量。

定义行：`38`

### `backup_dir`

```python
def backup_dir() -> str
```

本次要写入的备份目录（不存在则创建）。

定义行：`51`

### `list_backups`

```python
def list_backups() -> list[str]
```

已有备份路径，**新的在前**（设置页显示份数用）。

定义行：`58`

### `_cleanup`

```python
def _cleanup(keep: int) -> int
```

只保留最近 keep 份，返回删掉的份数。删不动仅告警，不阻断备份。

定义行：`66`

### `backup_user_db`

```python
def backup_user_db(*, keep: int=BACKUP_KEEP_DEFAULT) -> str | None
```

``VACUUM INTO`` 一份 user.db 的一致快照，返回备份路径；失败返回 None。

定义行：`78`

### `maybe_daily_backup`

```python
def maybe_daily_backup(*, keep: int=BACKUP_KEEP_DEFAULT, today: str | None=None) -> str | None
```

「每天最多一次」的自动备份；今天已经备过就返回 None（不重复占空间）。

定义行：`116`

### `export_user_db`

```python
def export_user_db(dest_path: str) -> str | None
```

把 user.db 另存到用户指定位置（同样走 `VACUUM INTO`，保证一致）。

定义行：`133`

### `restore_user_db`

```python
def restore_user_db(backup_path: str, *, keep: int=BACKUP_KEEP_DEFAULT) -> bool
```

用 ``backup_path`` 覆盖当前 user.db。成功返回 True。

定义行：`160`

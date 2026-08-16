# services.user_settings

> 源文件 `services/user_settings.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

用户设置集中读写 — settings.json。

## 函数

### `_migrate_settings`

```python
def _migrate_settings(data: dict) -> dict
```

惰性升级 settings 结构：版本 < CURRENT 时逐级迁移并落盘。

定义行：`21`

### `load_settings`

```python
def load_settings() -> dict
```

读取 settings.json，文件不存在或损坏时返回 &#123;&#125;；结构过期时先升级再返回。

定义行：`38`

### `_write_all`

```python
def _write_all(data: dict) -> None
```

全量写盘（含删除键）。

定义行：`50`

### `save_settings`

```python
def save_settings(data: dict) -> None
```

read-modify-write：把传入键合并进现有 settings.json（保留其它键）。

定义行：`57`

### `get_default_hangar_id`

```python
def get_default_hangar_id(key: str) -> int | None
```

读取默认机库设置（default_*_hangar_id 键）。

定义行：`64`

### `set_default_hangar_id`

```python
def set_default_hangar_id(key: str, hangar_id: int | None) -> None
```

写默认机库设置；None 时删除该键（对齐 TopToolbar -1 pop 语义）。

定义行：`70`

# services.user_settings

> 源文件 `services/user_settings.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

用户设置集中读写 — settings.json。

现有各调用方（TopToolbar 等）各自 json 读改写同一文件，本模块提供集中读写，
不强迁既有调用方；新增的默认机库设置等统一走这里。

## 函数

### `_migrate_settings`

```python
def _migrate_settings(data: dict) -> dict
```

惰性升级 settings 结构：版本 < CURRENT 时逐级迁移并落盘。

定义行：`23`

### `_read_raw`

```python
def _read_raw() -> dict | None
```

读原始 JSON：文件不存在 → &#123;&#125;；存在但读不出来（损坏/被占用）→ None。

定义行：`40`

### `_backup_corrupt`

```python
def _backup_corrupt() -> None
```

settings.json 读不出来时先另存现场，再让调用方重建。

定义行：`56`

### `load_settings`

```python
def load_settings() -> dict
```

读取 settings.json，文件不存在或损坏时返回 &#123;&#125;；结构过期时先升级再返回。

定义行：`67`

### `_write_all`

```python
def _write_all(data: dict) -> None
```

全量写盘（含删除键）。

定义行：`77`

### `save_settings`

```python
def save_settings(data: dict) -> None
```

read-modify-write：把传入键合并进现有 settings.json（保留其它键）。

定义行：`84`

### `get_default_hangar_id`

```python
def get_default_hangar_id(key: str) -> int | None
```

读取默认机库设置（default_*_hangar_id 键）。

定义行：`98`

### `set_default_hangar_id`

```python
def set_default_hangar_id(key: str, hangar_id: int | None) -> None
```

写默认机库设置；None 时删除该键（对齐 TopToolbar -1 pop 语义）。

定义行：`104`

### `get_price_settings`

```python
def get_price_settings() -> dict
```

价格来源设置 &#123;mat_hub, mat_price_type, mat_mult, prod_hub, prod_price_type, prod_mult&#125;。

定义行：`126`

### `get_material_price_mult`

```python
def get_material_price_mult() -> float
```

材料价格调整系数（默认 1.0）。

定义行：`131`

### `set_material_price_mult`

```python
def set_material_price_mult(value: float) -> None
```

写回材料价格调整系数（读-改-写，只动 price_settings.mat_mult，保留其它键）。

定义行：`145`

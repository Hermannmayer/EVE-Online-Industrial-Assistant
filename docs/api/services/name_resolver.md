# services.name_resolver

> 源文件 `services/name_resolver.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。

解析优先级: terminology.item_overrides > item.zh_name > item.en_name > str(id)

## 函数

### `_ensure_name_indexes`

```python
def _ensure_name_indexes(conn: sqlite3.Connection | sqlite3.Cursor) -> None
```

模糊匹配前按需给 item 表补 zh_name / en_name 索引。

定义行：`22`

### `_terminology_reverse`

```python
def _terminology_reverse() -> dict[str, int]
```

terminology.item_overrides 反向索引 &#123;覆盖名: type_id&#125;（基础矿物 34-40 等不在 item 表）。

定义行：`41`

### `_exact_type_id`

```python
def _exact_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None
```

item 表精确匹配 zh_name / en_name，未命中返回 None。

定义行：`54`

### `_exact_type_ids_batch`

```python
def _exact_type_ids_batch(conn: sqlite3.Connection | sqlite3.Cursor, names: list[str]) -> dict[str, int]
```

一次 IN 查询批量精确匹配 &#123;名字: type_id&#125;。

定义行：`60`

### `_like_type_id`

```python
def _like_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None
```

LIKE 模糊匹配（含引号归一化回退），未命中返回 None。

定义行：`89`

### `search_item_type_id`

```python
def search_item_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None
```

名称→type_id：精确 → terminology 反向 → LIKE 模糊 → 引号归一化 LIKE。

定义行：`114`

### `search_item_type_ids_batch`

```python
def search_item_type_ids_batch(conn: sqlite3.Connection | sqlite3.Cursor, names: list[str]) -> dict[str, int | None]
```

批量名称→type_id，键为原样传入的名字（含重复项与空串）。

定义行：`138`

### `resolve_item_name`

```python
def resolve_item_name(conn: sqlite3.Connection | sqlite3.Cursor, type_id: int) -> str
```

统一物品名称解析：term override → item 表 → str(id)。

定义行：`174`

### `resolve_item_names_batch`

```python
def resolve_item_names_batch(conn: sqlite3.Connection, type_ids: list[int]) -> dict[int, str]
```

批量查询物品名称，减少数据库往返。

定义行：`199`

### `mat_name`

```python
def mat_name(mat_id: int, conn: sqlite3.Connection) -> str
```

查询材料名称，优先查 item 表，基础矿物走 terminology.json 覆盖。

定义行：`244`

### `resolve_system_name`

```python
def resolve_system_name(conn: sqlite3.Connection, solar_system_id: int) -> str
```

星系显示名：中文 (英文)。中文优先 terminology.system_names，fallback 英文 → str(id)。

定义行：`249`

### `resolve_system_names_batch`

```python
def resolve_system_names_batch(conn: sqlite3.Connection, solar_system_ids: list[int]) -> dict[int, str]
```

批量查询星系显示名（中英对照），减少数据库往返。

定义行：`270`

### `resolve_system_display_names_batch`

```python
def resolve_system_display_names_batch(solar_system_ids: list[int]) -> dict[int, str]
```

批量查询星系显示名；异常返回空 dict。

定义行：`291`

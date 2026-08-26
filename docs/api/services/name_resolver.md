# services.name_resolver

> 源文件 `services/name_resolver.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。

解析优先级: terminology.item_overrides > item.zh_name > item.en_name > str(id)

## 函数

### `search_item_type_id`

```python
def search_item_type_id(conn: sqlite3.Connection, name: str) -> int | None
```

名称→type_id：精确 → terminology 反向 → LIKE 模糊 → 引号归一化 LIKE。

定义行：`17`

### `resolve_item_name`

```python
def resolve_item_name(conn: sqlite3.Connection | sqlite3.Cursor, type_id: int) -> str
```

统一物品名称解析：term override → item 表 → str(id)。

定义行：`58`

### `resolve_item_names_batch`

```python
def resolve_item_names_batch(conn: sqlite3.Connection, type_ids: list[int]) -> dict[int, str]
```

批量查询物品名称，减少数据库往返。

定义行：`83`

### `mat_name`

```python
def mat_name(mat_id: int, conn: sqlite3.Connection) -> str
```

查询材料名称，优先查 item 表，基础矿物走 terminology.json 覆盖。

定义行：`128`

### `resolve_system_name`

```python
def resolve_system_name(conn: sqlite3.Connection, solar_system_id: int) -> str
```

星系显示名：中文 (英文)。中文优先 terminology.system_names，fallback 英文 → str(id)。

定义行：`133`

### `resolve_system_names_batch`

```python
def resolve_system_names_batch(conn: sqlite3.Connection, solar_system_ids: list[int]) -> dict[int, str]
```

批量查询星系显示名（中英对照），减少数据库往返。

定义行：`154`

### `resolve_system_display_name`

```python
def resolve_system_display_name(solar_system_id: int | None) -> str
```

按星系 ID 查询显示名（中文 (英文)）；无/异常返回空串。

定义行：`175`

### `resolve_system_display_names_batch`

```python
def resolve_system_display_names_batch(solar_system_ids: list[int]) -> dict[int, str]
```

批量查询星系显示名；异常返回空 dict。

定义行：`188`

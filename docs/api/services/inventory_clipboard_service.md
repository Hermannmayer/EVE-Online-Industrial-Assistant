# services.inventory_clipboard_service

> 源文件 `services/inventory_clipboard_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID，并过滤蓝图行。

材料仓库只导入材料：已匹配行按物品种类过滤蓝图，未匹配行按名字标记过滤（见
``_filter_blueprint_rows``），避免游戏内复制整仓时把蓝图（含 ME/TE/流程列）当成
材料导入。

## 函数

### `parse_clipboard`

```python
def parse_clipboard(raw: str) -> tuple[list[dict], int]
```

解析 EVE 剪贴板 → (材料行, 被过滤的蓝图行数)。

定义行：`19`

### `parse_clipboard_rows`

```python
def parse_clipboard_rows(conn: sqlite3.Connection | sqlite3.Cursor, raw: str) -> tuple[list[dict], int]
```

按 ref 连接解析剪贴板并过滤蓝图行（可单测，不依赖容器）。

定义行：`25`

### `_filter_blueprint_rows`

```python
def _filter_blueprint_rows(conn: sqlite3.Connection | sqlite3.Cursor, rows: list[dict]) -> tuple[list[dict], int]
```

丢弃蓝图行：已匹配行按物品种类，未匹配行按名字标记。

定义行：`65`

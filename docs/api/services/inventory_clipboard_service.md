# services.inventory_clipboard_service

> 源文件 `services/inventory_clipboard_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID，并过滤蓝图行。

材料仓库只导入材料：已匹配行按物品种类过滤蓝图，未匹配行按名字标记过滤（见
``_filter_blueprint_rows``），避免游戏内复制整仓时把蓝图（含 ME/TE/流程列）当成
材料导入。

另有 `parse_purchase_clipboard`：「钱包 → 交易记录」的**买入行**（带单价）入库，
与整仓复制是两种文本，故不共用上面的蓝图过滤 —— 买蓝图同样是正当入库。

## 函数

### `parse_clipboard`

```python
def parse_clipboard(raw: str) -> tuple[list[dict], int]
```

解析 EVE 剪贴板 → (材料行, 被过滤的蓝图行数)。

定义行：`23`

### `parse_clipboard_rows`

```python
def parse_clipboard_rows(conn: sqlite3.Connection | sqlite3.Cursor, raw: str) -> tuple[list[dict], int]
```

按 ref 连接解析剪贴板并过滤蓝图行（可单测，不依赖容器）。

定义行：`29`

### `parse_purchase_clipboard`

```python
def parse_purchase_clipboard(raw: str) -> tuple[list[dict], dict]
```

解析「钱包 → 交易记录」的买入行 → (行, stats)。stats 见 `parse_purchase_records`。

定义行：`74`

### `parse_purchase_rows`

```python
def parse_purchase_rows(conn: sqlite3.Connection | sqlite3.Cursor, raw: str) -> tuple[list[dict], dict]
```

按 ref 连接解析买入行并匹配 type_id（可单测，不依赖容器）。

定义行：`80`

### `_filter_blueprint_rows`

```python
def _filter_blueprint_rows(conn: sqlite3.Connection | sqlite3.Cursor, rows: list[dict]) -> tuple[list[dict], int]
```

丢弃蓝图行：已匹配行按物品种类，未匹配行按名字标记。

定义行：`108`

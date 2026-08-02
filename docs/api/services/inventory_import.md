# services.inventory_import

> 源文件 `services/inventory_import.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

剪贴板导入纯函数 — 增量/全量行计算与导入前后差异对比。

## 函数

### `split_clipboard_lines`

```python
def split_clipboard_lines(raw: str) -> list[dict]
```

解析 EVE 剪贴板 → [&#123;name, qty&#125;]（纯函数，无 DB 依赖）。

定义行：`17`

### `compute_transfer_rows`

```python
def compute_transfer_rows(rows: list[dict], source_stock: dict[int, int], target_stock: dict[int, int] | None=None) -> list[dict]
```

按剪贴板行生成移库计划（纯函数）。

定义行：`55`

### `compute_row_delta`

```python
def compute_row_delta(mode: str, qty: int, current: int) -> tuple[int, int]
```

计算单行导入的 (delta, final)。

定义行：`92`

### `compute_import_diff`

```python
def compute_import_diff(before: dict[int, tuple[int, float]], after: dict[int, tuple[int, float]], names: dict[int, str], type_ids: list[int]) -> list[dict]
```

对比导入前后库存，返回发生变化行列表。

定义行：`112`

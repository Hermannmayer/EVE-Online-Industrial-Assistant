# services.inventory_import

> 源文件 `services/inventory_import.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

剪贴板导入纯函数 — 增量/全量行计算与导入前后差异对比。

本模块只做纯逻辑（无 DB 依赖），供 ImportReviewDialog 与 HangarTab 复用。

## 函数

### `split_clipboard_lines`

```python
def split_clipboard_lines(raw: str) -> list[dict]
```

解析 EVE 剪贴板 → [&#123;name, qty&#125;]（纯函数，无 DB 依赖）。

定义行：`17`

### `compute_row_delta`

```python
def compute_row_delta(mode: str, qty: int, current: int) -> tuple[int, int]
```

计算单行导入的 (delta, final)。

定义行：`55`

### `merge_same_type_rows`

```python
def merge_same_type_rows(items: list[dict]) -> list[dict]
```

把**同一个 type_id 的多堆**合并成一行、数量相加（纯函数，无 DB/Qt 依赖）。

定义行：`75`

### `compute_missing_in_hangar`

```python
def compute_missing_in_hangar(hangar_qty: dict[int, int], clipboard_type_ids: set[int]) -> dict[int, int]
```

全量同步的**反向差集**：「目标机库里有、剪贴板里没有」的物品 → &#123;type_id: 现有数量&#125;。

定义行：`117`

### `compute_import_diff`

```python
def compute_import_diff(before: dict[int, tuple[int, float]], after: dict[int, tuple[int, float]], names: dict[int, str], type_ids: list[int]) -> list[dict]
```

对比导入前后库存，返回发生变化行列表。

定义行：`136`

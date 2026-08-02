# services.plan_category

> 源文件 `services/plan_category.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划类别推导 — 制造/拷贝/发明/反应。

## 函数

### `category_symbol`

```python
def category_symbol(cat: str) -> str
```

类别符号（⚙📋💡⚗）。

定义行：`36`

### `category_color`

```python
def category_color(cat: str) -> str | None
```

类别行底色（hex）；制造返回 None（默认底色）。

定义行：`41`

### `load_category_map`

```python
def load_category_map(conn: Connection, blueprint_type_ids: list[int]) -> dict[int, str]
```

蓝图 id → 类别。优先级：reaction → invention → copying → manufacturing。

定义行：`46`

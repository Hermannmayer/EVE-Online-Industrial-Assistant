# services.plan_category

> 源文件 `services/plan_category.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划类别推导 — 制造/拷贝/发明/反应。

production_plans 无 activity 字段（计划全为制造），类别从蓝图活动数据推导：
- reaction：蓝图有 activity='reaction' 行
- invention(T2/T3)：制造蓝图是 activity='invention' 的产物
- copying：蓝图有 activity='copying' 行
- manufacturing：其余

约定：conn 的 primary 库须含蓝图表（reference.db 或 blueprint.db）。

## 函数

### `category_symbol`

```python
def category_symbol(cat: str) -> str
```

类别符号（⚙📋💡⚗）。

定义行：`29`

### `load_category_map`

```python
def load_category_map(conn: Connection, blueprint_type_ids: list[int]) -> dict[int, str]
```

蓝图 id → 类别。优先级：reaction → invention → copying → manufacturing。

定义行：`34`

# services.plan_category

> 源文件 `services/plan_category.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

生产计划类别推导 — 制造/复制/发明/反应。

production_plans 无 activity 字段（计划全为制造作业），类别从蓝图活动数据推导，
描述的是**这张蓝图的用途性质**（对齐游戏工业窗口的作业类型）：
- reaction：蓝图有 activity='reaction' 行
- invention(T2/T3)：该蓝图是 activity='invention' 的产物
- copying：蓝图有 activity='copying' 行**且无 manufacturing 行**（只能复制、不能制造）
- manufacturing：其余（含 T1 与 T2/T3 的制造蓝图 —— T2 生产同样是制造作业）

⚠️ copying 判据必须排除 manufacturing：EVE 里几乎每个可制造蓝图都能复制，
只看 copying 会把普通制造蓝图误判成复制类（实测全库 3283 个 → 修正后 70 个）。

材料效率研究 / 生产效率研究不在类别内 —— 本应用只能建制造计划，无研究作业。

约定：conn 的 primary 库须含蓝图表（reference.db 或 blueprint.db）。

## 函数

### `category_symbol`

```python
def category_symbol(cat: str) -> str
```

类别符号（⚙📋💡⚗）。

定义行：`35`

### `load_category_map`

```python
def load_category_map(conn: Connection, blueprint_type_ids: list[int]) -> dict[int, str]
```

蓝图 id → 类别。优先级：reaction → invention → copying → manufacturing。

定义行：`40`

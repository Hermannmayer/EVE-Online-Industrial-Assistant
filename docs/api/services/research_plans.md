# services.research_plans

> 源文件 `services/research_plans.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

科研计划的蓝图选型与落库 — 拷贝/发明/研究建计划行的唯一入口。

UI（蓝图库右键、全物品页右键）与「研究分析」对话框都调这里，
SQL 不散落到各处。

关键概念（语义契约见 services.plan_job_kinds）：
    product_type_id    本计划的产物。科研行恒为**蓝图 type_id**
                       （发明 = 产出的 T2 蓝图；拷贝/研究 = 被操作的蓝图）。
    blueprint_type_id  同 product_type_id（科研行的输入蓝图与产物是同一张）。
    runs               拷贝 = 每份拷贝的授权流程；发明 = 尝试次数；研究 = 目标等级。
    parallels          拷贝 = 产出份数；其余按 1 计。

## 函数

### `resolve_invention_source`

```python
def resolve_invention_source(conn, blueprint_type_id: int) -> dict[str, Any] | None
```

给定 T2/T3 蓝图，反查它的发明来源与全部可能的产物。

定义行：`25`

### `invention_base_runs`

```python
def invention_base_runs(conn, t2_blueprint_type_id: int, t1_blueprint_type_id: int) -> int
```

发明产出的 T2 BPC 基础流程数 = min(T1 拷贝上限, T2 制造上限)。

定义行：`72`

### `research_cost_per_run`

```python
def research_cost_per_run(db, blueprint_type_id: int, *, solar_system_id: int | None=None, char_config: dict | None=None) -> dict[str, Any] | None
```

「该蓝图每流程的研究成本」——供蓝图库「自动填写每流程成本」与「研究分析」使用。

定义行：`100`

### `_materials`

```python
def _materials(conn, blueprint_type_id: int, activity: str) -> list[tuple[int, int]]
```

蓝图某活动的材料清单 [(type_id, qty)]。

定义行：`192`

### `_prices`

```python
def _prices(conn, type_ids: list[int]) -> dict[int, float]
```

adjusted_price 优先（0/缺失 → sell_price → buy_price）。

定义行：`207`

### `_skill_levels`

```python
def _skill_levels(conn, blueprint_type_id: int, activity: str, skills: dict) -> tuple[int, int, int]
```

该活动要求的两个科学技能 + 加密技术原理的等级。

定义行：`221`

### `plan_type_name`

```python
def plan_type_name(plan: dict) -> str
```

给计划表「产品」列展示的研究产物名（拷贝/发明/研究各有说法）。

定义行：`246`

### `create_research_plan`

```python
def create_research_plan(blueprint_type_id: int, *, activity: str, blueprint_name: str, runs: int=1, parallels: int=1, mat_hangar_id: int | None=None, deposit_hangar_id: int | None=None, solar_system_id: int | None=None, char_name: str='', facility: str='', decryptor_type_id: int | None=None, success_rate: float | None=None, research_target_level: int=0, mat_hub: str='Jita', sell_hub: str='Jita') -> int
```

建一条科研计划行（pending，含科研专属列），返回 plan_id；失败 → -1。

定义行：`263`

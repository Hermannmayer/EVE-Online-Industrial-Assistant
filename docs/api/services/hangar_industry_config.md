# services.hangar_industry_config

> 源文件 `services/hangar_industry_config.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

机库工业配置解析服务 — 设施类型/结构改装件 → 制造加成。

每个机库可配置所在设施类型（决定结构本体基础加成）+ 结构改装件列表
（材料/时间/成本效率钻机，加成数值来自 ESI 拉取的 structure_rigs 表）+ 设施税。
制造计划从材料机库读取这些配置，影响材料/时间/安装费成本。

叠加方式（EVE 机制，乘算）：有效倍率 = 结构本体基数 × Π(1 + 改件加成/100)。

2026-10-17 审计 01-13 补齐：`structure_rigs` 新增 `cost_bonus` 列（发明/ME/TE/拷贝
成本优化钻机，ESI attributeEngRigCostBonus=2595）；`resolve_hangar_industry_config`
的成本倍率现在乘上改件成本加成。制造类的「蓝图类别 → 改件类别」映射在
`domain.rigs`（纯函数），真实用户机库 `rigs` 为空 → 可观测零漂移。

## 函数

### `_default_db`

```python
def _default_db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。

定义行：`24`

### `rig_category_label`

```python
def rig_category_label(cat: str) -> str
```

改件类别标签：terminology.json（rig_categories）为权威来源，内置表兜底。

定义行：`131`

### `parse_rigs`

```python
def parse_rigs(raw: str | None) -> list[int]
```

json.loads 容错：None/非法 JSON/非列表 → []，元素 int 化。

定义行：`136`

### `get_rig_catalog`

```python
def get_rig_catalog(facility_type: str | None, *, _db: DatabaseManager | None=None) -> list[dict]
```

返回该设施可装配的改件目录（含 ESI 加成），供机库设置 UI 使用。NPC/未选 → []。

定义行：`155`

### `validate_rig_set`

```python
def validate_rig_set(rig_ids: list[int], facility_type: str | None, *, _db: DatabaseManager | None=None) -> list[str]
```

返回违规描述列表（空=合法）。规则：同制造类别互斥、尺寸匹配、未知 id。

定义行：`204`

### `_rig_matches_activity`

```python
def _rig_matches_activity(rig_group: int, *, activity: str | None, blueprint_category: str | None) -> bool
```

该改件是否作用于当前活动/蓝图类别。

定义行：`239`

### `_load_rig_bonuses`

```python
def _load_rig_bonuses(rig_ids: list[int], *, activity: str | None, _db: DatabaseManager | None) -> tuple[dict[int, tuple[float, float, float]], dict[int, int] | None] | None
```

读改件加成（mat/time/cost）与 item.group 归属；表未就绪 → None。

定义行：`269`

### `resolve_rig_multipliers`

```python
def resolve_rig_multipliers(rig_ids: list[int], *, activity: str | None=None, blueprint_category: str | None=None, _db: DatabaseManager | None=None) -> tuple[float, float]
```

(材料倍率, 时间倍率) 乘算叠加：Π(1 + bonus/100)。structure_rigs 缺行按加成 0。

定义行：`318`

### `resolve_rig_cost_multiplier`

```python
def resolve_rig_cost_multiplier(rig_ids: list[int], *, activity: str | None=None, blueprint_category: str | None=None, _db: DatabaseManager | None=None) -> float
```

成本倍率 Π(1 + cost_bonus/100)；无数据 → 1.0（零漂移）。

定义行：`351`

### `_blueprint_rig_category`

```python
def _blueprint_rig_category(product_type_id: int | None, *, _db: DatabaseManager | None) -> str | None
```

产物 type_id → rig 制造类别 key（查 reference.db item，纯映射在 `domain.rigs`）。

定义行：`381`

### `resolve_hangar_industry_config`

```python
def resolve_hangar_industry_config(hangar_id: int | None, *, activity: str | None=None, blueprint_category: str | None=None, product_type_id: int | None=None, _db: DatabaseManager | None=None) -> dict
```

解析机库工业配置 → &#123;structure_mat_saving, structure_time_mod, structure_cost_mult,
facility_tax, facility_type, rig_ids&#125;。无机库/未配置 → 全默认（倍率 1.0、税 None）。

定义行：`404`

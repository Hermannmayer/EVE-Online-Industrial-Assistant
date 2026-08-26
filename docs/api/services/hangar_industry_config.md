# services.hangar_industry_config

> 源文件 `services/hangar_industry_config.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

机库工业配置解析服务 — 设施类型/结构改装件 → 制造加成。

每个机库可配置所在设施类型（决定结构本体基础加成）+ 结构改装件列表
（材料/时间效率钻机，加成数值来自 ESI 拉取的 structure_rigs 表）+ 设施税。
制造计划从材料机库读取这些配置，影响材料/时间/安装费成本。

叠加方式（EVE 机制，乘算）：有效倍率 = 结构本体基数 × Π(1 + 改件加成/100)。

## 函数

### `_default_db`

```python
def _default_db() -> DatabaseManager
```

惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。

定义行：`18`

### `rig_category_label`

```python
def rig_category_label(cat: str) -> str
```

改件类别标签：terminology.json（rig_categories）为权威来源，内置表兜底。

定义行：`125`

### `parse_rigs`

```python
def parse_rigs(raw: str | None) -> list[int]
```

json.loads 容错：None/非法 JSON/非列表 → []，元素 int 化。

定义行：`130`

### `get_rig_catalog`

```python
def get_rig_catalog(facility_type: str | None, *, _db: DatabaseManager | None=None) -> list[dict]
```

返回该设施可装配的改件目录（含 ESI 加成），供机库设置 UI 使用。NPC/未选 → []。

定义行：`149`

### `validate_rig_set`

```python
def validate_rig_set(rig_ids: list[int], facility_type: str | None, *, _db: DatabaseManager | None=None) -> list[str]
```

返回违规描述列表（空=合法）。规则：同制造类别互斥、尺寸匹配、未知 id。

定义行：`198`

### `resolve_rig_multipliers`

```python
def resolve_rig_multipliers(rig_ids: list[int], *, _db: DatabaseManager | None=None) -> tuple[float, float]
```

(材料倍率, 时间倍率) 乘算叠加：Π(1 + bonus/100)。structure_rigs 缺行按加成 0。

定义行：`222`

### `resolve_hangar_industry_config`

```python
def resolve_hangar_industry_config(hangar_id: int | None, *, _db: DatabaseManager | None=None) -> dict
```

解析机库工业配置 → &#123;structure_mat_saving, structure_time_mod, structure_cost_mult,
facility_tax, facility_type, rig_ids&#125;。无机库/未配置 → 全默认（倍率 1.0、税 None）。

定义行：`252`

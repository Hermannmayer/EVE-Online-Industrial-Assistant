# services.char_capacity

> 源文件 `services/char_capacity.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

人物产线容量 — 由角色技能（高级量产技术）决定最大并行产线条数。

## 函数

### `capacity_line_for_category`

```python
def capacity_line_for_category(category: str) -> str
```

计划 category → 容量线型（copying/invention→research，未知→manufacturing）。

定义行：`42`

### `line_label`

```python
def line_label(line: str) -> str
```

线型 → 中文标签（占用区展示）。

定义行：`51`

### `_sum_skill_levels`

```python
def _sum_skill_levels(skills: dict, names: tuple[str, ...]) -> int
```

纯函数：多个技能等级之和（缺省 0）。

定义行：`56`

### `max_lines_for_category`

```python
def max_lines_for_category(char_name: str | None, line: str, *, skills: dict | None=None) -> int
```

某线型最大产线条数 = 1 + Σ(该线型技能等级)。满级（两技能各 5）= 11。

定义行：`67`

### `active_lines_by_category`

```python
def active_lines_by_category(plans: list[dict]) -> dict[str, dict[str, int]]
```

从已 enrich category 的活跃计划行聚合 &#123;char_name(''=未分配): &#123;线型: SUM(parallels)&#125;&#125;。

定义行：`79`

### `_skill_key`

```python
def _skill_key() -> str
```

"高级量产技术"（skill_names 注册；未命中时兜底中文名）。惰性求值，避免 import 时加载术语表。

定义行：`95`

### `max_production_lines`

```python
def max_production_lines(char_name: str | None) -> int
```

人物最大并行产线条数 = 1 + 高级量产技术等级（默认 0 → 1 条）。

定义行：`100`

### `active_production_lines`

```python
def active_production_lines(char_name: str | None) -> int
```

人物当前占用产线条数 = SUM(parallels)（仅 in_progress/running）。

定义行：`109`

### `active_lines_per_character`

```python
def active_lines_per_character() -> dict[str, int]
```

全人物占用 &#123;char_name: active&#125;（未分配归空串）。

定义行：`129`

### `character_line_usage`

```python
def character_line_usage(char_name: str | None) -> tuple[int, int]
```

(active, max) 供产线占用条渲染。

定义行：`143`

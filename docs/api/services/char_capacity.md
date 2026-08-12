# services.char_capacity

> 源文件 `services/char_capacity.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

人物产线容量 — 由角色技能（高级量产技术）决定最大并行产线条数。

## 函数

### `_skill_key`

```python
def _skill_key() -> str
```

"高级量产技术"（skill_names 注册；未命中时兜底中文名）。惰性求值，避免 import 时加载术语表。

定义行：`14`

### `max_production_lines`

```python
def max_production_lines(char_name: str | None) -> int
```

人物最大并行产线条数 = 1 + 高级量产技术等级（默认 0 → 1 条）。

定义行：`19`

### `active_production_lines`

```python
def active_production_lines(char_name: str | None) -> int
```

人物当前占用产线条数 = SUM(parallels)（仅 in_progress/running）。

定义行：`28`

### `active_lines_per_character`

```python
def active_lines_per_character() -> dict[str, int]
```

全人物占用 &#123;char_name: active&#125;（未分配归空串）。

定义行：`48`

### `character_line_usage`

```python
def character_line_usage(char_name: str | None) -> tuple[int, int]
```

(active, max) 供产线占用条渲染。

定义行：`62`

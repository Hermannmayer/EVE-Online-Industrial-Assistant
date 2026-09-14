# services.plan_gantt

> 源文件 `services/plan_gantt.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

甘特图排期 —— 纯计算，不依赖 Qt。

原先这套逻辑长在 `ui_pyside6/views/industry/gantt_view.py` 的 QWidget 里，
与 QPainter 自绘混在一起。阶段 2b 把绘制交给 QML，排期计算上移到服务层，
这样它可以脱离界面单测（原先要构造 QWidget 才能测）。

排期口径（与旧实现一致）：
- **行序**取计划树序（母项在前、子项紧随），与项目其它视图一致；
- **时间**上子项先跑（同组子项之间并行、都从 0 起），母项接在全部子项结束之后 ——
  母项依赖子项产出，不能一起开跑；跨组不串行（不同产品各自从 0 起）；
- 柱形条末端标出预计完成时刻（本地时区）。

## 函数

### `build_rows`

```python
def build_rows(plans: list[dict]) -> list[dict]
```

把计划列表排成「按 BOM 依赖串行」的甘特条。

定义行：`28`

### `max_hours`

```python
def max_hours(rows: list[dict]) -> int
```

时间轴上限：覆盖最右侧柱形条，向上取整到 `AXIS_GRANULARITY` 的倍数。

定义行：`64`

### `_apply_dependencies`

```python
def _apply_dependencies(rows: list[dict]) -> None
```

同组内按 `component_parent_type_id` 建依赖边：父项 start = max(子项 end)。

定义行：`71`

### `_parent_row`

```python
def _parent_row(row: dict, by_tid: dict, mother: dict | None) -> dict | None
```

行在时间上的前驱：同组内 `component_parent_type_id` 指向的那一行。

定义行：`104`

### `_level`

```python
def _level(plan: dict) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`116`

### `end_time_text`

```python
def end_time_text(plan: dict, end_hours: float, now: datetime | None=None) -> str
```

柱形条末端的预计完成时刻（**本地时区** MM-DD HH:MM）。

定义行：`120`

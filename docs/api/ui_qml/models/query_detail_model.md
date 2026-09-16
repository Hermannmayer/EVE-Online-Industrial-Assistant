# ui_qml.models.query_detail_model

> 源文件 `ui_qml/models/query_detail_model.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品查询页 · 有结果态详情的数据整形（**纯函数，零 Qt/DB/缓存**）。

第 2 步（详情桥）的几何与文案算法全在这里，`ui_qml/bridge/query_detail_bridge.py`
只负责取数（DB / ESI / worker）并把结果喂进来。QML 侧只画，不做取最值/取整。
这条分工与 `ui_qml/bridge/price_chart_bridge.py` 的 `nice_range` / `plot_model`
是同一条既有约定（QML 不做几何计算）。

各函数对应结果区的一块面板：
  - `hub_bar_rows`     —— 5 个默认贸易中心的价格（每中心两行 + 一条横向柱形条 + 帝国圆点）
  - `material_rows`    —— 制造该物品所需的材料（买/卖双价）
  - `refine_rows`      —— 精炼该物品的产物
  - `refine_total_rows`—— 精炼的「产出 / 利润」总计行

## 函数

### `_num`

```python
def _num(value: Any) -> float
```

宽松转 float：None / 非数值一律当 0.0（价格缺列时不上抛）。

定义行：`55`

### `_money`

```python
def _money(value: float) -> str
```

千分位两位小数；无值（0/缺失）显式给 `—`，避免出现 `0.00` 的假价格。

定义行：`65`

### `_best_index`

```python
def _best_index(values: Sequence[float], *, highest: bool) -> int
```

在**正**值里取最高/最低的下标；并列取第一个，全无正值返回 -1。

定义行：`72`

### `hub_bar_rows`

```python
def hub_bar_rows(snapshots: Mapping[str, Mapping[str, Any]], hubs: Sequence[str]) -> list[dict]
```

5 个贸易中心的价格快照 → 柱形条行（**按 `hubs` 顺序**）。

定义行：`88`

### `material_rows`

```python
def material_rows(sell_materials: Sequence[Mapping[str, Any]], buy_materials: Sequence[Mapping[str, Any]] | None=None) -> list[dict]
```

制造材料（**买/卖双向各展开一次**）→ 材料行。

定义行：`149`

### `refine_rows`

```python
def refine_rows(result: Mapping[str, Any]) -> list[dict]
```

`RefineWorker.result_signal` 的载荷 → **每个产出材料一行**的扁平列表。

定义行：`182`

### `refine_total_rows`

```python
def refine_total_rows(result: Mapping[str, Any]) -> list[dict]
```

精炼总计 → `[&#123;"label", "valueText", "token"&#125;]`（两行：产出 / 利润）。

定义行：`226`

# services.market_chain_service

> 源文件 `services/market_chain_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

BOM 传导链 —— 从某个产物逐级下钻：用量、成本占比、30/90/180 天涨跌、「未跟涨度」。

展开**复用** `services/bom_expander.expand_bom`（不自己重写 BOM 递归）；本模块只补三样它
不管的东西：**原始用量**、**逐级成本占比**、**材料的价格涨幅**。

价格口径（**两种来源，每行都用 `source` 标出来**）：

- `source="history"`：`market.db.price_history` 的**成交均价**（与指数、异动榜同一口径）。
- `source="snapshot"`：`market.db.market_volume_snapshots` 的**挂单卖价**（该日快照的
  `sell_price`）。**口径差异**：挂单价不是成交价，一个人挂/撤就能推动（计划 §2.2 第 2 条），
  所以它只在「该材料本地没有成交历史」时兜底 —— 材料往往只有挂单价，没有 `price_history`。
  另外挂单价**没有成交量**，窗口均价用算术平均（成交均价按成交量加权），两者数值不可直接比较。
- 两者都没有 → `price=None`、`source=None`（不拿 0 冒充「免费」）。

涨幅窗口与异动榜同一套：近 W 个日历天均价 ÷ **前一个等长窗口**均价 − 1；某个窗口没有
记录 → `None`。

DAG（同一材料出现在多条支路）按 `typeId` **合并成一行**并用 `occurs` 记出现次数；展示行取
`(level, parent_type_id)` 最小的一次出现（最浅、最靠前），这样同一次数据下结果稳定。
`not_caught_up` 是**父项级**的残差 = 父项 30 天涨幅 − Σ(子项 cost_share × 子项 30 天涨幅)，
同一个父项下的所有子项行共享同一个值；正数 = 子项还没跟上父项。

## 函数

### `_table_exists`

```python
def _table_exists(conn, name: str) -> bool
```

market.db 里有没有这张表。

定义行：`46`

### `_chunks`

```python
def _chunks(ids: list[int]) -> Iterator[list[int]]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`55`

### `_fetch_series`

```python
def _fetch_series(conn, ids: list[int], region_id: int, lookback_start: str) -> dict[int, tuple[str, list[_Point]]]
```

`&#123;type_id: (source, [(date, price, weight)])&#125;` —— 成交均价优先，挂单价兜底。

定义行：`60`

### `_window_price`

```python
def _window_price(points: list[_Point], start: str, end: str) -> float | None
```

窗口均价：有权重就加权，权重全 0（挂单价）就算术平均，窗口内无记录给 None。

定义行：`94`

### `_change_pct`

```python
def _change_pct(points: list[_Point], window: int, today: date) -> float | None
```

近 `window` 天均价 vs 前一个等长窗口均价的涨幅（%）；缺任一窗口给 None。

定义行：`105`

### `get_transmission_chain`

```python
def get_transmission_chain(type_id: int, depth: int=2, region_id: int=JITA_RID, _db=None) -> list[dict]
```

把 `type_id` 的 BOM 逐级展开成传导链。

定义行：`118`

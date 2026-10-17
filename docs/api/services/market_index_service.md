# services.market_index_service

> 源文件 `services/market_index_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

大盘指数计算服务 —— 五个指数（MPI/PPPI/SPPI/CPI/PLEX）的计算与官方篮子映射。

篮子口径来源（官方）
--------------------
五个指数的名字对应 **CCP 官方 Monthly Economic Report（MER）** 的四条价格指数 + PLEX 锚。
MER 新闻页（https://www.eveonline.com/news/view/monthly-economic-report-september-2026）发布的
原始数据包里有 `data/index_baskets.csv` —— **官方逐 type 级成员清单**（列：
`type_id, type_name, category_id, category_name, group_id, group_name, primary_index, sub_index`；
四个指数合计 18,869 个 type），以及 `data/economy_indices_details.csv`（官方 2003-11 起的指数序列）。
本次实现采用的快照：**MER 2026-09 数据包**
（`https://monthly-economic-report.s3.eu-west-1.amazonaws.com/EVEOnline_MER_202609.zip`，
包 Last-Modified 2026-10-12，2026-10-17 下载核对）。官方从 2026-06 起的 MER 数据包包含这份成员
清单（2026-06 / 2026-09 有；2025-12 没有）；更早的官方口径只散见于 2011~2012 年的
「Price Indices」dev blog（四指数定义）与已下线的 Evelopedia「Market Indices」页。

官方清单是 **type 级**的；本地 SDE 只有 `reference.db.item.market_group_id`。两者高度对齐：
1,529 个市场分组一对一映射到某个指数（压缩成 :data:`MER_MARKET_GROUP_RANGES` 连续区间表，
导入时展开为 :data:`MER_MARKET_GROUP_INDEX`）；剩余的对齐差异全部显式列成 type 例外
（:data:`MER_TYPE_OVERRIDES` 补官方成员、:data:`MER_TYPE_EXCLUDED` 去掉规则误收的本地 type）。
用这份映射在真实 SDE 上复算：官方 18,411 个「本地 SDE 里也有的」成员 **0 个判错、0 个漏判**，
规则会多收的 174 个本地 type 已全部显式排除。

五条线
------
==================  ==========================================================================
``mpi``             官方 Mineral Price Index：固定 8 种矿物（:data:`MPI_TYPES`，与 MER 清单逐 type 核对一致）
``pppi``            官方 Primary Producer Price Index 篮子（矿石/月矿/行星产物/发明用品等 19 个 sub_index）
``sppi``            官方 Secondary Producer Price Index 篮子（T2 组件/打捞物/蓝图/增效体等 18 个 sub_index）
``cpi``             官方 Consumer Price Index 篮子（14,483 个 type、38 个 sub_index —— 不再是成交额 top-N 代理）
``plex``            固定 44992（ISK 锚），序列取自官方 Global PLEX Market（region 19000001）
==================  ==========================================================================

算法（不随篮子口径改动）
------------------------
1. **准入**：近 :data:`REBALANCE_DAYS` 个日历天成交额 > :data:`MIN_TURNOVER_ISK`（即 >0）
   **且**覆盖天数 ≥ :data:`MIN_COVERED_DAYS`。不满足的成员当日不参与（权重 0）。
2. **单成分日收益**：`当日成交均价 ÷ 该成员此前最近一次成交均价 − 1`；参考价间隔超过
   :data:`RETURN_GAP_DAYS` 天视为「已不是日收益」→ 当日不参与。再按 :data:`RETURN_CLAMP`
   截断 ±20%（超出按 ±20% 计）。
3. **成分内聚合**：参与成员的**加权中位数**（不是均值 —— 抗单笔异常）。权重见第 4 条。
4. **权重**：该成员**当日**往前 :data:`REBALANCE_DAYS` 个日历天的成交额（`volume × average`），
   经 :data:`WEIGHT_CAP`（25%）单成分上限后按合计归一化 —— 30 天滚动再平衡。
5. **逐日累乘**：基期 = 首个可算日 = :data:`BASE_VALUE`（100），之后
   `I_t = I_&#123;t-1&#125; × (1 + 当日加权中位数收益)`。成分换入换出只改变「当日参与集合与权重」，
   **不重设基期**，所以成分变更日天然不跳变（链式拼接）。

口径备注
--------
- **成员集合 = 官方 MER 篮子**（:func:`official_index_members`）：MPI 固定 8 矿；
  PPPI/SPPI/CPI 由官方 type 清单经 `market_group_id` 映射得到；PLEX 固定。
  异动榜（`services.market_movers_service`）复用同一份集合，两页不会口径分叉。
- **固定指数不因准入阈值掉成员**：MPI/PLEX 的成员表恒为固定集合（不满足准入的权重记 0）；
  PPPI/SPPI/CPI 的成员表只列当日有正权重的成员。
- 价格口径：本模块只用 **成交均价**（`market.db.price_history.average`），**不用挂单价** ——
  一个人挂/撤单就能推动挂单价。
- **`days` 字段** = 该指数已算出的点数（`points` 长度），`base_date` = 首个点日期。
- **数据不足一律 `None`**（不用 0 冒充）：少于 2 个点 → `value`/涨跌全 `None`；
  涨跌窗口没有覆盖到对应日历天 → 该窗口 `None`。

物化缓存
--------
:func:`refresh_index_daily` 把五个指数的逐日点位写进 `market.db.market_index_daily`
（market.db 是可重建缓存，故 DDL 直接建表、不走 `schema_migrations`，同 `price_history` 先例）。
表的 `type_id` 列存的是指数的**保留负数 id**（:data:`INDEX_TYPE_IDS`，真实 EVE type_id 恒为正），
`price` = 指数点位，`volume` = 当日成员成交额；`get_index_cards` / `get_index_series`
优先读这张表，表里没有该指数时退化为实时计算（不写库）。

大盘页要「卡片 + 序列」两样：用 :func:`get_dashboard` 一次算完（成分集 / 观测装载 / 逐日累乘
只跑一遍），不要分别调那两个函数 —— 那会把同一套计算整跑两遍。

## 函数

### `clamp_return`

```python
def clamp_return(value: float | None) -> float | None
```

单成分日收益去极值：超过 :data:`RETURN_CLAMP`（±20%）按 ±20% 计。

定义行：`538`

### `weighted_median`

```python
def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None
```

成交量加权中位数（权重非正的样本不参与）。

定义行：`549`

### `cap_weights`

```python
def cap_weights(raw: Mapping[K, float]) -> dict[K, tuple[float, bool]]
```

成交额权重：单成分上限 :data:`WEIGHT_CAP`（25%）后按合计归一化。

定义行：`576`

### `classify_official_basket`

```python
def classify_official_basket(type_id: int, market_group_id: int | None) -> str | None
```

官方 MER 篮子分类（纯函数，不查库）：`type_id` + SDE `market_group_id` → 指数 key 或 `None`。

定义行：`598`

### `_build_index`

```python
def _build_index(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int]) -> _IndexPoints
```

把「成员 → 逐日 `(date, average, volume)`」链式累乘成指数。

定义行：`621`

### `_price_change`

```python
def _price_change(rows: Sequence[tuple[str, float, int]], days: int) -> float | None
```

成员自身近 `days` 个日历天的成交均价涨幅（%）—— 数据不足 → `None`。

定义行：`716`

### `_last_price`

```python
def _last_price(rows: Sequence[tuple[str, float, int]], anchor: date | None) -> float | None
```

成员在 `anchor` 日（含）之前**最近一次**成交均价；没有可用观测 → `None`（不用 0 冒充）。

定义行：`732`

### `_weights_at`

```python
def _weights_at(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int], anchor: date) -> dict[int, tuple[float, bool]]
```

以 `anchor` 为最后一天，算成员表用的 30 天成交额权重（准入 + 25% 上限 + 归一化）。

定义行：`745`

### `_table_has_column`

```python
def _table_has_column(conn, table: str, column: str) -> bool
```

`table` 是否存在且含 `column`（表不存在 → False）。

定义行：`773`

### `_table_exists`

```python
def _table_exists(conn, name: str) -> bool
```

表是否存在。`name` 可以带库前缀（如 `ref.item`）—— 带前缀时查那张库的 `sqlite_master`。

定义行：`784`

### `_last_history_day`

```python
def _last_history_day(conn_mgr, region_id: int) -> date | None
```

最新**已补齐**的**成交**数据日（只看 `price_history`，覆盖数达标的那天）。

定义行：`805`

### `_last_day`

```python
def _last_day(conn_mgr, region_id: int) -> date | None
```

指数计算用的最新数据日：**成交**的已补齐日 与 **全服价**的最新日取较晚者。

定义行：`829`

### `_read_region_history`

```python
def _read_region_history(conn, out: dict[int, list[tuple[str, float, int]]], region_id: int, ids: Sequence[int], start: date, end: date) -> None
```

把 `price_history` 里 `region_id` 的 `ids` 行追加进 `out`（按 `_SQL_CHUNK` 分批）。

定义行：`856`

### `_load_observations`

```python
def _load_observations(conn_mgr, region_id: int, type_ids: Iterable[int], start: date, end: date) -> dict[int, list[tuple[str, float, int]]]
```

读 `price_history` → `&#123;type_id: [(date, average, volume), ...]&#125;`（按日期升序）。

定义行：`878`

### `_load_global_observations`

```python
def _load_global_observations(conn, type_ids: Iterable[int], start: date, end: date) -> dict[int, list[tuple[str, float, int]]]
```

读 `global_price_daily`（全服统一价）→ 与 `price_history` 同形的序列。

定义行：`919`

### `_load_names`

```python
def _load_names(conn_mgr, type_ids: Iterable[int]) -> dict[int, str]
```

`&#123;type_id: 中文名（退回英文名，再退回 #id）&#125;`；reference.db 没表 → `&#123;&#125;`。

定义行：`948`

### `official_index_members`

```python
def official_index_members(conn_mgr=None) -> dict[str, set[int]]
```

官方 MER 四指数篮子（`&#123;mpi, pppi, sppi, cpi&#125;` → type_id 集合）—— 指数与异动榜的唯一口径。

定义行：`968`

### `_official_classes`

```python
def _official_classes(conn_mgr) -> tuple[set[int], set[int]]
```

官方 MER 篮子的 PPPI / SPPI 成员集合（= :func:`official_index_members` 的对应两项）。

定义行：`994`

### `production_input_classes`

```python
def production_input_classes(db=None) -> tuple[set[int], set[int]]
```

**生产投入品**的 PPPI / SPPI 划分 —— 指数篮子与异动榜共用的唯一口径。

定义行：`1000`

### `production_inputs`

```python
def production_inputs(db=None) -> set[int]
```

生产投入品 = PPPI ∪ SPPI（见 :func:`production_input_classes`）。

定义行：`1013`

### `_member_sets`

```python
def _member_sets(conn_mgr, keys: Sequence[str]) -> tuple[dict[str, set[int]], set[int]]
```

`(&#123;key: 候选成分&#125;)`, **生产投入品**集合（= PPPI ∪ SPPI）。

定义行：`1019`

### `_build_for`

```python
def _build_for(conn_mgr, region_id: int, keys: Sequence[str], anchor: date | None=None, sets: Mapping[str, set[int]] | None=None) -> dict[str, _IndexPoints]
```

实时计算若干指数的点位（不写库）。

定义行：`1038`

### `_read_materialized`

```python
def _read_materialized(conn_mgr, region_id: int, key: str) -> list[dict]
```

读物化表里某指数的点位；没有表/没有行 → `[]`。

定义行：`1065`

### `_resolve_points`

```python
def _resolve_points(conn_mgr, region_id: int, keys: Sequence[str], anchor: date | None=None, sets: Mapping[str, set[int]] | None=None) -> dict[str, list[dict]]
```

点位：优先读物化缓存，缺失的指数实时计算（**不**写库）。

定义行：`1080`

### `refresh_index_daily`

```python
def refresh_index_daily(region_id: int=JITA_RID) -> int
```

重建 `market.db.market_index_daily`（五个指数逐日点位），返回写入行数。

定义行：`1109`

### `_pct`

```python
def _pct(value: float | None, base: float | None) -> float | None
```

百分比涨幅；基数缺失/为 0 → `None`（不用 0 冒充）。

定义行：`1133`

### `_value_before`

```python
def _value_before(points: Sequence[dict], days: int) -> float | None
```

最后一个点往前 `days` 个日历天（含）之前最近一个点的点位；不够长 → `None`。

定义行：`1140`

### `_cards_from_points`

```python
def _cards_from_points(points_map: Mapping[str, Sequence[dict]]) -> list[dict]
```

点位表 → 五张指数卡（`get_index_cards` / `get_dashboard` 共用这一份口径）。

定义行：`1154`

### `_series_from_points`

```python
def _series_from_points(conn_mgr, region_id: int, keys: Sequence[str], points_map: Mapping[str, Sequence[dict]], member_sets: Mapping[str, set[int]]) -> list[dict]
```

点位表 + 成分集 → 折线 + 篮子成员表（`get_index_series` / `get_dashboard` 共用）。

定义行：`1181`

### `get_index_cards`

```python
def get_index_cards(region_id: int=JITA_RID, _db=None) -> list[dict]
```

五张指数卡：`[&#123;key,label,value,chg1,chg7,chg30,chg90,chg180,days,base_date&#125;]`。

定义行：`1230`

### `get_index_series`

```python
def get_index_series(keys: Sequence[str] | None=None, region_id: int=JITA_RID, _db=None) -> list[dict]
```

指数折线 + 篮子成员表：`[&#123;key,label,points:[&#123;date,value&#125;],members:[...]&#125;]`。

定义行：`1239`

### `get_dashboard`

```python
def get_dashboard(region_id: int=JITA_RID, _db=None) -> dict
```

卡片 + 序列**一次算完** → `&#123;"cards": [...], "series": [...]&#125;`。

定义行：`1256`

### `_member_row`

```python
def _member_row(tid: int, weight: float, capped: bool, names: Mapping[int, str], obs: Mapping[int, Sequence[tuple[str, float, int]]], key: str, anchor: date | None) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`1274`

### `get_breadth`

```python
def get_breadth(region_id: int=JITA_RID, _db=None) -> dict
```

最新交易日的市场广度：`&#123;date,advancers,decliners,unchanged,turnover&#125;`。

定义行：`1295`

## 类

### `class _IndexPoints`（继承 `NamedTuple`）

一条指数的计算结果：逐日点位 + 最后一个指数日的成分权重。

定义行：`526`

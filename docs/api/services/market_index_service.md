# services.market_index_service

> 源文件 `services/market_index_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

大盘指数计算服务 —— CCP 四指数（MPI/PPPI/SPPI/CPI 代理）+ PLEX 锚。

口径来源：`docs/dev/market-monitor-plan.md` §2（CCP 2012 价格指数 dev blog + 2019 MER + 薄市场指数方法论）。
本模块只用 **成交均价**（`market.db.price_history.average`），**不用挂单价** —— 一个人挂/撤单就能推动挂单价。

五条线
------
==================  ==========================================================================
``mpi``             固定 8 种矿物（:data:`MPI_TYPES`），与 CCP MPI 一致
``pppi``            初级投入品：被 manufacturing/reaction 当材料，**且它供入的产物本身又被当材料**
                    （用途层级 ≥2，近似 CCP 的 ore/moon/PI/发明用品）
``sppi``            次级投入品：被当材料，但供入的产物**不再被当材料**（直接供给消费品）
``cpi``             消费品（代理）：有成交、不被任何蓝图当材料，按近 30 天成交额取 top-:data:`CPI_TOP_N`
``plex``            固定 44992（ISK 锚）
==================  ==========================================================================

算法（逐条对应计划 §2.2）
--------------------------
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
   **不重设基期**，所以成分变更日天然不跳变（这就是链式拼接，见计划 §2.2.6）。

口径备注（实现时做的取舍，逐条写清）
------------------------------------
- **PPPI 判定方向**：计划 §3 的伪代码 `product_of(mat) ∈ materials` 读作「mat 供入的蓝图产物
  是否还被当材料」，即 `blueprint_materials × blueprint_products` 按 (blueprint_type_id, activity)
  自连接后看 `product_type_id` 是否在材料集合里。这与计划 §2.1 的「它的产物又被当材料（层级 ≥2）」
  一致；不是「mat 自己是否由蓝图产出」（矿物由精炼产出，那样会把三钛合金错误地踢出初级品）。
- **固定指数不因准入阈值掉成员**：MPI/PLEX 的成员表恒为固定集合（不满足准入的权重记 0），
  以守住「MPI = 8 矿固定」；PPPI/SPPI/CPI 的成员表只列当日有正权重的成员。
- **CPI 篮子**：按「最新 30 天」的成交额取 top-:data:`CPI_TOP_N`（当前篮子）；
  篮子内每个历史日的权重仍是各日自己的 30 天滚动权重。
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

## 函数

### `clamp_return`

```python
def clamp_return(value: float | None) -> float | None
```

单成分日收益去极值：超过 :data:`RETURN_CLAMP`（±20%）按 ±20% 计。

定义行：`161`

### `weighted_median`

```python
def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None
```

成交量加权中位数（权重非正的样本不参与）。

定义行：`172`

### `cap_weights`

```python
def cap_weights(raw: Mapping[K, float]) -> dict[K, tuple[float, bool]]
```

成交额权重：单成分上限 :data:`WEIGHT_CAP`（25%）后按合计归一化。

定义行：`199`

### `_build_index`

```python
def _build_index(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int]) -> _IndexPoints
```

把「成员 → 逐日 `(date, average, volume)`」链式累乘成指数。

定义行：`221`

### `_price_change`

```python
def _price_change(rows: Sequence[tuple[str, float, int]], days: int) -> float | None
```

成员自身近 `days` 个日历天的成交均价涨幅（%）—— 数据不足 → `None`。

定义行：`315`

### `_last_price`

```python
def _last_price(rows: Sequence[tuple[str, float, int]], anchor: date | None) -> float | None
```

成员在 `anchor` 日（含）之前**最近一次**成交均价；没有可用观测 → `None`（不用 0 冒充）。

定义行：`331`

### `_weights_at`

```python
def _weights_at(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int], anchor: date) -> dict[int, tuple[float, bool]]
```

以 `anchor` 为最后一天，算成员表用的 30 天成交额权重（准入 + 25% 上限 + 归一化）。

定义行：`344`

### `_table_exists`

```python
def _table_exists(conn, name: str) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`372`

### `_last_history_day`

```python
def _last_history_day(conn_mgr, region_id: int) -> date | None
```

最新**已补齐**的**成交**数据日（只看 `price_history`，覆盖数达标的那天）。

定义行：`382`

### `_last_day`

```python
def _last_day(conn_mgr, region_id: int) -> date | None
```

指数计算用的最新数据日：**成交**的已补齐日 与 **全服价**的最新日取较晚者。

定义行：`406`

### `_load_observations`

```python
def _load_observations(conn_mgr, region_id: int, type_ids: Iterable[int], start: date, end: date) -> dict[int, list[tuple[str, float, int]]]
```

读 `price_history` → `&#123;type_id: [(date, average, volume), ...]&#125;`（按日期升序）。

定义行：`424`

### `_load_global_observations`

```python
def _load_global_observations(conn, type_ids: Iterable[int], start: date, end: date) -> dict[int, list[tuple[str, float, int]]]
```

读 `global_price_daily`（全服统一价）→ 与 `price_history` 同形的序列。

定义行：`465`

### `_load_names`

```python
def _load_names(conn_mgr, type_ids: Iterable[int]) -> dict[int, str]
```

`&#123;type_id: 中文名（退回英文名，再退回 #id）&#125;`；reference.db 没表 → `&#123;&#125;`。

定义行：`492`

### `_blueprint_classes`

```python
def _blueprint_classes(conn_mgr) -> tuple[set[int], set[int]]
```

蓝图层级判定 → `(PPPI 候选, SPPI 候选)`（都取自「被 manufacturing/reaction 当材料」的 type）。

定义行：`512`

### `_cpi_candidates`

```python
def _cpi_candidates(conn_mgr, region_id: int, materials: set[int], anchor: date | None) -> list[int]
```

CPI 代理篮子：近 30 天成交额 top-:data:`CPI_TOP_N`，排除「被当材料」的 type。

定义行：`547`

### `_member_sets`

```python
def _member_sets(conn_mgr, region_id: int, keys: Sequence[str], anchor: date | None) -> tuple[dict[str, set[int]], set[int]]
```

`(&#123;key: 候选成分&#125;)`, `materials`。候选成分**未**做准入过滤（准入在逐日权重里做）。

定义行：`575`

### `_build_for`

```python
def _build_for(conn_mgr, region_id: int, keys: Sequence[str]) -> dict[str, _IndexPoints]
```

实时计算若干指数的点位（不写库）。

定义行：`599`

### `_read_materialized`

```python
def _read_materialized(conn_mgr, region_id: int, key: str) -> list[dict]
```

读物化表里某指数的点位；没有表/没有行 → `[]`。

定义行：`613`

### `_resolve_points`

```python
def _resolve_points(conn_mgr, region_id: int, keys: Sequence[str]) -> dict[str, list[dict]]
```

点位：优先读物化缓存，缺失的指数实时计算（**不**写库）。

定义行：`628`

### `refresh_index_daily`

```python
def refresh_index_daily(region_id: int=JITA_RID) -> int
```

重建 `market.db.market_index_daily`（五个指数逐日点位），返回写入行数。

定义行：`648`

### `_pct`

```python
def _pct(value: float | None, base: float | None) -> float | None
```

百分比涨幅；基数缺失/为 0 → `None`（不用 0 冒充）。

定义行：`672`

### `_value_before`

```python
def _value_before(points: Sequence[dict], days: int) -> float | None
```

最后一个点往前 `days` 个日历天（含）之前最近一个点的点位；不够长 → `None`。

定义行：`679`

### `get_index_cards`

```python
def get_index_cards(region_id: int=JITA_RID, _db=None) -> list[dict]
```

五张指数卡：`[&#123;key,label,value,chg1,chg7,chg30,chg90,chg180,days,base_date&#125;]`。

定义行：`693`

### `get_index_series`

```python
def get_index_series(keys: Sequence[str] | None=None, region_id: int=JITA_RID, _db=None) -> list[dict]
```

指数折线 + 篮子成员表：`[&#123;key,label,points:[&#123;date,value&#125;],members:[...]&#125;]`。

定义行：`726`

### `_member_row`

```python
def _member_row(tid: int, weight: float, capped: bool, names: Mapping[int, str], obs: Mapping[int, Sequence[tuple[str, float, int]]], key: str, anchor: date | None) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`778`

### `get_breadth`

```python
def get_breadth(region_id: int=JITA_RID, _db=None) -> dict
```

最新交易日的市场广度：`&#123;date,advancers,decliners,unchanged,turnover&#125;`。

定义行：`799`

## 类

### `class _IndexPoints`（继承 `NamedTuple`）

一条指数的计算结果：逐日点位 + 最后一个指数日的成分权重。

定义行：`149`

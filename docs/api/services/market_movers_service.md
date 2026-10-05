# services.market_movers_service

> 源文件 `services/market_movers_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

异动榜 —— 近 N 个日历天的成交均价涨幅 / 放量倍数 / 指数准入（只读）。

**只用 `market.db.price_history` 的成交均价**，不碰挂单价（计划 §2.2 第 2 条：
挂单价一个人挂/撤就能推动，不进指数、也不进异动榜）。

口径（与 `services/price_history.get_history_summary` 同一条规矩）：

- 窗口一律按**日历天**取，`近 n 天 = [今天 - n + 1, 今天]`；窗口内**没有记录的日子
  按 0 成交**计入分母，所以「日均」= 窗口内成交量之和 ÷ n，**不是** ÷ 有记录的天数
  （ESI 历史只返回有成交的日子，日期是跳的）。
- 涨跌 `chg` = 近 n 天成交均价 ÷ **前一个等长窗口**（再往前 n 天）的成交均价 − 1，单位 %。
  两个窗口各自取**成交量加权均价** `Σ(average×volume) / Σvolume`；窗口内成交量全为 0
  （脏数据）时退回该窗口的算术均价。
  前窗口没有记录 → 算不出涨幅 → **该物品不进榜**（不拿 0 冒充「没涨」）。
- 放量倍数 `volume_ratio` = 近 n 天日均 ÷ 近 30 天日均；近 30 天成交量合计为 0 → `None`。
- 准入 `qualified`（计划 §2.2 第 1 条）：近 30 天成交额 > 0 **且**有记录天数 ≥ 5。
- `index_keys`：该物品命中的指数（`INDEX_KEYS` 顺序）。分类口径见 `_index_membership`；
  它是「成分身份」，与 `qualified`（准入阈值）是两件事 —— 异动榜分两区靠 `qualified`
  字段表达，不属于任何指数的物品 `index_keys` 为 `[]`。

## 函数

### `_window_price`

```python
def _window_price(turnover: float, volume: float, avg_sum: float, covered: int) -> float | None
```

窗口成交均价：有成交量就按成交量加权，成交量全 0 时退回算术均价，无记录给 None。

定义行：`53`

### `_index_membership`

```python
def _index_membership(conn, turnover_30d: dict[int, float]) -> dict[int, list[str]]
```

`&#123;type_id: 命中的指数 key&#125;`（顺序按 `INDEX_KEYS`）。

定义行：`62`

### `get_movers`

```python
def get_movers(days: int=3, limit: int=50, region_id: int=JITA_RID, qualified_only: bool=False, _db=None) -> list[dict]
```

近 `days` 个日历天的异动榜，按 |涨幅| 降序取前 `limit` 条。

定义行：`107`

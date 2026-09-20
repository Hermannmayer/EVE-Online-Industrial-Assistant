# services.wallet_import

> 源文件 `services/wallet_import.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

钱包交易记录的剪贴板解析 — 纯函数，无 DB / Qt 依赖。

游戏里「钱包 → 交易记录」Ctrl+A/C 复制出来的是 Tab 分隔文本，两种列型：

- **市场流水**（钱包页）：日期 / 类型 / 金额 / 余额 / 说明。第 4 列是**逐笔累计余额**，
  所以最新一笔的余额就是当前钱包余额 —— 挂单列表面板靠它免手打。
- **交易明细**（交易页）：日期 / 数量 / 物品名* / 单价 / 总额 / 卖家 / 地点 / 买家 / 账户。
  **金额为负 = 你付出 ISK（买入），为正 = 你收到 ISK（卖出）**（用户 2026-09-20 确认）。
  仓库/采购的入库只吃买入行，卖出行统计后跳过。

## 函数

### `_money`

```python
def _money(text: str) -> float | None
```

`-30,692 星币` → -30692.0；非法给 None（负数合法：流水里支出就是负的）。

定义行：`23`

### `_count`

```python
def _count(text: str) -> int | None
```

数量列 → int（去千分位）；非正整数给 None。

定义行：`33`

### `parse_wallet_journal`

```python
def parse_wallet_journal(raw: str) -> list[dict]
```

市场流水 → ``[&#123;time, kind, amount, balance, note&#125;]``（认不出的行丢弃）。

定义行：`43`

### `latest_balance`

```python
def latest_balance(rows: list[dict]) -> tuple[float, str] | None
```

取最新一笔流水后的余额 → ``(余额, 时间)``；无有效行给 None。

定义行：`66`

### `parse_purchase_records`

```python
def parse_purchase_records(raw: str) -> tuple[list[dict], dict]
```

交易明细 → 买入行 + 统计。

定义行：`82`

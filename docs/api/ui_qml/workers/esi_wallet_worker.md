# ui_qml.workers.esi_wallet_worker

> 源文件 `ui_qml/workers/esi_wallet_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

ESI 钱包余额 + 未结挂单：一次拉**全部已绑定角色**。

继承 `esi_skill_worker.EsiSkillImportWorker`，**只重写 `_import()`** —— 令牌获取 /
静默刷新 / 过期与撤销处理全部复用基类。为什么不把那段抽成模块级函数：基类的
`_browser_authorize` / `_refresh` 被 `tests/test_qml_char_settings.py` 按**类属性**
打桩，抽出去会让那些桩失效（测试会真去开浏览器）。

**为什么这条路径不做「订单变动」推断**：ESI 给的钱包余额是**绝对值**、挂单是
「该角色当前未结」的**完整集**（官方 OpenAPI spec 里该接口没有 `page` 参数，
一次调用即全量）。所以落库是**快照替换**：钱包绝对覆盖、订单按
`(char_id, is_corp)` 组整体替换。接 `adjust_wallet_balance` 那种差额逻辑会把钱算两遍。

载荷（`result_signal`）：

- `orders`：字段与 `query_dashboard_bridge._normalize_order` 同口径，桥直接收。
- `wallet_total`：**全部角色（含军团钱包，若开启）都成功才有值**，否则 `None` ——
  合计少算了某一块会把余额写小，比不写更糟，所以由桥据此决定要不要覆盖。
- `corp_total` / `include_corp`：军团钱包合计与开关状态（未开启或失败时为 `None`）。
  桥据此把「角色钱包 + 军团钱包」的构成写进状态栏 —— 看不出钱在哪正是要解决的问题。
- `groups`：本次成功同步到的归属组 `[[char_id, is_corp], ...]`，**含当前无挂单的空组**
  （桥按组整体替换，少了空组就删不掉已成交的幽灵行）。
- `errors`：单角色 / 军团钱包失败的说明。有它也不影响其余角色落库。
- `chars`：成功同步的角色数。

**军团钱包是可选口径**（开关在 `settings.json` 的 `esi_include_corp_wallet`）：
它是共享账户、不是个人净资产，读它还要角色有军团会计类角色，所以默认不拉。

## 函数

### `_map_order`

```python
def _map_order(raw: dict, char_id: int) -> dict
```

ESI 订单 → `open_orders` 记录口径。

定义行：`48`

## 类

### `class EsiWalletOrdersWorker`（继承 `EsiSkillImportWorker`）

一次性线程：逐角色拉钱包余额与未结挂单。

构造只传 `parent`（不传 `character_name`）—— 角色列表由 `esi_tokens` 决定。

定义行：`77`

#### 方法

##### `_import`

```python
async def _import(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`83`
##### `_character_corp`

```python
async def _character_corp(self, client, access: str, char_id: int) -> int
```

角色所属军团 id。`/characters/&#123;id&#125;/` 是**公开**接口，不需要任何 scope。

定义行：`167`
##### `_pull_corp_wallet`

```python
async def _pull_corp_wallet(self, client, access: str, corp_id: int) -> float
```

军团钱包合计（各分部余额相加）。

定义行：`172`
##### `_pull_one`

```python
async def _pull_one(self, client, access: str, char_id: int) -> tuple[float, list]
```

一个角色的 (钱包余额, 未结挂单)。

定义行：`188`

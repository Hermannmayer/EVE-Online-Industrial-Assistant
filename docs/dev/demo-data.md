# 演示数据集（完全合成，零账号数据）

公开 README 的配图用的**演示数据**是怎么造的、每个页面分别被哪些行点亮、以及「这里全部是虚构数据」的声明。

- 生成脚本：`scripts/build_demo_data.py`
- 演示根：`%TEMP%/eve-demo-root/`（可用 `--root` 改）
- 自检：脚本跑完自动逐项打印 `PASS/FAIL`（当前 **67/67**）

> **声明**：演示根里的一切**都是合成的**。人物名（`演示角色` / `Demo Trader`）、机库名
> （`演示总仓` / `演示生产线` / `演示反应堆` / `演示贸易仓`）、军团与合同发行方
> （`演示物流公司` / `Demo Freight Co` / `演示矿业集团`）、ESI 令牌（`DEMO-PLACEHOLDER-TOKEN-…`）
> 全是编的；价格用**固定随机种子 + BOM 推导**生成，只保证量级合理，与真实行情无关。
> 数据里**不含**任何真实 EVE 账号的机库、库存、计划、挂单、钱包或蓝图绑定。

---

## 1. 生成与用法

```bash
# 建演示根 + 逐项自检
.venv/Scripts/python.exe scripts/build_demo_data.py

# 只跑自检（不重建）
.venv/Scripts/python.exe scripts/build_demo_data.py --check-only

# 建完用演示根**交互式**起一次外壳（会打印装载了几个页面）
.venv/Scripts/python.exe scripts/build_demo_data.py --shell

# 建完逐页截图 → <演示根>/shots/（README 配图直接用这些 PNG）
.venv/Scripts/python.exe scripts/build_demo_data.py --shots
.venv/Scripts/python.exe scripts/build_demo_data.py --shots --shots-real --size 1600x1000   # 真窗口（有字体）

# 换演示根 / 固定锚定日期（复现另一天的数据）
.venv/Scripts/python.exe scripts/build_demo_data.py --root D:\eve-demo --anchor-date 2026-10-11
```

| 选项 | 作用 |
|---|---|
| `--root` | 演示根目录（默认 `%TEMP%/eve-demo-root`）。**必须与脚本预解析结果一致** —— 应用根目录要在 `import core.paths` 之前定下来 |
| `--source-root` | 公共 SDE 派生库与 `sqlite_master` DDL 的来源（默认本仓库） |
| `--anchor-date` | 数据锚定日期 `YYYY-MM-DD`（默认今天）。所有「近 N 天」窗口都相对它算 |
| `--check-only` | 只跑自检，不重建 |
| `--shell` | 交互式起外壳（`ShellWindow`），打印 `已装载 N/7 个页面` |
| `--shots` / `--shots-real` / `--shots-dir` / `--size` | 逐页截图；默认离屏、输出到 `<演示根>/shots/`；`--shots-real` 用真窗口（离屏平台下字体数为 0，文字会渲染成方框） |

脚本会把 `EVE_ASSISTANT_APP_ROOT` 指到演示根，自检用的就是**应用真实的**
`services/` / `domain/` 代码 —— 不存在「脚本自己一套口径、界面另一套」。

### 幂等

固定种子 `SEED = 20261011`，价格/成交量/日期偏移全部由 `(种子, 锚定日, 序号)` 决定。
连续两次构建的产物**逐文件 SHA-256 完全一致**（实测；`--shots` 会把
`data/market_monitor_cache.json` 与 `watchlist_items.last_*` 写脏，要一份干净的根就重跑一次构建）。

---

## 2. 数据来源红线

用户要求原话：「软件的数据最好由你自己生成。不要用我开发环境里的数据，那是我账号的数据，我怕泄露。」

### 脚本允许做的三件事

| # | 做什么 | 说明 |
|---|---|---|
| ① | **整文件复制** `database/reference.db`、`database/blueprint.db` | 这两份是 CCP 公开 SDE 的导入结果（物品/蓝图/星系/空间站/回收配方），不含任何用户数据 |
| ② | 从 `user.db` / `market.db` / `items.db` 的 **`sqlite_master` 读建表 DDL** | 只跑 `SELECT ... FROM sqlite_master`，**不读任何数据行** |
| ③ | 复制 `data/caches/icons/<type_id>.png` 里**被演示数据用到的 227 个** | 公共图标缓存；**不整目录复制**（全集 18,616 个） |

`data/terminology.json` 是仓库自带的公共术语文件（`git ls-files` 可查），一并复制进演示根。

### 脚本明确不做的

- ❌ 不复制用户真实 `database/`、`data/` 目录（`scripts/shell_snapshot.py --real` 的
  `_isolate_app_root()` 会整目录复制它们，**那条路不能用于公开截图**，本脚本不调用它）
- ❌ 不读 `user.db` 的任何数据行（机库/库存/计划/挂单/钱包/蓝图绑定/ESI 令牌）
- ❌ 不读 `data/char_config.json`、`data/search_history.json`、`data/score_settings.json`、
  `data/trade_cart.json` 等本机用户文件 —— 它们的键结构全部从**代码**推出来
  （`services/char_config_validator.DEFAULT_CHAR_CONFIG`、`core/search_history.py`、
  `ui_qml/bridge/all_items_bridge.py` 的 `_mfg`/`_trade`、`ui_qml/views/trade_cart_window.py`）
- ❌ 不联网（演示根存在的意义就是离线可看）

### 代码层面的闸门

```python
def _schema_only(conn, sql, params=()):
    """只允许 SELECT ... FROM sqlite_master，其余一律拒绝执行。"""
```

所有对**来源库**的查询都必须过这个函数（失败即 `RuntimeError`），来源库以
`file:...?mode=ro` 只读打开。脚本结束时打印：

```
[红线] 对真实 user.db 执行的数据行查询：0 次（只查过 sqlite_master 拿 DDL）
```

自检里另有两项专门盯这条红线：「未对 user.db 执行任何数据行查询」与
「演示 user.db 是新建文件（不是真实库的拷贝，实测 106,496 字节）」。

---

## 3. 演示根结构

```
%eve-demo-root%/
├── .eve-demo-root                     # 标记文件：说明本目录是合成演示数据
├── database/
│   ├── reference.db   (22.2 MB)       # 整文件复制公共 SDE 派生库
│   ├── blueprint.db   ( 3.5 MB)       # 同上
│   ├── market.db      ( 9.0 MB)       # 合成行情 + 指数 + 合同
│   ├── user.db        ( 0.1 MB)       # 合成用户数据（机库/库存/计划/挂单/关注/快照）
│   └── items.db       ( 0.05 MB)      # 旧兼容单库：**只建表、零数据行**
├── data/
│   ├── settings.json                  # auto_update_enabled = false（离线关键开关）
│   ├── char_config.json               # 虚构角色 + 技能（产线容量/精炼产率靠它）
│   ├── score_settings.json            # 评分页区域/人物（虚构）
│   ├── market_monitor_settings.json   # 大盘页：引导已读、折线粒度
│   ├── mfg_browser_settings.json
│   ├── search_history.json            # 虚构搜索词（演示物品名）
│   ├── trade_cart.json                # A→B 价差候选
│   ├── window_geometry.json / update_progress.json
│   ├── terminology.json               # 仓库自带公共术语文件
│   └── caches/icons/*.png             # 227 个演示物品图标
└── shots/                             # --shots 的产物（12 张）
```

> 构建产物里**没有** `market_monitor_cache.json` —— 那是大盘页首屏缓存，只有
> `--shots` / `--shell` 跑过一次之后才会出现（见第 9 节第 3 条）。

`items.db` 只是与真实安装同形。真正让 `Main._migrate_split_db()` 不碰演示库的是
`user.db._split_migration_complete` 里那条 `id = 1` 的完成标记。

---

## 4. 各库表与行数（实测）

| 库 | 表 | 行数 | 来源 |
|---|---|---|---|
| reference.db | `item` | 50,219 | 复制（公共 SDE） |
| | `market_tree` / `reprocessing_materials` / `station` / `solar_system` / `stargate` | 2,092 / 46,389 / 5,154 / 8,437 / 13,776 | 复制 |
| | `industry_system_costs` / `structure_rigs` / `item_dogma` / `dogma_attribute` / `meta_group` | 32,910 / 111 / 456 / 2,769 / 13 | 复制 |
| blueprint.db | `blueprint_activities` | 19,023 | 复制 |
| | `blueprint_materials` / `blueprint_products` / `blueprint_skills` | 36,193 / 6,266 / 22,252 | 复制 |
| market.db | `market_prices` | 1,165 | 合成（233 个物品 × 5 个贸易中心） |
| | `price_history` | 46,600 | 合成（Jita，200 天逐日成交） |
| | `market_volume_snapshots` | 69,900 | 合成（5 中心 × 60 天挂单量） |
| | `global_price_daily` | 200 | 合成（PLEX 全服统一价） |
| | `market_index_daily` | 1,000 | 合成（5 条指数 × 200 天） |
| | `public_contracts` / `contract_items` / `contract_issuers` | 9 / 16 / 3 | 合成 |
| user.db | `hangars` | 4 | 合成（虚构名） |
| | `inventory_items` | 41 | 合成（机库「演示总仓」28 行） |
| | `user_blueprints` | 10 | 合成（原图 6 / 拷贝 4） |
| | `production_plans` | 12 | 合成 |
| | `plan_blueprint_bindings` | 7 | 合成 |
| | `asset_snapshots` | 120 | 合成（逐日） |
| | `open_orders` | 12 | 合成（买 6 / 卖 6） |
| | `watchlist_items` | 4 | 合成（1 个触发阈值） |
| | `procurement_items` / `price_snapshots` / `order_events` / `user_skills` | 6 / 10 / 3 / 6 | 合成 |
| | `esi_tokens` | 2 | 合成占位（`DEMO-PLACEHOLDER-TOKEN-…`，不是任何真实凭据） |
| items.db | 8 张旧表 | 0 | 只建表 |

schema 版本（`PRAGMA user_version`）与 `services.schema_migrations.DB_SCHEMA_VERSIONS` 一致：
`ref=1` / `mkt=4` / `user=22` / `bp=3`；表结构由来源库的 `sqlite_master` DDL 原样建出，
所以启动时的 `ensure_all_schemas()` 全是空操作（不会动演示库、不会写 `backups/`）。

---

## 5. 每个页面被哪些行点亮

页面键与中文名以 `ui_qml/constants.py` 的 `NAV_TREE` 为准（7 个）。
下表左列是页面，右列是「界面上要看到的区块 → 数据来源」。

### `query` 物品查询

| 区块 | 数据来源 |
|---|---|
| 五中心买卖价（5 条横条 + 最优买/卖摘要） | `market.db.market_prices`：233 个演示物品 × 5 个贸易中心（`region_id` = 10000002/10000043/10000032/10000030/10000028），每个中心都有 `buy_price`/`sell_price`/`buy_volume`/`sell_volume` |
| 制造材料（单价 / 合计） | `blueprint.db.blueprint_materials` + `blueprint_products`（复制来的真实 SDE 配方）× `market_prices`；演示物品里凡有制造蓝图的都能展开出材料 |
| 精炼产物 | `reference.db.reprocessing_materials`（真实配方）× `market_prices` + `data/char_config.json` 的提炼技能；矿石类物品（`category_id=25`）可算 |
| 资产折线（5 条线）+ 资产表 | `user.db.asset_snapshots` **120 天**，`total` / `orders` / `inventory` / `line_value` / `wallet` 五列全部非 0 |
| 产线详情（每人物一块，制造/科研/反应各一行） | `user.db.production_plans`（`status IN ('in_progress','running')`）× `parallels` + `data/char_config.json` 的技能（产线容量） |
| 挂单列表（买单 / 卖单两张表） | `user.db.open_orders`：买 6 笔 / 卖 6 笔，`type_name` 全部非空 |
| 订单簿（挂单明细） | **走 ESI 实时订单**（`ui_qml/workers/order_workers.py`）—— 离线时该块显示「获取订单失败」，见第 8 节 |

### `estimate` 估价

| 区块 | 数据来源 |
|---|---|
| 剪贴板物品清单 → 单价 / 卖价合计 / 买价合计 | 剪贴板文本里的名字经 `services.ui_data_service.search_item_by_name` 命中 `reference.db.item`，价格取 `market_prices`（当前中心 `data/settings.json` 的 `price_settings.mat_hub`） |
| 体积 | `reference.db.item.volume` |
| 精炼价值 | `reference.db.reprocessing_materials` + 提炼技能（`data/char_config.json`） |
| 底部合计（体积 / 卖价 / 买价 / 均价） | 上面三列的汇总 |

可直接粘贴的演示剪贴板内容（`--shots` 用的就是它，名字取自演示 `reference.db` 的 SDE 中文名）：

```
三钛合金	120000	演示分组	0 m³	0 ISK
类晶体胶矿	48000	演示分组	0 m³	0 ISK
类银超金属	12500	演示分组	0 m³	0 ISK
超新星诺克石	3200	演示分组	0 m³	0 ISK
晶状石英核岩	900	演示分组	0 m³	0 ISK
```

### `industry` 工业制造

| 区块 | 数据来源 |
|---|---|
| 计划大表（12 行） | `user.db.production_plans` |
| 状态覆盖 `pending` / `in_progress` / `ready`（另有 1 条 `completed`） | 同上：7 条 pending、3 条 in_progress、1 条 ready、1 条 completed |
| 三类活动：制造 + 科研 + 反应 | `activity` = `manufacturing`（7 条）/ `copying`、`invention`、`researching_material_efficiency`、`researching_time_efficiency`（各 1 条）/ `reaction`（1 条）；`services.plan_category` 据此推出 `manufacturing` / `research` / `reaction` 三档 |
| 子项拆解（可展开的层级） | 计划 1 是母项（`group_number=1`、`sub_level=0`），计划 2/3 是它的子项（`sub_level=1`、`source_mother_ids='1'`、`component_parent_type_id` = 母项产物） |
| 自制件（蓝图绑定列 ✔/差N） | `user.db.user_blueprints`（10 张）+ `plan_blueprint_bindings`（7 条），含 BPO 与 BPC 两种 |
| 待启动小助手 / 材料缺口 | 计划 1（`status=pending`、`mat_hangar_id=2`）的材料在演示库存里**故意不全** → `services.plan_execution.check_materials()` 实测报 **2 种缺料**（`plan_start_check` 据此显示 `material_short`） |
| 运行中产线价值 | 制造中计划 × 材料需求 × `market_prices` 卖单价（`services.asset_snapshot_service._line_value` 的同一口径） |

### `trade` 市场贸易

| 区块 | 数据来源 |
|---|---|
| A→B 跨区价差排行（有行） | `market_prices` 同 233 个物品在**每个**贸易中心都有价 → `services.market_browser_service.fetch_cross_region_spread(Jita, Amarr)` 实测 **233 行** |
| 按分类筛选可用 | `reference.db.market_tree`（真实树）+ `item.market_group_id`；递归子树筛选取演示物品所属分类实测有行（8 行） |
| 「只看有对手盘的」 | 每个中心行的 `buy_volume` / `sell_volume` 都是 1200~90000 的正数 |
| 挂单量变化列 | `market_volume_snapshots`（5 中心 × 60 天，逐日） |
| 贸易购物车 | `data/trade_cart.json`（合成候选） |

### `watchlist` 市场监控

页内两个页签：**大盘**（默认）与**关注物品**。

| 区块 | 数据来源 |
|---|---|
| 大盘 · 5 张指数卡（现值 + 今日/7/30/90/180 日涨跌） | `market.db.market_index_daily`：`type_id` 用保留负数 id（-1 mpi / -2 pppi / -3 sppi / -4 cpi / -5 plex），每条 **200 天**点位 |
| 大盘 · 指数折线 | 同上（`services.market_index_service.get_index_series`）；篮子成员表来自 `price_history` 里被指数选中的成员 |
| 大盘 · 异动榜 | `market.db.price_history`（Jita 逐日成交均价）+ `services.market_movers_service.get_movers(days=3)`，实测 **50 行** |
| 大盘 · 市场广度 / 成交额 | `price_history` 最新交易日（200 天覆盖均匀，`COVERAGE_RATIO` 判定稳定） |
| 关注 · 关注列表 | `user.db.watchlist_items` **4 行**（`added_price` 已填，涨幅列有值） |
| 关注 · 触发阈值提醒 | 其中 1 行的 `price_threshold_sell` 低于当前 `market_prices.sell_price` → 状态栏「1 项触发提醒」，行底色高亮 |
| 关注 · 选中物品的历史折线 + 材料走势 | `price_history`（该物品 200 天）与 `market_volume_snapshots`（材料挂单价） |

### `contract` 合同市场

页内三个页签：**拍卖 / 物品交换 / 运输**。

| 区块 | 数据来源 |
|---|---|
| 拍卖（2 条） | `public_contracts.type='auction'`，`price`/`buyout` 都有值；`contract_items` 各 2 行 → 「内容物市价 vs 一口价」算得出 |
| 物品交换（4 条） | `public_contracts.type='item_exchange'` + `contract_items` 各 3 行 |
| 运输（3 条）+ **跳数与收益可算** | `public_contracts.type='courier'`，起止点用**真实 SDE 空间站 id**（`reference.db.station`），跳数走 `services.logistics.compute_jumps`（真实 `stargate` 星门图）：实测 3 条分别 **11 / 14 / 12 跳**，`isk_per_jump` 与 `isk_per_jump_m3` 都有值 |
| 内容物图标 / 发行方名 | `contract_items` → `reference.db.item`；发行方取自 `contract_issuers`（`演示物流公司` / `Demo Freight Co` / `演示矿业集团`） |
| 过期倒计时 | `date_expired` 锚定日 + 7~14 天 |

### `storage` 仓库管理

| 区块 | 数据来源 |
|---|---|
| 库存行（≥20） | `user.db.inventory_items`：机库「演示总仓」28 行 / 全部 41 行 |
| 图标列 | `data/caches/icons/<type_id>.png`（227 个演示物品的图标） |
| 库存数量 / 单个成本记录 / 占用资金 | `inventory_items.quantity` / `cost_price`（全部 > 0） |
| 规划占用 / 规划剩余 / 缺口 | `production_plans` × `blueprint_products` × `blueprint_materials` 的占用聚合；演示库存刻意把**计划用到的材料**放进来，所以这两列成片有数字，且有行 `缺口 > 0`（标红） |
| 按卖单总价值 / 估值可信 | `market_prices`（Jita）× `domain.market_depth.sell_price_reliable` |
| 「N 项市价不可信，X ISK 未计入」 | 见第 6 节的两行教材数据 |
| 蓝图表（≥6，原图 + 拷贝） | `user.db.user_blueprints`：10 张，`is_bpo` 与 `is_bpc` 并存；产物名/制造时间来自 `blueprint_products`/`blueprint_activities`，材料成本/销售收入/利润率来自 `market_prices` |
| 「占用中」标记 | `plan_blueprint_bindings`（这 10 张里有 7 张被计划占用） |

---

## 6. 两行「市价不可信」教材数据

新版仓库页/资产估值会把「卖单价立不住」的行从估值里剔除，并在底部写
「N 项市价不可信，X ISK 未计入」。演示数据刻意造了两行，用
`domain.market_depth.sell_price_reliable` 实测：

| 角色 | type_id | 卖单价 | 卖侧挂单量 | 买侧挂单量 | 实测判定 | 界面表现 |
|---|---|---|---|---|---|---|
| **离群价**（薄盘） | 36 | 13,500 ISK（正常价的 1500 倍） | **3** | 2,000,000 | `False` | 仓库页「估值可信」列显示 `⚠ 市价不可信`，该行金额进「未计入」，底部出现「1 项市价不可信，1,620,000 ISK 未计入」 |
| **正常厚盘**（对照） | 37 | 正常价 | **52,000** | 48,000 | `True` | 「估值可信」列显示 `可`，金额照常计入 |

两行都在机库「演示总仓」（`hangars.id = 1`），所以仓库页默认机库就能看到对比。
自检里这两条是**实测**而不是断言常量：

```
[自检] PASS  domain.market_depth.sell_price_reliable(离群价) is False  ·  type 36 卖价 13,500 / 卖量 3
[自检] PASS  domain.market_depth.sell_price_reliable(厚盘) is True  ·  type 37 卖量 52,000
```

---

## 7. 自检：逐项 PASS/FAIL

跑 `python scripts/build_demo_data.py` 会自动执行，共 **67 项**。覆盖：

- **schema**：四个库的 `PRAGMA user_version` 与 `DB_SCHEMA_VERSIONS` 一致 + `init_check.check_schema()`
- **reference.db**：`item` 带名 **50,219 行 ≥ 50000**（`services.init_check.ITEMS_NAMED_READY` 阈值，低于它会触发联网初始化向导）、缺名比例 0、`market_tree`、`item_dogma`、`industry_system_costs`、`structure_rigs`、`reprocessing_materials`、`dogma_attribute`、`station`、`solar_system`、蓝图名称缺失
- **blueprint.db**：`blueprint_activities` **19,023 > 1000**
- **market.db**：`market_prices` 行数 + 5 个贸易中心；逐日成交 ≥30 天；指数 5 条 × ≥30 天；挂单量快照；三类合同的行数与内容物；跨区候选
- **真实服务实测**：`get_index_cards()` 五条指数都有点位、`get_movers(days=3)` 有行、`fetch_cross_region_spread()` 有行、按分类筛选有行
- **两行教材数据**：`sell_price_reliable` 分别为 `False` / `True`
- **user.db 五类表行数**：`hangars` / `inventory_items` / `user_blueprints` / `production_plans` / `asset_snapshots` / `open_orders` / `watchlist_items`
- **工业制造**：覆盖 `pending`/`in_progress`/`ready`、覆盖制造+科研+反应、子项拆解字段、待启动小助手数据源 ≥8 条、材料缺口 > 0
- **仓库管理**：蓝图 ≥6 且原图与拷贝并存、库存行数、图标、规划占用/缺口/占用资金有数、「N 项市价不可信未计入」有数
- **市场监控**：关注列表 3~5 个、其中 ≥1 个触发阈值
- **物品查询**：资产折线 ≥14 天且 5 条线都有值、挂单买/卖分表都有行
- **估价页**：剪贴板物品的买/卖单价、体积、精炼价值都有数
- **离线**：`settings.json.auto_update_enabled=false`、`char_config.json`、`terminology.json` 就位、图标 ≥30 个
- **红线**：未对 `user.db` 执行任何数据行查询（计数 0）、演示 `user.db` 是新建文件、演示根标记文件存在

任何一项 FAIL → 脚本退出码非 0。

---

## 8. 页面装载与截图

```bash
.venv/Scripts/python.exe scripts/build_demo_data.py --shell   # 打印「已装载 7/7 个页面」
.venv/Scripts/python.exe scripts/build_demo_data.py --shots   # → <演示根>/shots/*.png
```

`--shell` / `--shots` 直接构造 `ui_qml.shell_window.ShellWindow`（应用根 = 演示根），并在构造前
把三条会联网/弹窗的路径换成空操作：`ShellWindow._init_price_check`、`ShellWindow._check_first_run`、
`ShellWindow._maybe_daily_backup`、`ContractBridge._start_backfill`。

`--shots` 产出 12 张（页面 → 文件）：

| 页面 | 文件 | 说明 |
|---|---|---|
| 物品查询 | `query-idle.png` | 空闲态仪表盘：产线详情 + 资产折线 + 资产表 + 挂单列表 |
| | `query.png` | 详情态（可制造品）：五中心价 + 制造材料 |
| | `query-ore.png` | 详情态（矿石）：五中心价 + 精炼产物 |
| 估价 | `estimate.png` | 剪贴板 5 项 → 单价/合计/体积/精炼价值 |
| 工业制造 | `industry.png` | 12 条计划（含子项展开箭头、状态标签） |
| 市场贸易 | `trade.png` | Jita→Amarr 排行 + 分类树 |
| 市场监控 | `watchlist.png` | 大盘：5 张指数卡 + 折线 + 异动榜 |
| | `watchlist-watch.png` | 关注物品：列表 + 详情 |
| 合同市场 | `contract-auction.png` / `contract-exchange.png` / `contract-courier.png` | 三个页签各一张 |
| 仓库管理 | `storage.png` | 库存表（图标/规划占用/缺口/估值可信） |

离屏平台（`QT_QPA_PLATFORM=offscreen`）下 `QFontDatabase` 是 0 个字体，文字会渲染成方框
—— 只用于核对结构/配色/「有没有数据」。要出正式配图用 `--shots --shots-real`。

**页面装载是硬指标**：`shell_window._register_pages()` 在页面构造抛异常时会
`log.warning("页面 %s 未迁移到 QML 或加载失败，本页暂缺")` 并跳过该页，所以
`--shots` 会把「装载了几个页面」当验收，不是 7/7 直接返回退出码 2。

---

## 9. 已知限制

1. **订单簿（物品查询页右上面板）需要联网。** 它读的是 ESI 的**实时公开订单**
   （`ui_qml/workers/order_workers.py`），演示数据里没有、也不该有这一块 ——
   离线时该面板显示「获取订单失败」。README 若要这一块，联网拍一次即可
   （那条请求只取公开订单，不涉及账号数据）。同一页的「挂单列表」是**本地
   `user.db.open_orders`**，离线有数。
2. **不要用裸 `Main.py` 起演示根。** `StartupCheckWorker` 会跑 `check_all()`，
   其中 `icons` 一项要求图标缓存覆盖全集 80%（18,616 个），而整目录复制
   67 MB 图标缓存正是本任务禁止的 → `all(status.values())` 为 False，`Main` 会先弹
   **联网初始化向导**。用 `--shell`（或 `--shots`）起外壳，它们绕开那条启动链。
   其余 9 项（schema / items / price_baseline / blueprints / implants / industry /
   rigs / sde_core / sde_data）在演示根上实测全部为 `True`。
3. **`--shots` 会轻微写脏演示根**：`watchlist_items.last_buy_price/last_sell_price`（价格变化检测）
   与 `data/market_monitor_cache.json`（大盘页首屏缓存）。要一份干净的根，重跑一次构建即可。
4. **演示价格是合成的**，量级贴近游戏但**不等于**任何真实行情；
   指数点位、成交量、K 线都是随机游走生成的，不要拿来对照真实市场。

---

## 10. 相关文件

- `scripts/build_demo_data.py` —— 本数据集的全部生成逻辑与自检
- `scripts/shell_snapshot.py` —— 日常界面回归用的离屏/真窗口截图（`--real` 会复制真实
  `database/`、`data/` 到临时目录，**公开截图不要用它**）
- `docs/dev/data.md` —— 四个库的表结构与职责

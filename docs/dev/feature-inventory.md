# 功能清单（内部核对底账）

> **用途**：维护 `README.md` 时逐条核对「这条宣传点是否真有界面入口」。写 README 的原则是
> **宁可少写一条，也不写界面里点不到的东西**。本文件不进宣传文案，只作事实底账。
>
> **口径**：以 `ui_qml/qml/pages/**` + `ui_qml/bridge/**` 的**当前实现**为准；
> `docs/user/**` 与 `docs/index.md` 只当线索（其中多处已与代码不符，见第 12 节）。
> `CHANGELOG.md` 只用来看「最近加了什么能力」，不写进 README。
>
> **怎么核对**：每条给「功能 → 用户能拿它干什么 → 代码入口（`文件:方法`）」。
> 行号会随重构漂移，**以方法名 / objectName / 按钮文案为准**。
>
> **更新时机**：新增页面、新增用户可见动作、或者发现 README 写了点不到的东西时，
> 先改这里，再改 README。

---

## 0. 导航页面总表

七页导航是单一事实来源 `ui_qml/constants.py` 的 `NAV_TREE`
（`(key, 标题, 图标语义键, 图标配色)`）：

| 导航项 | page key | 页面 QML | 桥 |
|--------|----------|----------|-----|
| 物品查询 | `query` | `ui_qml/qml/pages/QueryPage.qml` | `ui_qml/bridge/query_bridge.py:QueryBridge` + `query_detail_bridge.py:QueryDetailBridge` + `query_dashboard_bridge.py:QueryDashboardBridge` |
| 估价 | `estimate` | `ui_qml/qml/pages/EstimatePage.qml` | `ui_qml/bridge/estimate_bridge.py:EstimateBridge` |
| 工业制造 | `industry` | `ui_qml/qml/pages/IndustryPage.qml` | `ui_qml/bridge/industry_bridge.py:IndustryBridge` → `ui_qml/views/industry_view.py:IndustryPage` |
| 市场贸易 | `trade` | `ui_qml/qml/pages/TradePage.qml` + `TradeCartWindow.qml` | `ui_qml/bridge/trade_bridge.py:TradeBridge` + `trade_cart_bridge.py:TradeCartBridge` |
| 市场监控 | `watchlist` | `ui_qml/qml/pages/MarketMonitorPage.qml`（容器）→ `MarketPulsePane.qml`（大盘）+ `WatchlistPage.qml`（关注物品） | `ui_qml/bridge/market_pulse_bridge.py:MarketPulseBridge` + `watchlist_bridge.py:WatchlistBridge`（容器装配 `ui_qml/monitor_page.py:monitor_spec`） |
| 合同市场 | `contract` | `ui_qml/qml/pages/ContractPage.qml` + `ContractTabPane.qml` | `ui_qml/bridge/contract_bridge.py:ContractBridge` |
| 仓库管理 | `storage` | `ui_qml/qml/pages/StoragePage.qml` | `ui_qml/bridge/inventory_bridge.py:InventoryBridge` |

外壳：`ui_qml/shell_window.py:ShellWindow` + `ui_qml/qml/shell/Main.qml`。
主工具栏（价格与更新的入口）：`ui_qml/qml/shell/Main.qml`。
五个贸易中心：`core/constants.py:TRADE_HUB_IDS`（Jita / Amarr / Dodixie / Rens / Hek）。
**中文名在界面里是三套并存，写 README 时不要声称「界面显示某某中文名」**：

- 估价页中心下拉 / 机库标签 → `吉他 (Jita)` 这种中文+英文对照（`ui_qml/bridge/estimate_bridge.py:EstimateBridge.hubOptions`、`ui_qml/bridge/inventory_bridge.py:InventoryBridge.hubs`，中文名取自 `data/terminology.json` 的 `system_names`）
- 查询页「5 个贸易中心价格」面板 / 市场贸易页下拉 → **只显示英文键**（`ui_qml/bridge/query_detail_bridge.py:QueryDetailBridge._build_hub_summary`、`ui_qml/models/query_detail_model.py`、`ui_qml/qml/pages/query/HubPricePanel.qml`、`ui_qml/bridge/trade_bridge.py:_hub`）
- 人物设置市场费率 / NPC 直售 → 只有 4 个中心，中文名也不一致（`core/char_settings_common.py`）

双主题：`ui_qml/theme/registry.py:THEME_REGISTRY`（`fluent-dark`「Fluent 深色」/ `fluent-light`「Fluent 浅色」，
界面卡片文案取 `name_zh`，见 `ui_qml/bridge/settings_bridge.py:ThemeSelectorBridge`）。
程序自称 **EVE 商人助手**（`Main.py:main` 的 `setApplicationName`、`build_release.py` 的发行包名、
`LICENSE`）；文档站标题仍写「EVE 工业助手」（`docs/.vitepress/config.mts`、`docs/index.md`）——**以程序名为准**。

---

## 1. 物品查询（`query`）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 前缀候选搜索 | 输入中/英文名或 Type ID，边打字边出全部前缀匹配候选（数字按 Type ID 精确匹配） | `ui_qml/qml/pages/QueryPage.qml`（`searchInput.onTextChanged`）→ `query_bridge.py:QueryBridge.onTextChanged` / `_fetch_suggestions` |
| 候选即详情 | 点候选那一条直接出详情；回车 = 选第一条 | `ui_qml/qml/pages/QueryPage.qml`（`onAccepted`）→ `query_bridge.py:QueryBridge.pickSuggestion` → `query_detail_bridge.py:QueryDetailBridge.setItem` |
| 搜索历史 | 搜索框空着时点一下，列出最近搜过的词 | `ui_qml/qml/pages/QueryPage.qml`（`onPressed`）→ `query_bridge.py:QueryBridge.showHistory` / `clearHistory`；数据在 `core/search_history.py` |
| 五个贸易中心价格 | 看 Jita / Amarr / Dodixie / Rens / Hek 的卖单买单价，标出最便宜 / 最贵 | `ui_qml/qml/pages/query/HubPricePanel.qml`（「中心 / 卖单 ↑ / 买单 ↓」）← `query_detail_bridge.py:QueryDetailBridge._load_hub_prices` / `_build_hub_summary` |
| 实时订单面板 | 看该物品 Top5 买单 / 卖单，一键复制最优买卖价 | `ui_qml/qml/pages/query/OrderPanel.qml`（「复制卖单价 / 复制买单价」）← `query_detail_bridge.py:QueryDetailBridge._load_orders` / `_render_orders` / `copyPrice` |
| 精炼面板 | 选人物 / 数量 / 站点（NPC 空间站 / 玩家设施）算拆解产物与价值 | `ui_qml/qml/pages/query/RefinePanel.qml` ← `query_detail_bridge.py:QueryDetailBridge.setRefineCharIndex` / `setRefineQty` / `setRefineFacility` / `_load_refine`；公式在 `services/refining_service.py` |
| 精炼产率按人物技能 | 产率取当前人物真实技能表；没配技能按 0 级算 | `query_detail_bridge.py:QueryDetailBridge._refine_skills`；`ui_qml/bridge/estimate_bridge.py:EstimateBridge._current_skills` |
| 制造材料面板 | 改制造数量与价格中心，看造它要哪些料、各值多少 | `ui_qml/qml/pages/query/MaterialPanel.qml`（「制造数量 / 价格中心」）← `query_detail_bridge.py:QueryDetailBridge.setMaterialQty` / `setMaterialHubIndex` / `_load_materials` |
| 区域切换 | 换查询与详情用的贸易中心 | `ui_qml/qml/pages/QueryPage.qml`（区域下拉）→ `query_bridge.py:QueryBridge.setRegionIndex` |
| 宏「全物品」按钮 | 把工作区切成全物品浏览 / 再点一次返回 | `ui_qml/qml/pages/QueryPage.qml`（`allItemsButton`，文案在「全物品」/「返回」之间切）→ `query_bridge.py:QueryBridge.openAllItems` / `closeAllItems` / `allItemsVisible` |
| 清空 | 清掉当前选中（或清全物品的筛选），回到空闲态仪表盘 | `ui_qml/qml/pages/QueryPage.qml`（「清空」）→ `query_bridge.py:QueryBridge.clear` |
| 首屏仪表盘 | 不查东西时的主区域（产线详情 / 资产折线图 / 挂单列表） | `ui_qml/qml/pages/query/QueryDashboard.qml` |
| 产线详情 | 每个人物一块，制造 / 科研 / 反应各一行容量条 + 「待下线 N」 | `QueryDashboard.qml`（「产线详情」）← `query_dashboard_bridge.py:QueryDashboardBridge.occupancyRows` / `occupancyByChar` / `occupancySummary` |
| 资产折线图 | 总资产 / 挂单金额 / 库存材料 / 运行中产线价值 / 钱包余额五条线；图例可开关、四档时间跨度、手动刷新 | `ui_qml/qml/pages/query/AssetChartPanel.qml`（「资产（表格显示）」「刷新」「时间跨度」）← `query_dashboard_bridge.py:QueryDashboardBridge.assetSeries` / `assetSummaryRows` / `setRangeIndex` / `toggleSeries` / `reloadAssets` |
| 挂单列表（读游戏导出） | 读 `我的文档\EVE\logs\Marketlogs\` 里最新的订单导出文件，分买单 / 卖单两块 | `ui_qml/qml/pages/query/OpenOrdersPanel.qml`（「读取订单」）← `query_dashboard_bridge.py:QueryDashboardBridge.readOrders`；解析在 `services/order_export.py` |
| 从 ESI 同步钱包与挂单 | 拉全部已绑定角色的钱包余额与未结挂单，直接覆盖本地 | `OpenOrdersPanel.qml`（「从 ESI 同步」）← `query_dashboard_bridge.py:QueryDashboardBridge.syncOrdersFromEsi`；`ui_qml/workers/esi_wallet_worker.py` |
| 钱包余额手填 / 剪贴板导入 | 手填 ISK 点「记录」，或从「钱包 → 交易记录」复制后取最新一笔余额 | `OpenOrdersPanel.qml`（「钱包余额 / 记录 / 从剪贴板导入」）← `query_dashboard_bridge.py:QueryDashboardBridge.setWalletText` / `importWalletFromClipboard` |
| 军团钱包开关 | 把军团钱包各分部余额算进总资产（需军团会计权限） | `OpenOrdersPanel.qml`（「钱包余额含军团钱包」）← `query_dashboard_bridge.py:QueryDashboardBridge.setIncludeCorpWallet` |
| 订单变动确认 | 导入后逐条确认「买到了 / 卖完了」还是「手动撤销」，据此加减钱包 | `query_dashboard_bridge.py:QueryDashboardBridge.previewOrderChanges` / `applyOrderChanges`；文案在 `ui_qml/bridge/order_change_bridge.py` |

---

## 2. 估价（`estimate`）与另外两个物品浏览器

### 2.1 估价页（导航 → 估价）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 粘贴剪贴板估价 | 从游戏 Ctrl+C 复制物品列表，一键补全价格 | `ui_qml/qml/pages/EstimatePage.qml`（「粘贴剪贴板」）← `estimate_bridge.py:EstimateBridge.paste` → `ui_qml/workers/estimate_workers.py:ClipboardParseWorker` |
| 估价表列 | 图标 / 名字 / 数量 / 单价 / 卖价合计 / 买价合计 / 体积 m³ / 精炼价值 | `ui_qml/qml/pages/EstimatePage.qml`（`columnTitles`） |
| 价格中心 + 折扣 | 换取价中心、给总价打折 | `EstimatePage.qml`（「价格中心」「折扣」）← `estimate_bridge.py:EstimateBridge._set_hub` / `_set_discount` |
| 精炼价值列 | 逐行按所选人物技能与场地算精炼价值 | `EstimatePage.qml`（「人物」「精炼场地」）← `estimate_bridge.py:EstimateBridge._rebuild_refine_values` / `_current_skills` |
| 搜索添加物品 | 不粘贴时也能按名字搜一件加进来 | `estimate_bridge.py:EstimateBridge.addItem` |
| 行右键动作 | 复制名称 / 复制 Type ID / 修改数量 / 数量翻倍 / 修改蓝图 ME-TE / 删除条目 / 清空表格 | `EstimatePage.qml`（右键菜单）← `estimate_bridge.py:EstimateBridge.setQty` / `multiplyQty` / `setBlueprint` / `removeRow` / `clearAll` |
| 更新价格 | 重读本地价格并重算全表（不联网：走本地 `pricing_service`） | `EstimatePage.qml`（「更新价格」）← `estimate_bridge.py:EstimateBridge.refreshPrices` |
| 复制总价 | 「卖价到剪贴板」「买价到剪贴板」（纯数字） | `EstimatePage.qml` ← `estimate_bridge.py:EstimateBridge.copyTotals` |
| 添加到机库 | 把整批估价结果按增量入库到选定机库 | `EstimatePage.qml`（「机库」「添加到机库」）← `estimate_bridge.py:EstimateBridge.addToHangar` |
| 使用说明 | 页内「怎么用」帮助 | `EstimatePage.qml`（「怎么用」） |

### 2.2 全物品浏览（查询页工具栏 →「全物品」，**内嵌**在工作区）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 分类树 | 按市场分类树翻全表，可展开 / 折叠 | `ui_qml/qml/dialogs/AllItemsDialog.qml`（`ai` 由 `QueryPage` 注入）← `all_items_bridge.py:AllItemsBridge.toggleTreeNode` / `selectTreeNode` / `_refresh_tree` |
| 全表列 | 图标 / 中文名 / English / 买价 / 卖价 / 均价 / 体积 | `ui_qml/models/all_items_models.py:BCOLS`；`AllItemsDialog.qml` |
| 表头排序 | 点列头排序（再点反向） | `all_items_bridge.py:AllItemsBridge.sortByColumn` |
| 搜索 / 类别下拉 | 按名字筛当前列表、按类别筛 | `AllItemsDialog.qml`（「搜索:」「类别:」）← `all_items_bridge.py:AllItemsBridge.setSearchText` / `setCategoryIndex` / `_apply` |
| 双击进详情 | 双击一行回到该物品的查询详情页 | `AllItemsDialog.qml`（行双击）→ `all_items_bridge.py:AllItemsBridge.itemActivated`（内嵌态）→ `query_bridge.py:QueryBridge.selectItemFromAllItems` |
| 内嵌态裁剪 | 内嵌时**不显示**「制造评分 / 贸易评分 / 设置 / 批量对比 / 导出 / 置顶」与右键菜单 | `ui_qml/qml/dialogs/AllItemsDialog.qml`（各按钮 `visible: !page.embedded`）、`all_items_bridge.py:AllItemsBridge.embedded` |

### 2.3 可制造物品窗口（工业制造页 →「从全物品添加」）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 独立紧凑置顶窗 | 列宽按内容实测、可置顶，适合挂在游戏旁边 | `ui_qml/qml/dialogs/ManufacturableItemsDialog.qml`（「置顶」）← `manufacturable_items_bridge.py:ManufacturableItemsBridge.setPinned` / `_autofit_widths` |
| 列 | 图标 / 中文名 / English / 买价 / 卖价 + 成本 / 利润每件 / 产能每天 / 日订单量(Jita) / 日成交量(Jita) / 状态 / 利润率% | `manufacturable_items_bridge.py:_MFG_BCOLS` / `_MFG_MCOLS` |
| 筛选 | 类别、库存/状态、日销量、利润率 ≥、中心、人物、设施税；刷新计算 | `ManufacturableItemsDialog.qml`（「类别:」「库存/状态:」「日销量:」「利润率 ≥」「中心:」「人物:」「设施税:」「刷新计算」）← `manufacturable_items_bridge.py:ManufacturableItemsBridge.setCategoryIndex` / `setStockFilterIndex` / `setSalesFilterIndex` / `setMinMarginText` / `setHubIndex` / `setCharIndex` / `setTax` / `refreshScores` |
| 库存 / 状态档位 | 全部 / 库中有 / 有挂单 / 库中有且有挂单 / 无蓝图 / 有原图待拷贝 / 有拷贝待发明 / 正在制造 | `manufacturable_items_bridge.py:_STOCK_FILTERS` + `_STOCK_STATE_KEYS` |
| 单击 / 复制 | 单击单元格复制该格文字 | `manufacturable_items_bridge.py:ManufacturableItemsBridge.clickCell` |
| 行右键 | 复制名称 / 复制蓝图名称 / 复制整行 / 制造核算明细 / 挂单建议 / 加入制造列表 / 加入拷贝·发明·效率研究规划 | `ManufacturableItemsDialog.qml`（右键菜单）← `manufacturable_items_bridge.py:ManufacturableItemsBridge.copyName` / `copyBlueprintName` / `copyRow` / `showBreakdown` / `showMarketAdvice` / `addToPlan` / `addResearch` |
| 制造材料明细 | 双击一行看这件东西的制造材料清单 | `ManufacturableItemsDialog.qml`（行双击）← `manufacturable_items_bridge.py:ManufacturableItemsBridge.openMaterials` |
| 挂单建议弹窗 | 该挂单还是直接吃单 / 薄市场别挂大单 | `ui_qml/bridge/market_advice_bridge.py:MarketAdviceQmlDialog`（入口 `ManufacturableItemsBridge.showMarketAdvice`） |

---

## 3. 工业制造（`industry`）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 蓝图搜索候选添加 | 输入中/英文名实时出候选，选中即加进计划表 | `ui_qml/qml/pages/IndustryPage.qml`（「蓝图」「添加」）← `industry_bridge.py:IndustryBridge.requestSuggestions` / `addPlan` |
| 从全物品添加 | 打开可制造物品窗口挑 | `IndustryPage.qml`（「从全物品添加」）← `industry_bridge.py:IndustryBridge.openManufacturableBrowser` → `ui_qml/views/industry_view.py:IndustryPage.open_manufacturable_browser` |
| 双行价格来源 | 材料与成品各自配 Hub / 价格类型 / 倍率 | `IndustryPage.qml`（两行 `FPriceSourceRow`：`label: 材料` / `label: 成品`，组件在 `ui_qml/qml/components/FPriceSourceRow.qml`）← `industry_bridge.py:IndustryBridge.setPriceSetting` / `priceSettings` |
| 计划大表（20 列） | 勾选备料 / 类别 / 图标 / 产品 / 备注 / 组号 / 子级 / 状态 / 人物 / 流程 / 蓝图 / 时长 / 产能 / 设施 / 输出 / 成本 / 自制成本-件 / 利润 / 市场利润率% / 个人利润率% | `ui_qml/models/industry_models.py:PlanTableModel._HEADERS`（含勾选列共 20 项） |
| 行内编辑 | 直接改备注 / 人物 / 设施 | `ui_qml/models/industry_models.py:PlanTableModel._EDITABLE_COLS`；`ui_qml/bridge/plan_table_bridge.py:PlanTableBridge.commitEdit` |
| 行右键编排 | 展开/折叠共享组件、编辑生产计划、绑定库存蓝图、添加备注、勾选备料、项目启动、撤销启动（返还材料）、下线、设为待生产（复用）、智能调整（母项递归拆解 / 子项并行配置 / 子项大规模产线并行）、查看核算、复制蓝图名称、删除产线 | `ui_qml/qml/pages/PlanTablePane.qml`（`rowMenu`）← `plan_table_bridge.py:PlanTableBridge.toggleSharedCollapse` / `editPlans` / `bindBlueprint` / `addNotes` / `setMaterialsReady` / `startPlans` / `undoStartPlans` / `completePlans` / `resetForReusePlans` / `decomposeParent` / `adjustChildren` / `massParallel` / `viewCostBreakdown` / `copyBlueprintName` / `deletePlans` |
| 表头右键切列 | 显示 / 隐藏任意列 | `ui_qml/qml/pages/PlanTablePane.qml`（`headerMenu`）← `plan_table_bridge.py:PlanTableBridge.setColumnVisible` / `columnVisible` |
| 表头排序 / 列宽 | 点列头排序；列宽可拖、可自动量宽 | `plan_table_bridge.py:PlanTableBridge.sortBy` / `setColumnWidth` / `autofitWidths` |
| 视图切换 | 数据视图 ↔ 甘特图 | `IndustryPage.qml`（「数据视图」「甘特图」）← `industry_bridge.py:IndustryBridge.setViewMode` |
| 甘特图 | 按 BOM 依赖串行（子项先做、母项接后），柱条末端给预计完成时刻；可调粒度与缩放 | `ui_qml/qml/pages/FGanttChart.qml` ← `industry_bridge.py:IndustryBridge.ganttRows` / `ganttMaxHours` / `set_gantt_plans` |
| 状态 / 类别筛选 | 两个正交下拉 | `IndustryPage.qml`（两个 `FComboBox`）← `industry_bridge.py:IndustryBridge.setFilterIndex` / `setCategoryIndex` / `filterOptions` / `categoryOptions` |
| 定向价格刷新 | 只拉活跃计划涉及物品的价格（5 分钟缓存 TTL + 并发 50） | `IndustryPage.qml`（「刷新」）← `industry_bridge.py:IndustryBridge.refreshPrices` → `ui_qml/workers/industry_page_workers.py` |
| 保存价格 | 把当前双行价格设置落盘 | `IndustryPage.qml`（「保存价格」）← `industry_bridge.py:IndustryBridge.savePrices` |
| 产线启动小助手 | 独立工具窗：按人物分行启动产线、可部分启动、加备注 | `IndustryPage.qml`（「产线启动小助手」）← `industry_bridge.py:IndustryBridge.launchWizard`；`ui_qml/qml/pages/LauncherWindow.qml` + `ui_qml/views/industry/production_launcher.py` |
| 采购小助手 | 独立可置顶小窗：待采购 / 已有库存两分区，可排序、手改采购量、删行；复制整份清单、增量添加到仓库、从钱包交易记录粘贴、一键完成所有 | `IndustryPage.qml`（「采购小助手」）← `industry_bridge.py:IndustryBridge.openProcurement`；`ui_qml/qml/pages/ProcurementWindow.qml` + `ui_qml/bridge/procurement_bridge.py:ProcurementBridge.refresh` / `copyAll` / `addToHangar` / `importPurchases` / `completeAll` / `editQty` / `deleteRow` / `setPinned` |
| 汇总弹窗 | 所需蓝图表 / 填料总表 / 产出总表 / 人物占用 | `IndustryPage.qml`（四个底部按钮）← `industry_bridge.py:IndustryBridge.openBlueprintList` / `openMaterialsSummary` / `openOutputSummary` / `openCharUsage` |
| 汇总表复制 | 只读汇总表双击任一格复制那一格文字 | 各汇总桥 + `ui_qml/bridge/summary_dialog.py` |
| 个人利润率 | 已有材料按库存加权平均成本、缺口按市价 | `services/scoring_service.py:ScoringService.calculate_personal_margin`（列见 `industry_models.py:PlanTableModel._HEADERS`） |
| 自制成本 / 件 | 判断一件料自己造还是买（料钱 + 作业费 ÷ 单轮产出） | `services/scoring_service.py:ScoringService.manufacturing_unit_costs`；采购表列见 `ui_qml/views/procurement_tab.py:_apply_make_costs` |
| 成本公式 | 材料成本 / 安装费（EIV + SCI + 设施税 + SCC 附加费）/ 成品价值 / 利润 | `domain/formulas.py`、`core/eve_formulas.py` |

---

## 4. 市场贸易（`trade`）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| A → B 全品类价差排行 | 选起终点贸易中心与各自价格口径，点「开始计算」出排行 | `ui_qml/qml/pages/TradePage.qml`（「从」「到」「开始计算」）← `trade_bridge.py:TradeBridge.setFromIndex` / `setToIndex` / `setFromSideIndex` / `setToSideIndex` / `analyze` / `_start_rank` |
| 切换方向 | 两个中心与各自价格类型一起对调 | `TradePage.qml`（「⇄ 切换方向」）← `trade_bridge.py:TradeBridge.swapDirection` |
| 价格口径 | 从 A 默认「卖单」（买入要付卖单价）、到 B 默认「买单」 | `trade_bridge.py:_SIDE_LABELS`（卖单 / 买单）；`TradePage.qml` 两个下拉 |
| 排行表列 | 中文名称 / 英文名称 / 起点价格 / 终点价格 / 价差 / 每单位体积 / 每方利润 / B侧挂单变化 / 起点日成交量 / 终点日成交量 / 加入购物车 | `ui_qml/models/trade_rank_model.py:COLUMNS` |
| 表头排序 | 点列头排序（再点反向） | `trade_bridge.py:TradeBridge.sortBy`；`ui_qml/models/trade_rank_model.py:TradeRankModel.sort` |
| 筛选项 | 「只看赚钱的」+ 对手盘门槛（不限 / 两侧 ≥ 1 / ≥ 10 / ≥ 100） | `TradePage.qml`（「只看赚钱的」「（对手盘：两侧在所选价位的挂单量）」）← `trade_bridge.py:TradeBridge.setHideUnprofitable` / `setLiquidityIndex` / `_apply_filters`（档位常量 `_LIQUIDITY_LABELS`） |
| 市场分类筛选 | 一级分类下拉 + 左树按整棵子树精确筛（两者互斥） | `TradePage.qml`（「市场分类」+ 左树）← `trade_bridge.py:TradeBridge.setCategoryIndex` / `toggleTreeNode` / `selectTreeNode` / `clearTreeSelection` |
| 只读本地价格 | 「开始计算」不发 ESI 请求；状态栏显示各中心快照时间 | `trade_bridge.py:TradeBridge.analyze` / `_fetch_times` / `_status_text` |
| 贸易购物车 | 独立置顶窗：名称 / 价差 / 数量 / 总计金额；标记已购买、清理已购买、复制名称、移除 | `TradePage.qml`（「购物车」「加入购物车」）← `trade_bridge.py:TradeBridge.addToCart` / `openCart` / `cartSummary`；`ui_qml/qml/pages/TradeCartWindow.qml` + `trade_cart_bridge.py:TradeCartBridge.setQty` / `togglePurchased` / `removeItem` / `copyName` / `clearPurchased` / `setPinned` |

---

## 5. 市场监控（`watchlist`）

容器：`ui_qml/qml/pages/MarketMonitorPage.qml` 两个分段页签 **大盘**（默认）/ **关注物品**，
装配见 `ui_qml/monitor_page.py:monitor_spec` / `_MonitorHooks`。

### 5.1 大盘

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 五个指数卡 | 矿物指数（MPI）/ 初级投入品（PPPI）/ 次级投入品（SPPI）/ 消费品（CPI·代理）/ PLEX（全服统一价），基期 = 100 | `services/market_index_service.py:INDEX_KEYS` / `INDEX_LABELS` / `get_index_cards`；`ui_qml/qml/pages/MarketPulsePane.qml`（「市场大盘」「（基期=100 · 只用 Jita 成交均价）」） |
| 指数折线 + 7 日均线 + 粒度 | 五条基期 = 100 的折线，7 日均线可开关，粒度可切（切粒度只重画已加载的点） | `MarketPulsePane.qml`（「7 日均线」+ 粒度选择）← `market_pulse_bridge.py:MarketPulseBridge.selectIndex` / `setShowMa7` / `setRangeIndex` / `rangeLabels` |
| 卡片涨跌 | 最近一个点与 7 / 30 / 90 / 180 天涨幅 | `services/market_index_service.py:CHG_WINDOWS` / `_cards_from_points` |
| 量价 / 广度 | 最新交易日的涨跌家数与成交额 | `MarketPulsePane.qml`（「量价 / 广度」）← `services/market_index_service.py:get_breadth`；`market_pulse_bridge.py:MarketPulseBridge._apply_breadth` |
| 篮子成员表 | 各指数成分、权重（单成分上限 25%）、近 30 天涨幅 | `MarketPulsePane.qml`（「篮子成员 · …」）← `services/market_index_service.py:get_index_series` / `_member_row`；`MarketPulseBridge._sync_members` |
| 市场诊断 | 按指数与广度规则推导的一句话判断（页面标注「不是预测、也不是投资建议」） | `MarketPulsePane.qml`（「市场诊断」「（按指数与广度规则推导，不是预测、也不是投资建议）」）← `MarketPulseBridge._sync_divergence` / `_index_chg_pct` |
| 异动榜①合格成分 | 过了指数准入 + 流动性 / 稳定性门槛的条目 | `MarketPulsePane.qml`（「异动榜 ① 合格成分（过准入 + 流动性门槛，可信）」）← `services/market_movers_service.py:get_movers`；`MarketPulseBridge._apply_movers` |
| 异动榜②全市场 | 未过准入的也列出来只作线索；涨幅达 200% 标「极端」 | `MarketPulsePane.qml`（「异动榜 ② 全市场…标「极端」的是 ≥200% 的大幅波动」）← `services/market_movers_service.py:EXTREME_CHG_PCT` / `get_movers` |
| 异动榜门槛 | 日均成交量下限、近期有成交天数下限、前窗口至少 1 天成交、窗口内价格离散度上限、垃圾量日剔除 | `services/market_movers_service.py:MIN_DAILY_VOLUME` / `MIN_TRADING_DAYS` / `MIN_BASE_DAYS` / `MAX_WINDOW_SPREAD` / `_window_price` |
| 数据状态行 | 各中心快照天数与最后日期 | `MarketPulsePane.qml`（「数据状态（各中心快照天数与最后日期）」）← `MarketPulseBridge._apply_status` |
| 点行开右侧抽屉 | BOM 逐级传导链 + 挂单建议 | `MarketPulsePane.qml`（行点击 → 抽屉）← `MarketPulseBridge.openMover` / `openMember` / `_open_detail` / `_load_advice` |
| 挂单建议四档 | 两侧挂单划算 / 直接吃单更划算 / 薄市场别挂大单 / 本地没有数据 | `ui_qml/bridge/market_advice_bridge.py:_ADVICE_TITLES` |
| 行右键 | 复制名称 / 加入关注列表 / 加入制造列表 | `MarketPulsePane.qml`（右键菜单）← `market_pulse_bridge.py:MarketPulseBridge.copyName` / `addToWatchlist` / `addToPlan` |
| 刷新指数 | 重算大盘逐日点位（本页唯一联网动作） | `MarketPulsePane.qml`（`refreshIndexButton`）← `market_pulse_bridge.py:MarketPulseBridge.refreshIndex` → `IndexRefreshWorker` |
| 使用引导 | 「这一页怎么用」弹窗，可关掉不再提示 | `MarketPulsePane.qml`（「这一页怎么用」「知道了」）← `MarketPulseBridge.dismissGuide` / `on_shown` |

### 5.2 关注物品

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 添加关注 | 搜索物品 + 选区域 + 填备注 → 添加 | `ui_qml/qml/pages/WatchlistPage.qml`（「搜索物品:」「区域:」「备注:」「添加关注」）← `watchlist_bridge.py:WatchlistBridge.onSearchChanged` / `pickSuggestion` / `setRegionIndex` / `setNote` / `add` |
| 阈值提醒 | 设「买价 ≤ X」/「卖价 ≥ Y」时提醒 | `WatchlistPage.qml`（「设置买价阈值 / 设置卖价阈值」）← `watchlist_bridge.py:WatchlistBridge.setThreshold` / `rowInfo` |
| 价格变化检测 | 定时检测价格变化并提示 | `services/watchlist_manager.py:check_price_changes`；`watchlist_bridge.py:WatchlistBridge.checkPriceChanges` |
| 刷新 / 排序 / 删除 | 表内操作 | `WatchlistPage.qml`（「刷新价格」「删除选中」「排序:」）← `watchlist_bridge.py:WatchlistBridge.refresh` / `setSortIndex` / `removeRow` |
| 行内备注 | 改某一行备注 | `watchlist_bridge.py:WatchlistBridge.setRowNote` |
| 加入时价格锚点 | 「当前 / 加入时」比的是挂单价，加入时取 Jita 卖价 | `watchlist_bridge.py:WatchlistBridge.columns`；`services/watchlist_manager.py`（加入时取价） |
| 详情区 | 选中行看历史与材料价曲线 | `WatchlistPage.qml` + `ui_qml/qml/pages/watchlist/WatchlistDetailPane.qml` ← `WatchlistBridge.selectRow` / `setRangeIndex` / `setShowMaterials` / `_load_detail` / `_rebuild_charts` |

---

## 6. 合同市场（`contract`）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 三个页签 | 拍卖 / 物品交换 / 运输，各带条数徽标 | `ui_qml/bridge/contract_bridge.py:_TABS`；`ContractBridge.setTabIndex` / `_refresh_tab_counts` |
| 星域选择 | 从常用贸易中心点选，或手输星域名（如 静谧谷 / Domain） | `ui_qml/qml/pages/ContractPage.qml`（「星域:」「或输入星域名」）← `contract_bridge.py:ContractBridge.pickRegion` / `setRegionQuery` / `refreshRegionLabel` |
| 发布者筛选 | 按发布者名字反查他的合同（三个页签共用） | `ContractPage.qml`（「发布者:」）← `contract_bridge.py:ContractBridge.setIssuerQuery` / `applyFilters` |
| 拉取合同 | 从 ESI 拉合同列表（唯一入口） | `ContractPage.qml`（「拉取合同」）← `contract_bridge.py:ContractBridge.refresh` |
| 补齐全部物品 / 停止 | 手动补齐整个星域的合同物品与发布者名字，可中断 | `ContractPage.qml`（「补齐全部物品」「停止」）← `contract_bridge.py:ContractBridge.startFill` / `stopFill` / `_start_backfill` |
| 进页自动补齐 | 打开合同页时自动补齐**当前列表**缺的物品与发布者（结果落库，可停止） | `contract_bridge.py:ContractBridge.on_shown` / `_start_backfill` |
| 筛选条 | 价格类型、价格区间、只看蓝图合同、剩余至少 N 小时、跳数口径、最低安全 | `ui_qml/qml/pages/ContractTabPane.qml`（「价格:」「只看蓝图合同」「剩余至少:」「跳数口径:」「最低安全:」「应用筛选」）← `contract_bridge.py:ContractBridge.setPriceTypeIndex` / `setPriceMin` / `setPriceMax` / `setBlueprintOnly` / `setMinHoursLeft` / `setJumpModeIndex` / `setMinSecurity` |
| 跳数口径 | 不计算 / 最短路线 / 避开低安 / 自定义安全下限（选了口径才算） | `contract_bridge.py:_JUMP_MODES`；`services/logistics.py:compute_jumps` |
| 拍卖表列 | 物品 / 标题 / 发布者 / 一口价 / 当前出价 / 内容物市价 / 价差 / 价差% / 剩余 / 地点 | `ui_qml/models/contract_models.py`（拍卖列定义）；`contract_bridge.py:ContractBridge.auctionColumns` |
| 物品交换表列 | 物品 / 标题 / 发布者 / 合同价 / 内容物市价 / 价差 / 价差% / 蓝图 / 蓝图市价 / 制造利润 / 剩余 / 地点 | `ui_qml/models/contract_models.py`；`contract_bridge.py:ContractBridge.exchangeColumns` |
| 运输表列 | 发布者 / 起点 / 终点 / 跳数 / 方数 / 报酬 / 抵押 / 每跳 ISK / 每方每跳 ISK / 剩余 | `ui_qml/models/contract_models.py`；`contract_bridge.py:ContractBridge.courierColumns` |
| 表头排序 | 点列头排序（金额列默认降序） | `contract_bridge.py:ContractBridge.sortBy` |
| 合同估值 | 内容物市价与价差；缺价物品单独计数、不当 0 计入；本星域缺价回落 Jita | `services/contract_service.py:list_auction_contracts` / `list_exchange_contracts` / `list_courier_contracts`；`domain/contract_analysis.py` |
| 含蓝图合同 | 蓝图本身按市价 + 按 runs 造出来能赚多少（制造利润） | `domain/contract_analysis.py:blueprint_exchange_metrics` / `manufacturing_profit` |
| 合同物品明细 | 点合同加载物品表：中文名 / 英文名 / 数量 / 蓝图复制品 / 包含 / ME / PE / 剩余流程数 / 单价 / 小计 + 表尾合同价 / 内容物市价 / 价差 | `ui_qml/models/contract_models.py`（物品表列）；`contract_bridge.py:ContractBridge.selectContract` / `_load_items` / `itemColumns` / `itemSortBy` |
| 物品面板文案 | 「合同物品（选中上方合同查看；单价按该星域市价，缺价回落 Jita）」 | `ContractTabPane.qml`；`contract_bridge.py:ContractBridge.itemSummary` |
| 右键动作 | 复制发布者 / 复制物品列表 / 加入关注列表 | `ContractTabPane.qml`（右键菜单）← `contract_bridge.py:ContractBridge.copyIssuer` / `copyItems` / `addItemsToWatchlist` |

---

## 7. 仓库管理（`storage`）

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 两个页签 | 机库管理 / 蓝图管理 | `ui_qml/qml/pages/StoragePage.qml`（`storageTabBar`） |
| 机库切换 | 顶栏机库下拉 | `StoragePage.qml`（「机库:」）← `inventory_bridge.py:InventoryBridge.setHangarIndex` / `hangarNames` |
| 物品表（10 列） | 图标 / 名称 / 库存数量 / 单个成本记录 / 规划占用 / 规划剩余 / 缺口 / 占用资金 / 按卖单总价值 / 估值可信 | `ui_qml/models/inventory_helpers.py:InvTableModel._HEADERS`；列定义 `inventory_bridge.py:InventoryBridge.itemColumns` |
| 表头排序 | 两张表都点列头排序，刷新 / 移库后排序状态保持 | `inventory_bridge.py:InventoryBridge.sortItems` / `sortBlueprints`；`inventory_helpers.py`（`reapply_sort`） |
| 多选 | 多选后批量移动 / 删除 | `StoragePage.qml`（右键「删除 (%1)」「移动到 (%1)」）← `inventory_bridge.py:InventoryBridge.itemsForMenu` / `deleteItems` / `moveItems` |
| 库存修正 | 逐行审阅的修正预览表：导入模式、贸易中心、只看有变更的行、材料倍率、全选/取消全选；右键设置为卖单价/买单价/均价、卖价×倍率、买价×倍率、删除行、来自其他机库、过滤无变化项、搜索匹配物品 | `StoragePage.qml`（「库存修正」）← `inventory_bridge.py:InventoryBridge.runClipboardImport("full")` → `ui_qml/bridge/review_bridge.py:ImportReviewBridge`（`setModeIndex` / `setHubIndex` / `setOnlyChanged` / `setPriceFromMarket` / `applyDiscount` / `deleteRows` / `addFromHangar` / `filterNoChange` / `searchMatch`） |
| 增量粘贴 | 从游戏复制物品（Ctrl+C），按增量累加到当前机库（只增不减） | `StoragePage.qml`（「增量粘贴」+ ToolTip）← `inventory_bridge.py:InventoryBridge.runClipboardImport("incremental")` → `ui_qml/bridge/review_bridge.py:run_clipboard_import`；解析 `services/inventory_clipboard_service.py:parse_clipboard`（Worker 在 `ui_qml/workers/inventory_import_worker.py`） |
| 从钱包交易记录粘贴 | 负 ISK 买入行按记录单价入库当成本 | `StoragePage.qml`（「从钱包交易记录粘贴」+ ToolTip）← `inventory_bridge.py:InventoryBridge.importPurchasesFromClipboard` → `ui_qml/bridge/review_bridge.py:run_purchase_import`；解析 `services/inventory_clipboard_service.py:parse_purchase_clipboard` → `services/wallet_import.py:parse_purchase_records` |
| 查看规划缺失材料 | 按当前计划与库存算缺口 | `StoragePage.qml`（「查看规划缺失材料」）← `inventory_bridge.py:InventoryBridge.openMaterialCoverage` → `ui_qml/bridge/material_coverage_bridge.py` |
| 物品行操作 | 编辑数量、编辑成本价、删除、移动到、复制名称、复制 Type ID | `StoragePage.qml`（物品右键菜单）← `inventory_bridge.py:InventoryBridge.editItemQuantity` / `editItemsCost` / `deleteItems` / `moveItems` / `copyItemNames` / `copyItemTypeIds` |
| 底部合计 | 「按卖单价格: X ISK（N 项市价不可信，Y ISK 未计入）」 | `StoragePage.qml`（`itemTotalText`）← `inventory_bridge.py:InventoryBridge.itemTotalText` |
| 蓝图表（13 列） | 图标 / 名称 / 类型 / 材料等级 / 时间等级 / 产物名称 / 制造时间 / 流程数量 / 材料成本 / 销售收入 / 每流程利润 / 利润率 / 状态 | `ui_qml/models/inventory_helpers.py:BlueprintTableModel._HEADERS`；列定义 `inventory_bridge.py:InventoryBridge.blueprintColumns` |
| 蓝图经济性 | 按材料 / 成品价格来源算每张蓝图的成本、收入、每流程利润与利润率 | `StoragePage.qml`（两个 `FPriceSourceRow`：`label: 材料` / `label: 成品`）← `inventory_bridge.py:InventoryBridge.setPriceSetting` / `refreshEconomics` / `_calc_economics` |
| 蓝图筛选 | 类型 / 科技等级 / 市场分类 / 搜索 | `StoragePage.qml`（「类型:」「科技等级:」「市场分类:」「搜索:」）← `inventory_bridge.py:InventoryBridge.setTypeFilterIndex` / `setTechFilterIndex` / `setMarketFilterIndex` / `setBlueprintSearch` / `applyBlueprintFilter` |
| 蓝图行操作 | 研究分析、删除行、修改所在机库、修改每流程成本、自动填写每流程成本（T2 发明）、修改蓝图等级、修改流程数、复制该格 | `StoragePage.qml`（蓝图右键菜单）← `inventory_bridge.py:InventoryBridge.showResearchAnalysis` / `deleteBlueprints` / `moveBlueprints` / `setBlueprintCostPerRun` / `autoFillCostPerRun` / `editBlueprintLevels` / `editBlueprintRuns` / `copyBlueprintCell` |
| 加入四种规划 | 加入制造业规划 / 加入拷贝规划 / 加入发明规划 / 加入效率研究规划 | `StoragePage.qml`（蓝图右键）← `inventory_bridge.py:InventoryBridge.addToManufacturingPlan` / `addCopyPlan` / `addInventionPlan` / `addResearchPlan` |
| 粘贴导入蓝图 | 从游戏复制蓝图清单批量导入 | `StoragePage.qml`（「粘贴导入蓝图」）← `inventory_bridge.py:InventoryBridge.pasteBlueprints`；`ui_qml/workers/blueprint_import_worker.py` |
| 刷新计算 | 重算估值与状态列 | `StoragePage.qml`（「刷新计算」）← `inventory_bridge.py:InventoryBridge.refreshAll` |
| 加权平均成本 | 多次入库同一物品按加权平均累计；可批量设置成本价 | `services/inventory_manager.py`；批量设置成本价：`inventory_bridge.py:InventoryBridge.editItemsCost` → `ui_qml/bridge/hangar_dialogs.py:BatchCostPriceQmlDialog` |

---

## 8. 横切能力

### 8.1 本地数据与备份

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 四库分离 | 参考 / 行情 / 蓝图 / 用户数据四个 SQLite 文件在 `database/` | `services/database_manager.py:DatabaseManager`；`core/paths.py` |
| 用户数据备份 | 每天自动备份开关、最多保留几份、立即备份、导出用户数据、还原选中备份 | `ui_qml/qml/dialogs/SettingsDialog.qml`（「用户数据备份」「每天自动备份」「最多保留」「立即备份」「导出用户数据…」「还原到」「还原选中备份」）← `ui_qml/bridge/settings_bridge.py:SettingsBridge.setBackupEnabled` / `setBackupKeep` / `backupNow` / `exportNow` / `restoreBackup`；`services/db_backup.py` |
| 价格自动更新 | 开关 + 0~1440 分钟间隔 | `SettingsDialog.qml`（「价格更新」「更新间隔:」「启用自动更新」）← `settings_bridge.py:SettingsBridge`（间隔 / 自动更新字段） |
| 双主题与字号 | 主题卡片点击即切并持久化；全局字号可调 | `SettingsDialog.qml`（「主题」「字体大小」「全局字号:」）← `settings_bridge.py:ThemeSelectorBridge.setCurrentTheme`（卡片点击，内部 `theme.apply_theme`）/ `set_current`（回填选中态）；`ui_qml/theme/registry.py:apply_theme` / `set_font_scale` |
| 数据初始化 / 关于 | 手动触发数据初始化、看关于 | `SettingsDialog.qml`（「数据初始化」「关于」）← `settings_bridge.py:SettingsBridge` |
| 主工具栏 | 区域勾选、价格时效、自动更新开关、「更新价格」（全应用拉取市场价格的入口） | `ui_qml/qml/shell/Main.qml`；`ui_qml/shell_window.py:ShellWindow.request_price_update` |

### 8.2 价格可信度护栏

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 深度取价 | 按挂单量累计取价，跳过凑数薄挂单；阈值受「该侧总量 1%」与「挂单量中位数」双重封顶 | `domain/market_depth.py:depth_price`；常量 `core/constants.py:PRICE_DEPTH_VOLUME_PCT` / `PRICE_DEPTH_MIN_UNITS` / `PRICE_DEPTH_MIN_BOOK` |
| 三态可信判定 | `None` = 没卖价（不参与统计）；`False` = 有卖价但立不住（卖侧过薄且相对买侧不足，或没有买盘）；`True` = 可用 | `domain/market_depth.py:sell_price_reliable`；阈值 `core/constants.py:PRICE_CREDIBLE_MIN_SELL_VOLUME` / `PRICE_CREDIBLE_SELL_BUY_VOLUME_RATIO` |
| 剔出合计 | 不可信的行不进 `market_total`，单独统计 `unreliable_total` | `services/inventory_manager.py:get_total_value`（口径随 `sell_price_reliable`） |
| 界面标注 | 「估值可信」列显示「⚠ 市价不可信」，金额与可信度两列标橙，**数字照显不藏** | `ui_qml/models/inventory_helpers.py:price_credible_text` / `price_unreliable`；着色在 `InvTableModel.data`（ForegroundRole） |
| 合计文案 | 「N 项市价不可信，Y ISK 未计入」 | `ui_qml/bridge/inventory_bridge.py:InventoryBridge.itemTotalText` |
| 资产快照同口径 | 资产快照估值用同一判据 | `services/asset_snapshot_service.py` |
| 回归证据 | 真实盘口回归（卖侧极薄的离群单不得进合计） | `tests/test_inventory_manager.py`、`tests/test_market_depth.py`、`tests/test_qml_storage.py` |

---

## 9. 数据与启动

| 功能 | 用户能拿它干什么 | 代码入口（文件:方法） |
|------|------------------|----------------------|
| 启动顺序 | splash → 启动检查 → 有缺失则数据初始化向导 → 主窗口 | `Main.py:main` / `_StartupHandler.handle`；`ui_qml/workers/startup_worker.py:StartupCheckWorker` |
| 数据初始化步骤 | 数据库结构 / 物品数据 / 价格基础数据 / 工业数据 / 植入体数据 / 结构改装件数据 / 蓝图数据 / SDE 扩展数据（星系·设施）/ 物品图标等 | `services/init_service.py:STEPS` |
| 初始化向导 | 逐项状态、进度、失败重试、非关键步骤跳过、总进度与耗时、后台运行 | `ui_qml/bridge/init_wizard_bridge.py:InitWizardBridge`；`ui_qml/qml/dialogs/InitWizardDialog.qml` |
| 角色绑定（ESI SSO） | 「从 ESI 添加角色」开浏览器授权；「刷新当前角色」静默刷新 | `ui_qml/bridge/char_settings_bridge.py:CharSettingsBridge.importFromEsi`（`force_browser` 区分两条入口）；`ui_qml/workers/esi_skill_worker.py` |
| 人物设置三个 Tab | 技能（可从 ESI 导入等级）/ 增效体三插槽 / 市场费率（经纪人费率·销售税率·改单折扣·最大订单） | `ui_qml/bridge/char_settings_bridge.py:SkillsBridge` / `ImplantsBridge` / `MarketBridge`；`core/char_settings_common.py` |
| 数据来源 | SDE（`sde.jita.space/latest`）与 ESI（`esi.evetech.net/latest`） | `services/importers/sde_loader.py`、`services/importers/getprices.py`、`services/client.py` |
| 打包 | PyInstaller，产物带只读模板库 | `build_release.py`；`Main.py:_run_init_only`（`--init-only` 生成模板库） |
| 热重载开发 | 改 `.py` / `.qml` / `.qss` / `.ui` 自动重启（带防抖） | `dev.py`；`core/hot_reload.py` |
| 界面快照 | 离屏验结构与配色、真窗口验字形；可切某页再拍 | `scripts/shell_snapshot.py:main` |
| 宣传截图（合成数据） | 用 `EVE_DEMO_ROOT` 指向演示根，不碰真实账号数据 | `scripts/capture_readme_shots.py`（配套 `scripts/build_demo_data.py`） |
| 测试分档 | target / fast / validate / ui-retest / full | `scripts/run_tests.sh` |

---

## 10. 代码里有、但当前点不到的功能（**不要写进 README**）

以下功能的实现与对话框都在仓库里，但**当前没有任何界面入口**（全仓搜索确认：
只在测试里被实例化，或只有定义没有调用方）。README 不得把它们当功能宣传。

| 功能 | 现状证据 | 说明 |
|------|----------|------|
| 批量查价（含 CSV 导出） | 对话框 `ui_qml/bridge/batch_price_bridge.py:BatchPriceQmlDialog` 只在 `tests/test_qml_batch_price.py` 实例化；`ui_qml/bridge/query_bridge.py:QueryBridge.openBatchPrice` **无任何调用方**；`QueryPage.qml` 工具栏只有「全物品 / 清空 / 区域」三个控件 | 曾挂在查询页工具栏，现已移除按钮 |
| 全物品**独立窗口**（含制造评分 / 贸易评分 / 设置 / 批量对比 / 导出 / 置顶 / 右键菜单） | 类 `ui_qml/bridge/all_items_bridge.py:AllItemsQmlDialog` 只在 `tests/test_qml_all_items.py` 实例化；查询页只走**内嵌**形态 `QueryBridge.openAllItems`，内嵌态把这些按钮全部隐藏（`AllItemsDialog.qml` 各按钮 `visible: !page.embedded`） | 内嵌态仍可用：分类树、全表、排序、搜索、双击进详情 |
| 批量对比（制造 / 贸易 / 反应三种口径） | `ui_qml/bridge/compare_bridge.py:CompareQmlDialog` / `open_compare_qml_dialog` 只在测试里调用；唯一入口是 `all_items_bridge.py:AllItemsBridge.openCompare`，而它只挂在独立窗的按钮上 | 连带不可达 |
| CSV / Excel 导出（物品表、批量查价、批量对比） | `core/export_helper.py:export_to_csv` / `export_to_excel` 只有两个调用方（`batch_price_bridge.exportCsv`、`all_items_bridge.exportData`），两者都在上面两个不可达对话框里 | 目前**唯一可用的文件导出**是设置页的「导出用户数据…」（`settings_bridge.py:SettingsBridge.exportNow`） |
| 价格走势图对话框 | `ui_qml/bridge/price_chart_bridge.py:PriceChartQmlDialog` 无调用方；查询页没有「走势图」按钮 | `price_chart_bridge` 的几何纯函数仍被 `query_dashboard_bridge` 复用 |
| 物流运费计算（公开货运 / 自有运输的运费与利润） | `services/logistics.py:calc_transport_profit` / `estimate_freight_cost` 无 UI 调用方（`docs/dev/flows.md` 也把它标为「当前无 UI 入口」）；用户可见的只有合同页的跳数与每跳 ISK | 不要写成「物流规划页」 |

---

## 11. 不要写进 README 的说法（原因）

| 说法 | 为什么不能写 |
|------|--------------|
| 「英文界面 / 多语言 / i18n」 | 仓库里没有任何 `.ts` / `.qm` 翻译文件，各页面文案都是中文硬编码。 |
| 「支持多个操作系统」 | 只在 Windows 上运行与验证；发行包是 Windows 可执行文件。README 里只陈述 Windows 环境要求，不列举其它平台。 |
| 「One Dark Pro / One Light 主题」 | 现存主题是 `Fluent 深色` / `Fluent 浅色`（`ui_qml/theme/registry.py:THEME_REGISTRY`，卡片文案取 `name_zh`）。 |
| 「实时行情」 | 价格是本地快照，要手动或定时点「更新价格」；页面显示各中心的价格时间。 |
| 「贸易评分独立页面」 | 贸易评分只有独立窗的评分模式入口，而独立窗不可达（见第 10 节）；不要单列成页面功能。 |
| 「物流规划页 / 运费计算器」 | `services/logistics.py:calc_transport_profit` / `estimate_freight_cost` 无 UI 调用方；可写的只有合同页的跳数与每跳 ISK。 |
| 「完全离线 / 不联网也能用」 | 查询页选中物品会**自动**去 ESI 取订单（`query_detail_bridge.py:QueryDetailBridge.reloadOrders` / `_load_orders`，缓存 TTL 5 分钟）；合同页进入或切页签会**自动**后台补齐（`contract_bridge.py:ContractBridge.on_shown` / `_start_backfill`）。准确说法：数据来自公开 ESI，需要时联网拉取并落本地库，查询/排行/评分都查本地库。 |
| 「EVE 工业助手」（作为程序名） | 程序自称 **EVE 商人助手**（`Main.py:main` 的 `setApplicationName`、发行包名、`LICENSE`）；「EVE 工业助手」只是文档站标题。 |
| 「自动交易 / 自动下单 / 自动启动产线」 | 只读工具：没有任何 ESI 写操作，产线状态是本地账目。 |
| 「云同步 / 多设备 / 账号」 | 没有账号体系，也不上传数据。 |
| 「保证盈利 / 投资建议」 | 大盘与挂单建议页面上都写明「按规则推导，不是预测、也不是投资建议」。 |
| 沿革类叙述（「原先 / 已移除 / 批次 N / 阶段 N」） | README 只描述当前状态，不写项目演变。 |

---

## 12. 文档与代码不一致（供维护参考，不在本次 README 范围）

| 位置 | 不一致 | 建议 |
|------|--------|------|
| `docs/user/query.md` | 说查询页工具栏有「批量查价」「制造配方」按钮、全物品是二级窗口 | 与现状不符（工具栏只剩「全物品 / 清空 / 区域」，全物品是内嵌面板） |
| `docs/user/overview.md` | 导航表只列 5 项（漏「市场监控」「合同市场」），ASCII 图列 6 项；页面 key 仍写 `estimate_view` / `query_view` 等旧命名；主题名写 One Dark Pro / One Light；Hub 只列 4 个 | 补齐 7 项、换成 page key、改主题名、补 Hek |
| `docs/user/industry.md` | 写「19 列」（实际 20 列，含勾选列，见 `ui_qml/models/industry_models.py:PlanTableModel._HEADERS`）；Hub 只列 4 个 —— 注意 `ui_qml/models/plan_qml_model.py` 的类 docstring 自己也写着「19 列」，同样过时，别当依据 | 改成 20 列并说明含勾选列；补 Hek |
| `docs/user/inventory.md` | 写物品表 9 列（实际 10 列：多了「按卖单总价值」「估值可信」之外还有规划占用/剩余/缺口/占用资金）；写「仓库页已迁到 QML（原 `ui_pyside6/`…）」 | 按当前 `_HEADERS` 重写；去掉沿革叙述 |
| `docs/user/pricing.md` | 通篇是 service 级 API 示例；「价格走势图」一节描述的功能没有界面入口 | 改为用户口径或标注未接入 |
| `docs/guide/quickstart.md` | Hub 只列 4 个；主题名写 One Dark Pro / One Light；流程里含「物流运输」 | 与现状对齐 |
| `docs/dev/flows.md` | 标题「贸易评分（无 UI 入口）」**结论是对的**（贸易评分只挂在无生产调用方的独立窗里）；只是没说清「为什么无入口」 | 保留结论，补一句原因：评分模式所在的全物品独立窗没有调用方，内嵌态把评分按钮隐藏了 |
| `docs/dev/feature-inventory.md` 的姊妹问题 | 旧 README 与部分文档把「全物品查询 / 批量对比 / 导出」当功能宣传 | 这三项当前都没有界面入口（见第 10 节） |
| `docs/index.md` | 首页 features 把「物流规划」列为主功能 | 当前无可达入口 |

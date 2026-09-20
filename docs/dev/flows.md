# 功能链路速查

> 把核心功能从 UI 入口到 DB 的完整数据流串起来，回答「这个功能怎么运作」。
> 数据表格式见 [data.md](data.md)、分层与异步模式见 [architecture.md](architecture.md)。
> **本页为手写文档、无自动同步**：改动业务代码后请同步本页。
> 正文只写「模块.函数」不写行号，避免随代码漂移。行号请以 `docs/api/` 为准。

## 制造评分

```
UI（工业页）→ workers/industry_workers.ScoreWorker
  → scoring_service.ScoringService.calc_manufacturing_score（薄委托，签名稳定）
  → scoring_facade.calc_manufacturing_score（编排）
      · db.connect("ref","mkt","bp") 跨库读蓝图/材料/SDE
      · _DbPriceProvider 取价取量（get_price/get_volume/get_system_cost_index）→ domain.scoring
  → domain/scoring.py 纯算法（PriceProvider 注入，无 DB）
  → domain/formulas.py（材料/时长/费用纯公式）
  → ScoringService._cache（TtlLRUCache，按 cache_key 命中）
```

- 数据结构：blueprint.db（`blueprint_products`/`blueprint_activities`/`blueprint_materials`）、reference.db（`item` 名称、`industry_system_costs`、研究成本）、market.db（`market_prices`）
- 入口：`services/scoring_service.py` 的 `ScoringService.calc_manufacturing_score`
- **关键差异**：评分链路取价走 `scoring_service` 模块级 `get_price`（直查 `mkt.market_prices`），**不走 `PricingService`**

## 跨区域价差排行（市场贸易页）

```
贸易页「开始计算」→ ShellWindow.request_price_update([A, B], on_done)
  → workers/main_window_workers.PriceUpdateWorker → importers/getprices.run_price_update
  → 回来后：workers/trade_workers.CrossRegionRankWorker
      · market_browser_service.fetch_cross_region_spread（A/B 两 region JOIN，可选市场分类子树）
      · market_browser_service.fetch_hub_order_change（B 侧挂单量的近日变化，零请求）
  → models/trade_rank_model.TradeRankQmlModel（一个物品一行）
```

- 「开始计算」**先刷新两个中心的价格再算**，刷新走外壳那条单写者通道（`request_price_update`
  串行排队），**不自己起 `PriceUpdateWorker`** —— 两个写者同时动 `market.db` 会撞锁
- ⚠️ `PriceUpdateWorker` 的 `success` 标志**不可信**：`run_price_update` 在拉取失败时
  不抛异常（失败 region 被跳过、旧价保留）。判断「刷新到底生没生效」要回头看
  `fetch_hub_fetch_time`，页面状态栏就是这么标的
- 页面**加载不查库、不拉取**，只有点按钮才动作
- **筛选项在内存里做**（`TradeBridge._apply_filters`）：切筛选项不重算 SQL、不重读库。
  两个开关都是「排除」语义，默认全开：
  - 「只看赚钱的」→ `价差 > 0`
  - 「两侧 ≥ N」→ `min(A侧、B侧对手盘挂单量) ≥ N`。**对手盘挂单量取自 `market_prices`
    的 `buy_volume`/`sell_volume`**（按所选价位取对应那侧）。这一项是必要的：
    `importers/getprices.save_prices` 会把 ESI `/markets/prices/` 的全局均价作为兜底
    混进 `market_prices`，那种行两侧价格看着很高、挂单量却是 0，根本成交不了 ——
    实测全量 11604 行里这类「假价差」占了绝大多数，默认筛选后只剩 312 行
- 购物车（`ui_qml/views/trade_cart_window.py`）存 `data/trade_cart.json`，按方向分组；
  外壳 `ShellWindow.trade_cart()` 持单例，页面与独立窗口共用同一份

## 贸易评分（无 UI 入口）

同制造评分的编排结构，入口为 `ScoringService.calc_trade_score` → `scoring_facade.calc_trade_score`：

- 额外读取：reference.db `item.volume`（体积成本）、`_ss.get_volume`（成交量门槛）
- 参数维度：buy_hub / sell_hub / buy_price_type / sell_price_type / char_config
- 产物：每跳利润估计等，经 `domain/scoring.py` trade 分支
- **当前没有 UI 调用方**：市场贸易页重构成排行表后，原先的「贸易评分」区块已删除。
  链路本身（服务与纯算法）保留未动

## 统一定价

```
UI（财务/运费/精炼/BOM）→ services/pricing_service.py PricingService
  → services/repositories/market_repository.py MarketRepository
  → mkt.market_prices（价格/成交量/adjusted price）· ref.industry_system_costs（SCI）
```

- 数据落库：`services/importers/getprices` 写 `market_prices`/`market_volume_snapshots`；`getindustry` 写 `industry_system_costs`/`industry_facilities`
- **并存约定**：评分链路走 `scoring_service.get_price`，其余 UI 链路走 `PricingService`——两套取价路径同时存在，改价需两边同步

## BOM 递归展开

```
services/bom_expander.py: expand_bom / get_material_tree / get_flat_materials（公共入口）
  → _expand 递归（T2/T3 产业链）
      · _find_blueprint_for_product：bp.blueprint_products JOIN bp.blueprint_activities
      · _get_materials：bp.blueprint_materials
      · calc_material_for_runs：domain/formulas.py
      · 价格：_default_pricing().get_price（PricingService，mkt.market_prices）
```

- UI 无直接调用方；内部查询被 `plan_decompose`、`plan_rebuild` 复用

## 精炼价值

```
估算页 _on_refine → workers/refine_worker → services/refining_service.RefiningService.calc_value
  · filter_refinable：ref.reprocessing_materials（可精炼判定）
  · 产率 calc_refining_yield：core/eve_formulas.py
  · 输入/产出价：PricingService.get_price（mkt.market_prices）
```

## 物流运费（当前无 UI 入口）

```
services/logistics.py
  · estimate_freight_cost / calc_transport_profit
  · get_distance_jumps：TRADE_HUB_DISTANCES 硬编码距离表（含 Hek）
  · 体积：reference.db item.volume
  · 价格：PricingService.get_price
  · 费率常量：core/eve_formulas（经纪人费/销售税）
```

- **市场贸易页的「运输利润」Tab 已删除**（2026-09），这些函数的调用方随之消失；
  服务与纯算法保留，**计划挪到合同市场**（合同页的运输 Tab 目前只算合同报酬口径：
  `domain/contract_analysis.courier_metrics`，没有运费成本与净利润）
- `compute_jumps` 仍被 `services/contract_service.py` 使用

## 生产计划

- 表：user 库 `production_plans` / `plan_blueprint_bindings` / `user_blueprints` / `price_snapshots`
- 仓库：`services/repositories/plan_repository.py`（不存在 `services/plan_repository.py`）
- 保存：`plan_service.insert_plan`；批量导入 `insert_plans_batch`（blueprint 导入走批量）
- 启动：`plan_table._start_plan` → `plan_start_check.plan_start_block`（**纯逻辑、零 DB**；返回 `(类别码, 文案)`，UI 用码选短标签、用文案做 tooltip；`plan_start_block_reason` 是同一次判定的文案投影）→ `plan_execution.check_materials` → `start_plan`（原子 UPDATE status + `inventory_manager.deduct_item`）
- 部分启动：`plan_execution.start_plan_partial(plan_id, lines, ...)` —— 只启动 N 条产线。**时序必须是「先拆行、后启动」**：先 `UPDATE parallels=N` + `insert_split_remainder`（复制结构列、清空执行列、`source_mother_ids` 置 `''`）+ `move_bindings`（把前 N 张之外的绑定**移动**给余量行），**提交后**再 `plan_service.load_plan` 重新取数（漏了这步会按 P 条扣料），最后 `start_plan(auto_bind=False)`（自动绑定走自己的连接立即提交，是回滚看不见的副作用）。失败则 `_rollback_split` 把两行并回一条。仅限**独立计划与子项全部完成的母项**（子项行由需求重放驱动，拆了会被改写）。预览用 `preview_partial_start`（按 N 条口径报缺口）
- 完成：`plan_execution.complete_plan`（成品入 `inventory_items` + `consume_bpc_runs` 消耗 `user_blueprints` + 清 bindings）；撤销 `cancel_plan` 返还材料
- **母项结束时清理已完成的子项行**：`complete_plan` 在**同一事务**内（`deposited` 回写之后、`commit` 之前）调
  `plan_execution.remove_completed_children(group_number, conn=conn)`，返回体带 `removed` 计数供 UI 出文案。
  - **触发条件**：`sub_level==0` 且 `group_number>0`，**且组内没有别的活跃 level-0 行**（部分启动拆出的
    「已启动 / 未启动」两半必须都结束，否则仍在跑的那半会失去子项制造价口径）。
  - **子项自身完成不删自己**：母项的「市场」口径三列（材料成本/利润/市场利润率）靠同组子项行
    （`plan_metrics.mother_subitem_cost_map` + `adjust_mother_metrics`）才能按子项制造价计；删早了会在
    混合态下回退市场价。**入库成本不受影响**——子项下线时产出已按其自身成本入库，母项启动与下线都按库存成本核算。
  - **清理判据是「已无归属」且全局扫**：有 `source_mother_ids` 的行要等引用它的母项**全部**结束才删
    （跨组共享件靠这条兜住，只按组过滤会留永久孤儿）；没有来源记录的行只在触发组内清。
  - ⚠️ **绑定清理由传入的 `conn` 完成，不得调 `release_blueprint`** —— 后者自开另一条缓存连接并独立提交，
    在外层未提交写事务内会 WAL 写锁自锁（卡满 `busy_timeout` 后 `database is locked`），且破坏「清理与置
    completed 同生共死」的原子性。
  - 删母项（右键「删除产线」，`plan_table._delete_rows`）时也调同一函数，否则已完成的子项行会成为永远清不掉的
    孤儿（`plan_rebuild` 的 prune 分支显式豁免 `_DONE_STATUSES`）。
- 展开：`plan_table._decompose_parent` → `plan_decompose.decompose_plan`（递归读 `user_blueprints` + bom 材料）→ `plan_rebuild.rebuild_children` → `PlanRepository` 增删改
- **需求传播**（`plan_rebuild.compute_child_forest`）：每轮**先把需求累齐 → 再定稿 runs → 最后才拿 runs 展开下一级**，
  且每个节点每轮只展开一次；迭代到所有节点 runs 不再变（`_MAX_ROUNDS=10`）为止，跨层共享 2-3 轮收敛。
  两条铁律，违反哪条都会静默算错（都不报错，只是数字不对）：
  - **别在累需求过程中折算 runs**：共享中间件会被每个母项各展开一遍，下级 demand 翻倍（实测 60 算成 80）。
  - **别用短路写递归**（`changed = changed or _propagate(...)`）：本节点 runs 有变化时就不往下走了，
    而「正在变」恰是最该往下走的时候。多母项共享中间件时每轮都在变，level≥2 永远进不了 `nodes`；
    `prune` 又按「type 不在 nodes 里」判孤儿，会把已存在的孙项行删掉（先单母项拆解出孙项、再加第二个母项、重算子项 → 孙项消失）。
    回归防线：`tests/test_plan_rebuild.py::test_shared_intermediate_expands_to_its_own_children`
    与 `::test_prune_keeps_grandchildren_when_a_second_mother_shows_up`。
- 读取：`plan_service.load_plans`；价格快照 `save_price_snapshots`
- **计划表的派生视图要缓存**（`industry_models.PlanTableModel._view_cache`）：可见行、行号映射、
  「有子项的组」都是 O(行数)，却被 `data()` 按「列 × 角色」**逐格**调用 —— 实测 50 行、折叠两个组时
  全表刷一遍 485ms（不折叠 58ms），QML 滚动每帧都要取角色，于是「几十行就开始卡」。
  缓存按签名 `(id(列表), 行数, 折叠快照)` 失效，`beginResetModel` 另有兜底清空。
  ⚠️ 改这几个方法时别退回「每格重扫全表」，回归防线：
  `tests/test_qml_plan_model.py::test_cell_reads_do_not_rescan_the_whole_table`
  （断言的是**调用次数**而不是耗时 —— 耗时断言在 CI 上会飘）。
- 旁路：`plan_aggregator` 是**采购/需求聚合**，不是计划展开
- 价格口径（工具栏双行价格设置）：`mat_hub/mat_price_type/mat_mult` 与 `prod_hub/prod_price_type/prod_mult` 由 `top_toolbar.get_price_settings()` 提供，消费方必须**整套一起透传**（漏一项就是「改设置数字不动」的缺陷）：
  - 计划成本/利润：`BatchPlanCalcWorker`（表格批量重算）、`industry_view._on_plan_add`、`plan_table._view_cost_breakdown` → 成本明细弹窗、`parent_decompose_dialog`、`blueprint_tab` 的「加入制造规划」预览 → `ScoringService.calculate_plan_metrics(mat_mult=, prod_mult=)` → `scoring_facade.calc_manufacturing_score` → `domain.scoring`
  - ⚠️ `scoring_facade` 有 TTL 缓存，`mat_price_mult/prod_price_mult` **必须进 cache_key**，否则同一类陈旧缓存缺陷会在评分层复现
  - 倍率只作用于玩家买卖价：材料价乘 `mat_mult`、成品价乘 `prod_mult`；**EIV 用的 adjusted_price 不乘**（CCP 官方估价，与买卖价无关）
  - 状态栏「备料中采购」：`industry_view._refresh_procurement_summary` → `ProcurementSummaryWorker(region_id, price_type, price_mult, self_made)` → `ui_data_service.aggregate_procurement_summary` → `plan_aggregator.aggregate_procurement`。该函数带指纹缓存，指纹 = **（价格口径, 自制件集合, 计划字段集）**，任一漏进指纹就会回吐旧值
  - ⚠️ **自制件集合必须按「全量计划」算**（`plan_aggregator.self_made_type_ids`，由调用方传成 `self_made=`）：
    两个调用方都会把计划筛成 `materials_ready && pending`（ready/running 的材料已扣库存，计入会虚高），
    而子项产线**往往正在生产中** —— 拿筛过的那份现算，子线就「不存在」了，它的产物被当成没有子线、
    重复计成待采购。用户报的「电磁发生器已在生产，采购却仍报缺 2504」就是这么来的
    （母项待生产、子线生产中）。实测同一份数据：按筛过的算 19 行 / 55,739,040 ISK，按全量算 18 行 / 0。
    回归防线：`tests/test_plan_aggregator.py::TestSelfMadeComponents` 与
    `tests/test_procurement_tab.py::test_recalculate_excludes_running_sublines`。
    同一模块的 `collect_direct_materials` 用的是「全部活跃计划」查询，天然没这个问题。
  - 口径分叉（有意）：采购小助手 `procurement_tab` 有自己独立的 Hub/价格类型控件、无倍率控件，不套用工具栏倍率
  - 「买卖差价」列：`plan_aggregator._spread` = `(sell_price - buy_price) × 需采购量` —— **金额**，与「总价」同阶
    （原来给的是单价差，读着像单价、和旁边 `数量 × 单价` 的总价对不上，用户报过）。**不吃 `price_mult`**
    （倍率是跨区运费/溢价的模拟，价差是市场事实本身）。**单边无挂单 → `None`**，显示 `-`、复制给空串 ——
    给 0 会被读成「卖买同价」。`get_market_prices` 本来就同时返回 sell/buy，这一列不额外查库。
  - 采购表当前 5 列：物品名称 / 总需求 / 需采购 / 买卖差价 / 总价。「库存」「单价」「体积」已从**显示**下线
    （列表太宽装不下），数据仍在行里（`owned`/`price`/`volume`）—— 汇总行、复制整单、增量添加都还在用。
  - ⚠️ 列**四处按索引对齐**：`procurement_bridge._HEADERS` / `_SORT_FIELDS` / `_COPY_FIELDS` /
    `procure_rows` 的 cells。加列必须四处一起插，插错位是「排序按这列、复制按那列」的静默串列
    （回归防线：`tests/test_procurement_tab.py::test_column_lists_stay_index_aligned`）。
    QML 侧的 `allColumns` 从 `columns` 长度推，不要写死下标数组。
  - ⚠️ 窗口宽度按**工具栏那一行**定，不是按表格：`FSummaryTable.colWidth` 给弹性列的下限是 80px，
    且**不会**为了塞下而挤固定列 —— 固定列一多总宽就超出窗口、右侧列被裁（「首次打开显示不全」）。
    按 `Σ(列宽+cellPadding 12) + 12 + 80` 估表格，再量工具栏那行的 `implicitWidth`（实测 ~753px），
    两者取大。护栏：`test_procurement_tab.py::test_table_stays_narrow_enough_to_fit_the_window`。
- **工具窗的置顶要在显示/前置时重申**（`pin_utils.reassert_pin`，采购小助手与产线启动小助手共用）：
  `apply_window_pin` 在**构造时**就跑过一次，那一刻窗口还没显示；而 `QWindow.raise_()` 在 Windows 上是
  `SetWindowPos(HWND_TOP)` —— 不带 `HWND_TOPMOST` 的插入位置。两者都可能让置顶在用户真正看到窗口之前丢掉，
  表现是「勾着置顶却没置顶，再点一次才好」。所以 `window_visibility_changed(True)` 与置顶态下的 `raise_()`
  都重申一次（幂等、一次 Win32 调用）。
- **启动成本快照**（`production_plans.material_cost_snapshot`，schema v12→v13）：`start_plan` 在**扣减之前、事务之外**采样机库加权单价，写入 `{"total": 总成本, "unit": {type_id: 单价}}`：
  - 两个「之前」都是硬约束 —— `deduct_item` 把余量清到 0 会删行（扣完再取价得 0）；`db.connect()` 同线程复用连接、嵌套 with 退出会提前 commit（在事务内取价会毁掉「失败整体回滚」）
  - `complete_plan` 按快照 `total` 算成品入库单价；`cancel_plan` 按快照 `unit` 返还成本 —— 都是**启动那一刻**的口径，不受在产期间价格重算影响
  - 旧计划无快照 → 回退 `material_cost` / 机库当前加权成本（向后兼容）；`cancel_plan` 与 `reset_plan_for_reuse` 会清空快照
- **重算失败不得清零成本**：`BatchPlanCalcWorker` 对「评分异常→空 dict」与 `no_price`/`no_blueprint`/`no_materials`（`calculate_plan_metrics` 对这三种 status 返回全零 dict）的行**跳过不发**，保留库中上次的正确值；父项若同组有更深的失败子项也一并跳过（否则 `mother_subitem_cost_map` 拿空 dict 会把母项成本算低）。跳过数量经 `failed_names` 由状态栏提示「N 条计划估值失败，成本沿用上次值」
- **完成入口统一**：右键「下线」与状态列「待下线」都走 `CompletePlansDialog` 选产出机库（批量只弹一次框）；`deposit_hangar_id` 为空时不再静默跳过入库
- **「删除产线」语义**（菜单曾名「取消生产」「删除行」）：解除蓝图绑定 + 删除本行**及其连带的子项**，
  **不返还已扣材料、不动库存行** —— 与游戏「取消产线只退蓝图」一致（领域模型见 `AUDIT-20260801.md`）。
  - 删母项 → 子项走 `rebuild_children(prune=True)` 的**需求式**收缩（仍被别的活跃母项引用的共享件保留）；
    删子项 → 走 `plan_decompose.collect_removed_child_ids` 的血缘式**同组子孙**连坐
    （与「母项拆解」预览里移除组件是同一条语义，两处共用一个函数）。
  - 连坐在产（`in_progress`/`running`）的子项**不删**（`plan_rebuild._is_locked` 的既有口径：已投产产线不砍），
    确认框里会带出「N 条在产子项不会删除」。
  - 误点启动请用「撤销启动（返还材料）」；删除前有确认框按状态说明后果。
  - 菜单里**没有**「设置蓝图等级」「查看蓝图原图的 NPC 卖家」「产线启动小助手」：
    蓝图等级统一由库存蓝图带出（不再有计划级的手填等级），NPC 卖家仍在蓝图选择弹窗里，
    小助手在工业页底部状态栏已有按钮。
- **蓝图流程不足可强制启动**：`_binding_shortfall` 有两道（张数 / 每张流程 ≥ runs），
  `start_plan` 与 `complete_plan` **成对**提供 `allow_bp_short` —— **只放开启动会造成死锁**
  （强制启动的计划永远无法下线）。强制时**不换绑**，完成时 `consume_bpc_runs` 按实际可用量消耗；
  账面偏差由用户在蓝图管理做**全量剪贴板导入**矫正。
  - **五条下线入口都要覆盖**：计划表格状态列（单行）、计划表格右键（批量）、采购页「一键完成」、
    工业页底部状态栏「全部下线」、产线启动小助手行内「可下线」（单行）。
    **单行**下线共用 `ui_qml/views/industry/complete_plans_dialog.py::complete_one_plan`
    （返回 None = 用户取消或已弹过失败告警，**非 None 即成功**——调用方据此决定要不要把行标成已完成）；
    预检与放行**必须共用** `ui_qml/bridge/complete_guard.py::confirm_bp_shortfall`。
    状态栏那条曾漏传 `allow_bp_short`，强制启动过的计划在该入口永远下不了线，且失败原因被
    `complete_plans` 吞成一句「失败 N 项」（现已随 `failed_reasons` 带出）。确认框留 UI 层：
    `complete_plans()` 是无 parent 的服务函数，validate 档会在无 QApplication 下直调它。
  - **原图（`is_bpo=1`）不受该限制**：`_bp_available_runs` 视为无限流程，既不触发「不足」确认，
    下线时也**永不消耗、永不删除**（`complete_plan` 与 `consume_bpc_runs` 各有独立防线）。
    不变量是 **`is_bpo=1` ⇒ `runs=0`**，由 v15→v16 迁移与剪贴板解析两侧同口径维护
    （见 `domain/blueprint_sync.py`）。
- **并行产线逐线计算**：各线按**各自绑定蓝图**的 ME/TE 独立结算
  - 等级来源：`plan_service._enrich_rows` 预填 `line_levels`（`user_blueprints.me_level/te_level`，
    绑定来源与 `bound_blueprint_ids` 同一回退：关联表优先 → `assigned_blueprint_id`）；
    未绑的线取**已绑里最差那张**（`min(me)` 与 `min(te)` 分别取）；一张没绑则留空
  - 短路：`line_levels` 为空、或**与计划级 (me,te) 完全一致** → 走原单次路径（零行为变化）。
    ⚠️ 短路条件不能写成「各线彼此一致」—— 五张都绑 ME8 而计划级写 10 时仍须走逐线
  - 汇总（`ScoringService.combine_per_line`）：材料/作业费/收入/利润 **Σ**；
    **时长取 max**（并行同时跑，单次路径的 `hours_per_run × runs` 是其均匀特例）；
    日产出 Σ(24/hoursᵢ)；利润率 = Σ利润/Σ总成本（与单线同式）
  - ⚠️ **`materials[].qty` 保持「单线单轮」语义**（逐线时取最差线）：`plan_metrics` 两处消费方
    都会再乘 `runs × parallels`，放汇总值会被**重复放大**。
    要求精确的消费方改读同条目的 **`total_qty`**（整批取整量，见下）或 `materials_all_lines`
  - **取整口径（2026-09-16 统一）**：材料需求按**整批**取一次整，不是逐轮取整后乘轮数 ——
    后者对基础量 ≥2 的材料系统性多要货（基础量 22、ME10、2510 次作业：49,698 对 50,200）。
    单一定义处是 `domain/formulas.material_total_for_runs`，成本 / 扣料 / 判定三处都走它。
    每条材料另带 `total_qty`（由 `calculate_total_metrics` / `combine_per_line` 算好；
    逐线时**各线各自整批再求和**，因为每条并行线在 EVE 里是独立作业、各带自己的 ME）。
    `material_requirements` 与 `plan_metrics` 优先读 `total_qty`，缺失时才回退旧乘法
  - ⚠️ 材料成本口径变了，**利润/利润率/ISK-h 必须一起重算**：`profit_per_run` 里含的是
    单轮材料成本，所以用**增量式**（`total_profit = profit_per_run × 倍数 + 材料省下的部分`）
    而不是自己拼 `total_cost = 材料 + 费用` —— `fees_per_run` 里**没有** `research_cost`
    （它在 `domain/scoring.py` 才加进 total_cost），拼出来会让 T2/T3 计划的利润虚高
  - 展示：表格 ME/TE 列一致时不变；不一致时显示**最低那组** + `≠`，tooltip 逐条列出

## 科研计划（拷贝 / 发明 / ME-TE 研究）

`production_plans.activity` 把「制造计划」泛化为「工业计划」；活动契约的唯一真源是
`services/plan_job_kinds.py`（输入蓝图规则 / 产出口径 / 提示文案）。**所有消费方必须经它判定**，
不得硬编码 `activity='manufacturing'`。

```
入口（手动加入，母项拆解不生成科研产线）
  蓝图库右键 / 全物品页右键
    → services/research_plans.create_research_plan（单次 INSERT，含科研专属列）
      · 拷贝 CopyPlanDialog      份数 + 每份流程（≤ 蓝图 copying 的 max_production_limit）
      · 发明 InventionPlanDialog 产物（多产物下拉）+ 解码器 + 预期成功率 + 每线尝试次数 × 并行数
      · 研究 ResearchPlanDialog  ME/TE + 目标等级

评分（按行 activity 分派）
  ScoringService.calculate_plan_metrics
    · manufacturing → scoring_facade（现状路径，零改动）
    · copying/invention/researching_* → ScoringService._calculate_research_metrics
        → services/plan_metrics.invention_plan_cost / copying_plan_cost / research_plan_cost
        → domain/research.py（成功率 / 解码器表 / BPC 产出 / 科学作业时长）

执行
  启动：plan_start_check.plan_start_block(blueprint_ready=plan_execution.plan_blueprint_ready)
        · 拷贝/研究要 BPO；发明要够流程的 BPC（不能用 BPO）
  完成：plan_execution.complete_plan 按 output_kind 分派
        · copying            → 产出 BPC 入 user_blueprints（不消耗原图流程）
        · invention          → **必须回填 actual_output_runs**；否则返回 code='need_outcome'
                               拒绝静默完成 → 工业页弹 InventionOutcomeDialog
                               （默认值 = 期望流程；「发明失败」按钮置 0）
        · researching_*      → 只完成作业（等级仍由用户手动维护）
  消耗：发明每次尝试扣输入 T1 BPC 的 1 个流程；拷贝/研究不扣
```

**语义契约**（`product_type_id` 恒为「本计划的产物」）：制造=物品、拷贝/研究=被操作的蓝图、
发明=产出的 T2/T3 蓝图。科研行的产物**不在** `blueprint_products.activity='manufacturing'` 里，
所以 `plan_aggregator` 对科研行整行跳过蓝图采购，材料（数据核心/解码器）走
`plan_execution.material_requirements` 的科研分支（材料量已按作业次数算好，**不再乘 runs×parallels**）。

**已知陷阱**（改这块前先看）：
- `plan_execution.plan_blueprint_ready` 取代旧 `has_image` 口径；`has_image` 对科研行恒 False。
- 研发活动的表名不一致：`blueprint_activities` 用 `researching_material_efficiency`，
  而 `blueprint_materials` 用 `research_material`（映射见 `plan_job_kinds.material_activity`）。
- 发明时长/产出上限在**输入 T1 蓝图**上，不在产物那张蓝图。
- 发明产出的 BPC 基础流程数 = `blueprint_products.quantity`（invention 行）= SDE 的
  授权流程数，取值 1/3/5/10/20。旧口径 `min(T1 拷贝上限, T2 制造上限)` 已废弃
  （228/1349 条路径不符，216 条 T3 古文物路径错给 300）。

## 库存管理

- 表：user 库 `hangars` / `inventory_items` / `user_blueprints`
- UI 同步调用（无独立 worker）：`inventory_manager.add_item`（加权平均成本）、`set_item_quantity`（经 `inventory_import.compute_import_diff` 全量覆盖/删除）、`move_items`（右键「移动到机库」）
- `deduct_item` 被计划启动/展开/重建调用
- 剪贴板导入按仓库类型校验（同一机库分两张表、两页签）：材料侧 `inventory_clipboard_service.parse_clipboard`（机库管理「库存修正/增量粘贴」、采购页「增量添加到仓库」）过滤蓝图行；`parse_purchase_clipboard`（机库管理 / 采购页「从剪贴板导入」）吃「钱包 → 交易记录」的买入行、不过滤蓝图；蓝图侧 `ui_data_service.parse_blueprint_clipboard`（蓝图管理「粘贴导入蓝图」）过滤材料行。判定见 `services/item_kind.py`（`item` group 名后缀 = 蓝图，失败开放），过滤数在预览框统计栏提示
  - 蓝图侧解析**同时接受 `manufacturing` 与 `reaction`**：反应公式是蓝图仓库的正式成员，
    只认 manufacturing 会让它们在剪贴板里解析不出、进而被「全量同步」当成库中冗余删除。
    结构完整却认不出蓝图的行计入「未识别」计数并在预览框提示（不再无声消失）。
  - **匹配键是 `(蓝图类型, is_bpo, ME, TE)`，不含流程数**：流程数是行内属性，进了键就会让
    「同一张图流程数变了」（BPC 被消耗、原图归一）退化成删旧行 + 插新行，连带丢掉行 `id`、
    `notes`，并经 `delete_blueprint` 静默解除活跃计划的绑定。配对与增删规则见
    `domain/blueprint_sync.py::plan_group_sync`（先取流程数相同的份额 → 幂等）。
  - **张数按 `SUM(quantity)` 而非行数计**：下线产出会把同规格 BPC 合并成 `quantity>1` 的一行，
    按行数计会让全量同步误判「库里少」而多插行。
  - **全量同步的删除是危险动作，三重保护**：预览框纯删除行**默认不勾选**、确认前弹删除清单、
    被活跃计划占用的行**硬阻断**（`get_occupied_blueprint_ids`，跳过数经 `blocked` 回报）。
    「最终」列只接受非负整数，非法值标红并拦下确认。

## 物品查询页

两态：**未选物品** = 仪表盘（产线详情 / 资产折线图 / 挂单列表）；**已选物品** = 详情面板（5 中心价格 / 订单 / 精炼 / 制造材料）。
**没有结果表格** —— 候选弹窗就是匹配清单，点一条直接出详情（用户明确要求；`ui_qml/models/query_model(s).py` 已随之删除）。

```
候选：QueryPage 输入框 → QueryBridge.onTextChanged（200ms 防抖）
  → ui_qml.workers.query_workers.SuggestionWorker → query_suggest_items
  → QueryBridge._on_suggestions → suggestionsChanged → 弹窗显式 open()
选中：QueryBridge.pickSuggestion（候选项带 type_id）→ QueryDetailBridge.setItem
  历史项是**裸查询词**、没有 type_id → 填回输入框 + 重新拉候选，由用户挑
两态判据：QML 的 workArea.idle = !(detail.typeId > 0)，且**不带 busy**
```

- 子桥**懒建**：`QueryBridge._get_detail` / `_get_dashboard` 首次被 QML 读到才 import 并构造（`query_detail_bridge` / `query_dashboard_bridge`）；导入失败返回 `None`，QML 按 `detail === null` 写占位，**不连累整页**（外壳只把该面板记为暂缺）
- 详情面板四块（`QueryDetailBridge`）：① 价格 `market_repo.get_batch_market_snapshot`（每 hub 一次）；② 订单 `workers/order_workers.OrderFetchWorker` + `order_popup_bridge.order_rows`（订单弹窗已删，这个纯函数只剩详情面板一个调用方），缓存 `order_workers.order_cache` 由 `QueryDetailBridge._on_orders_fetched` 写入；③ 精炼 `workers/refine_worker.RefineWorker`（产率按**所选人物**的提炼技能算，人物与数量/站点都是面板上的输入）；④ 制造材料 `bom_expander.get_flat_materials`（买/卖各展开一次）。几何/文案在 `ui_qml/models/query_detail_model.py` 纯函数里
- 候选口径：`services/ui_data_service.query_suggest_items` 只做**前缀**匹配（Type ID 全等，或名字 `LIKE 'x%'`），并排除无用类别 `_JUNK_CATEGORY_IDS`（`category_id=11` 那类 0 价 0 蓝图的遗留条目，也是候选里「两条一模一样的 `♦ 毒蜥级`」的来源）；**不设条数上限**。原先「查询串命中类别名 → 返回整个类别」的兜底、名字子串匹配、以及按名字跑整表搜索的 `query_search_items*` 都已删除
- 站名解析：`order_workers.OrderFetchWorker._resolve_names` **先查本地 SDE `reference.db.station`**（复用 `services.npc_seller.resolve_stations_by_ids`），只有本地没有的玩家建筑才打 ESI `/universe/names/`；解析失败**不写缓存**（写进去会让该 location 永久显示编号）

空闲态三条线（`QueryDashboardBridge`）：
- **产线详情**：`occupancyByChar`（**每人物一块，块内制造/科研/反应各一行**；行尾给「待下线 N」= 该人物该线型 `status=='ready'` 的计划数，与「空 N」= 剩余产线）← `_refresh_occupancy` + `_build_occupancy_by_char` + `_ready_count_by_char_line` ← `services.char_capacity.active_lines_by_category` + `max_lines_for_category` + `capacity_line_for_category`。同一算法另出 `occupancyRows`（按人物，与 `LauncherBridge.occupancyRows` 逐字同形状）。（仪表盘原有的「快捷操作（可启动 / 可下线）」列表已按用户要求删除 —— 启动/下线在**生产计划表**与**产线启动小助手**里都有）
- **资产折线图**：`assetPlot` / `assetSeries` / `assetSummaryRows` ← `_refresh_snapshots` → `services.asset_snapshot_service.load_series` → `query_dashboard_bridge.asset_plot`（几何复用 `ui_qml.bridge.price_chart_bridge` 的 `nice_range`/`axis_values`/`map_values`/`pick_indices`）；区间档位 `range_window` + `trim_from`。**5 条线**取数来源见 `services/asset_snapshot_service` 模块 docstring（inventory / orders / line_value / wallet / total）。面板右上角「刷新」→ `reloadAssets`（**强制**重读，绕开指纹）
- **挂单列表**：`buyOrderRows` / `sellOrderRows`（**买单、卖单各一张表**，各带笔数）← `_ensure_orders` ← `user.db.open_orders`

挂单导入（`QueryDashboardBridge.readOrders`）：

```
services.order_export.find_latest_export(None)   ← 目录固定游戏默认（%USERPROFILE%\Documents\EVE\logs\Marketlogs；文件名含 order/订单）
  → services.order_export.read_export_text（utf-8-sig → utf-16 → gbk 逐档）
  → services.order_export.parse_order_export（表头驱动 CSV，退化启发式；不抛异常）
  → QueryDashboardBridge._fill_location_names → services.npc_seller.resolve_stations_by_ids（补中文站名）
  → QueryDashboardBridge._fill_type_names → ref.item（补中文物品名；真实导出**无物品名列**）
  → _snapshot_orders（写库**之前**的挂单快照 = before）
  → QueryDashboardBridge._write_orders → INSERT OR REPLACE INTO open_orders（order_id 主键 → 幂等）
  → classify_order_changes(before, records)（**纯函数**：消失 → gone、剩余量变少 → partial；新增不算变动）
  → _review_changes（有变动才弹「订单变动」确认框）→ _apply_outcomes（钱包增减 / 台账 / 删行或回写剩余量）
  → QueryDashboardBridge._record_snapshot → services.asset_snapshot_service.record_snapshot
```

订单变动确认（`ui_qml/bridge/order_change_bridge.py` + `ui_qml/qml/dialogs/OrderChangeDialog.qml`）：
每条变动逐条选「买到了 / 卖完了」（默认，计入钱包）或「手动撤销」（不动钱包）。`_apply_outcomes` 四步：
① `DELETE`（整笔消失）或 `UPDATE volume_remain`（部分成交）；② 落 `order_events` 台账（只记录，不参与计算）；
③ `asset_snapshot_service.adjust_wallet_balance` 增减余额（卖 **+** 价格×减少量、买 **−**，**不扣税费**，用户确认口径）；
④ 清 `_pending_changes` + 重记快照。用户点「取消」→ 什么都不做，变动留在 `_pending_changes` 里下次导入重新提示。

- 钱包余额**手填**：`QueryDashboardBridge.setWalletText` → `asset_snapshot_service.set_wallet_balance`（settings.json `wallet_balance`）+ `record_snapshot`；订单变动也走同一个键（`adjust_wallet_balance`）。**导出目录固定为游戏默认目录** —— 面板上的自定义目录输入框与 `settings.json` 的 `order_export_dir` 键已按用户要求退场
- 表：user 库 `asset_snapshots`（含 `line_value`）/ `open_orders` / `order_events`，schema 迁移 v16→v17 建前两张表、**v17→v18** 加 `line_value` 列并建 `order_events`（`services.schema_migrations._USER_V17_TABLES_SQL` / `_ORDER_EVENTS_SQL` / `_migrate_user_v16_to_v17` / `_migrate_user_v17_to_v18`）；服务入口另有 `CREATE TABLE IF NOT EXISTS` 兜底（测试 / 新库）
- 日期口径：快照日期一律由 **SQLite 侧** `date('now','localtime')` 决定（`asset_snapshots.snap_date` 唯一，当天重复记录覆盖不累积），不混用 Python 的 `date.today()`
- 刷新：`QueryDashboardBridge.refresh` **幂等且便宜** —— 先算「计划字段 + 机库库存 + 角色技能 + 快照/挂单行数 + 本桥本地状态」指纹，没变就直接返回（不重算、不发 `changed`）。由 QML 的空闲态可见性驱动（可见即刷一次 + 60s 定时器），桥**不自建定时器**；折线图右上角的「刷新」按钮走 `reloadAssets`（强制）

**已知陷阱**（改这块前先看）：
- **QML 没有 `int()`**：JS 全局只有 `Number` / `parseInt` / `Math.*`。写 `int(x)` 会让整条绑定抛 `ReferenceError`，而 QML 对绑定错误**静默**（属性停在默认值）—— 实测容量条一个槽位都画不出来，只剩一条空轨道。
- **面板容器用 `FPanel` 不用 `FSection`**：`FSection` 把子项收进内层 `ColumnLayout`，在里面写 `anchors.fill: parent` 会被布局**静默忽略**、子项塌成 `implicitHeight`（实测整张表只剩表头）。要放「自己管布局的一整块」（表格 / 图表 / 占用条）用 `FPanel`，只放若干行依次排列的控件才用 `FSection`。
- **两态判据**取桥上的 Property：`workArea.idle = !(detail.typeId > 0)`（`QueryDetailBridge.typeId`，`notify=changed`）—— 绑定追得到，不像 Slot 调用那样要自己补发通知。判据里**不能带 `busy`**：那是「按候选查明细」的中间态，掺进来会让界面在仪表盘与详情之间来回翻两次。
- **订单导出文件的真实格式**（详见 `services/order_export.py` 模块 docstring）：UTF-8 **带 BOM**、文件名是**中文**的（`个人订单-…` / `军团订单-…`）、`volRemaining` 是**浮点串**、位置名包在 `<localized hint="英文">中文</localized>` 里、**没有物品名列**。
- **在途取数线程必须在页面销毁时停**：`QueryBridge.shutdown`（+ QML `Component.onDestruction`）会停 `_detail_bridge` / `_dash_bridge`，`QueryDetailBridge.shutdown` 收 `_order_worker` / `_refine_worker`（订单走 ESI，超时 30 秒）。不停的话 Qt 会在退出时析构一个**还在跑**的 `QThread` → **进程退出崩，且输出里连一行 traceback 都没有**。⚠️ `QueryBridge.shutdown` **不能读 `self.detail` / `self.dashboard`** —— 那两个 getter 会把没用过的子桥无谓地建出来（连带 import 整条业务链）。

## 数据初始化（SDE/ESI）

```
初始向导 → init_service.InitService.start → _run_sequence（asyncio 并行步骤）
  → 动态加载 importers：
     getitems → ref.item / market_tree
     getprices → mkt.market_prices / market_volume_snapshots
     getblueprints → bp.* 四表
     getindustry → ref.industry_system_costs / industry_facilities
     sde_loader → ref.category / station / solar_system / reprocessing_materials 等
     geticon → PNG 图标缓存
就绪判定：init_check.check_all（各 check_* 数行数）
```

## 角色配置

- 无 DB，读写 `data/char_config.json`：`char_config_validator.load_char_config` / `migrate_char_config`
- 解析：`char_config_resolver.resolve_char_config`（优先级 skills > char_data > char_name → get_character）
- 消费方：`plan_service.calculate_plan_metrics`、`scoring_service`、industry workers
- `char_capacity` 读技能计算产线数（读 `production_plans` 状态）

## 数据库层

- `database_manager.py`：`connect(primary, *attach)` 用 SQLite `ATTACH` 联合 4 库（ref/mkt/usr/bp），每库 WAL
- 迁移：`schema_migrations.ensure_schema`（逐版本走 `_MIGRATIONS`，先备份到 `database/backups/`）；`ensure_all_schemas` 循环做全库
- 入口：`startup_worker`（Main.py 启动）、`init_service`。规范见 [schema-migration.md](schema-migration.md)

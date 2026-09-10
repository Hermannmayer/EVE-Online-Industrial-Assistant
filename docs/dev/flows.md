# 功能链路速查

> 把核心功能从 UI 入口到 DB 的完整数据流串起来，回答「这个功能怎么运作」。
> 数据表格式见 [data.md](data.md)、分层与异步模式见 [architecture.md](architecture.md)。
> **本页为手写文档、无自动同步**：改动业务代码后请同步本页（`scripts/check_docs_stale.py` 在改代码时会提醒）。
> 正文只写「模块.函数」不写行号，避免随代码漂移。行号请以 `docs/api/` 为准。

## 制造评分

```
UI（工业/贸易页）→ workers/industry_workers.ScoreWorker、trade_workers.TradeScoreWorker
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

## 贸易评分

同制造评分的编排结构，入口为 `ScoringService.calc_trade_score` → `scoring_facade.calc_trade_score`：

- 额外读取：reference.db `item.volume`（体积成本）、`_ss.get_volume`（成交量门槛）
- 参数维度：buy_hub / sell_hub / buy_price_type / sell_price_type / char_config
- 产物：每跳利润估计等，经 `domain/scoring.py` trade 分支

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

## 物流运费

```
贸易页 → workers/trade_workers.TransportWorker → services/logistics.py
  · estimate_freight_cost / calc_transport_profit
  · get_distance_jumps：TRADE_HUB_DISTANCES 硬编码距离表（含 Hek）
  · 体积：reference.db item.volume
  · 价格：PricingService.get_price
  · 费率常量：core/eve_formulas（经纪人费/销售税）
```

## 生产计划

- 表：user 库 `production_plans` / `plan_blueprint_bindings` / `user_blueprints` / `price_snapshots`
- 仓库：`services/repositories/plan_repository.py`（不存在 `services/plan_repository.py`）
- 保存：`plan_service.insert_plan`；批量导入 `insert_plans_batch`（blueprint 导入走批量）
- 启动：`plan_table._start_plan` → `plan_start_check.plan_start_block_reason`（**纯逻辑、零 DB**）→ `plan_execution.check_materials` → `start_plan`（原子 UPDATE status + `inventory_manager.deduct_item`）
- 完成：`plan_execution.complete_plan`（成品入 `inventory_items` + `consume_bpc_runs` 消耗 `user_blueprints` + 清 bindings）；撤销 `cancel_plan` 返还材料
- 展开：`plan_table._decompose_parent` → `plan_decompose.decompose_plan`（递归读 `user_blueprints` + bom 材料）→ `plan_rebuild.rebuild_children` → `PlanRepository` 增删改
- 读取：`plan_service.load_plans`；价格快照 `save_price_snapshots`
- 旁路：`plan_aggregator` 是**采购/需求聚合**，不是计划展开
- 价格口径（工具栏双行价格设置）：`mat_hub/mat_price_type/mat_mult` 与 `prod_hub/prod_price_type/prod_mult` 由 `top_toolbar.get_price_settings()` 提供，消费方必须**整套一起透传**（漏一项就是「改设置数字不动」的缺陷）：
  - 计划成本/利润：`BatchPlanCalcWorker`（表格批量重算）、`industry_view._on_plan_add`、`plan_table._view_cost_breakdown` → 成本明细弹窗、`parent_decompose_dialog`、`blueprint_tab` 的「加入制造规划」预览 → `ScoringService.calculate_plan_metrics(mat_mult=, prod_mult=)` → `scoring_facade.calc_manufacturing_score` → `domain.scoring`
  - ⚠️ `scoring_facade` 有 TTL 缓存，`mat_price_mult/prod_price_mult` **必须进 cache_key**，否则同一类陈旧缓存缺陷会在评分层复现
  - 倍率只作用于玩家买卖价：材料价乘 `mat_mult`、成品价乘 `prod_mult`；**EIV 用的 adjusted_price 不乘**（CCP 官方估价，与买卖价无关）
  - 状态栏「备料中采购」：`industry_view._refresh_procurement_summary` → `ProcurementSummaryWorker(region_id, price_type, price_mult)` → `ui_data_service.aggregate_procurement_summary` → `plan_aggregator.aggregate_procurement`。该函数带指纹缓存，指纹 = **（价格口径, 计划字段集）**，价格项漏进指纹就会回吐旧值
  - 口径分叉（有意）：采购小助手 `procurement_tab` 有自己独立的 Hub/价格类型控件、无倍率控件，不套用工具栏倍率
- **启动成本快照**（`production_plans.material_cost_snapshot`，schema v12→v13）：`start_plan` 在**扣减之前、事务之外**采样机库加权单价，写入 `{"total": 总成本, "unit": {type_id: 单价}}`：
  - 两个「之前」都是硬约束 —— `deduct_item` 把余量清到 0 会删行（扣完再取价得 0）；`db.connect()` 同线程复用连接、嵌套 with 退出会提前 commit（在事务内取价会毁掉「失败整体回滚」）
  - `complete_plan` 按快照 `total` 算成品入库单价；`cancel_plan` 按快照 `unit` 返还成本 —— 都是**启动那一刻**的口径，不受在产期间价格重算影响
  - 旧计划无快照 → 回退 `material_cost` / 机库当前加权成本（向后兼容）；`cancel_plan` 与 `reset_plan_for_reuse` 会清空快照
- **重算失败不得清零成本**：`BatchPlanCalcWorker` 对「评分异常→空 dict」与 `no_price`/`no_blueprint`/`no_materials`（`calculate_plan_metrics` 对这三种 status 返回全零 dict）的行**跳过不发**，保留库中上次的正确值；父项若同组有更深的失败子项也一并跳过（否则 `mother_subitem_cost_map` 拿空 dict 会把母项成本算低）。跳过数量经 `failed_names` 由状态栏提示「N 条计划估值失败，成本沿用上次值」
- **完成入口统一**：右键「下线」与状态列「待下线」都走 `CompletePlansDialog` 选产出机库（批量只弹一次框）；`deposit_hangar_id` 为空时不再静默跳过入库
- **「取消生产」语义**（菜单原名「删除行」）：解除蓝图绑定 + 删除计划行，**不返还已扣材料** —— 与游戏「取消产线只退蓝图」一致（领域模型见 `AUDIT-20260801.md`）。误点启动请用「撤销启动（返还材料）」；删除前有确认框按状态说明后果
- **蓝图流程不足可强制启动**：`_binding_shortfall` 有两道（张数 / 每张流程 ≥ runs），
  `start_plan` 与 `complete_plan` **成对**提供 `allow_bp_short` —— **只放开启动会造成死锁**
  （强制启动的计划永远无法下线）。强制时**不换绑**，完成时 `consume_bpc_runs` 按实际可用量消耗；
  账面偏差由用户在蓝图管理做**全量剪贴板导入**矫正。UI 三处入口都要覆盖：
  计划表格 `_start_plan`、小助手 `_start`、以及 `procurement_tab` 直调 `complete_plan` 的那条
  （确认框留 UI 层：`complete_plans()` 是无 parent 的服务函数）
- **并行产线逐线计算**：各线按**各自绑定蓝图**的 ME/TE 独立结算
  - 等级来源：`plan_service._enrich_rows` 预填 `line_levels`（`user_blueprints.me_level/te_level`，
    绑定来源与 `bound_blueprint_ids` 同一回退：关联表优先 → `assigned_blueprint_id`）；
    未绑的线取**已绑里最差那张**（`min(me)` 与 `min(te)` 分别取）；一张没绑则留空
  - 短路：`line_levels` 为空、或**与计划级 (me,te) 完全一致** → 走原单次路径（零行为变化）。
    ⚠️ 短路条件不能写成「各线彼此一致」—— 五张都绑 ME8 而计划级写 10 时仍须走逐线
  - 汇总（`ScoringService.combine_per_line`）：材料/作业费/收入/利润 **Σ**；
    **时长取 max**（并行同时跑，单次路径的 `hours_per_run × runs` 是其均匀特例）；
    日产出 Σ(24/hoursᵢ)；利润率 = Σ利润/Σ总成本（与单线同式）
  - ⚠️ **`materials` 保持「单线单轮」语义**（逐线时取最差线）：`plan_metrics` 两处消费方
    都会再乘 `runs × parallels`，放汇总值会被**重复放大**。
    要求精确的 `material_requirements` 改读新增的 `materials_all_lines`（Σ 各线单轮量，只乘 `runs`）
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
      · 发明 InventionPlanDialog 产物（多产物下拉）+ 解码器 + 预期成功率 + 尝试次数
      · 研究 ResearchPlanDialog  ME/TE + 目标等级

评分（按行 activity 分派）
  ScoringService.calculate_plan_metrics
    · manufacturing → scoring_facade（现状路径，零改动）
    · copying/invention/researching_* → ScoringService._calculate_research_metrics
        → services/plan_metrics.invention_plan_cost / copying_plan_cost / research_plan_cost
        → domain/research.py（成功率 / 解码器表 / BPC 产出 / 科学作业时长）

执行
  启动：plan_start_check.plan_start_block_reason(blueprint_ready=plan_execution.plan_blueprint_ready)
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
- 发明产出的 BPC 基础流程数 = `min(T1 拷贝上限, T2 制造上限)`（SDE 实测 1125 条路径可校验），
  不要按「舰船 1 / 其余 10」硬编码。

## 库存管理

- 表：user 库 `hangars` / `inventory_items` / `user_blueprints`
- UI 同步调用（无独立 worker）：`inventory_manager.add_item`（加权平均成本）、`set_item_quantity`（经 `inventory_import.compute_import_diff` 全量覆盖/删除）、`move_quantity`/`move_items`（transfer 弹窗）
- `deduct_item` 被计划启动/展开/重建调用
- 剪贴板导入按仓库类型校验（同一机库分两张表、两页签）：材料侧 `inventory_clipboard_service.parse_clipboard`（机库管理「库存修正/增量粘贴」、采购页「增量添加到仓库」、「移库」）过滤蓝图行；蓝图侧 `ui_data_service.parse_blueprint_clipboard`（蓝图管理「粘贴导入蓝图」）过滤材料行。判定见 `services/item_kind.py`（`item` group 名后缀 = 蓝图，失败开放），过滤数在预览框统计栏提示

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

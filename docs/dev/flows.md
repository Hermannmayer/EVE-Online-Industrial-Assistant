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

## 库存管理

- 表：user 库 `hangars` / `inventory_items` / `user_blueprints`
- UI 同步调用（无独立 worker）：`inventory_manager.add_item`（加权平均成本）、`set_item_quantity`（经 `inventory_import.compute_import_diff` 全量覆盖/删除）、`move_quantity`/`move_items`（transfer 弹窗）
- `deduct_item` 被计划启动/展开/重建调用

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

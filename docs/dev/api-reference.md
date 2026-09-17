# API 参考

本页汇总所有模块的函数级 API 文档。文档由 `scripts/gen_api_docs.py` 从源码自动生成，与代码同步更新。

::: tip 生成方式
每次 push main 时，CI 运行 `gen_api_docs.py` 重新生成所有 API 文档页。文档内容直接来自 Python AST 解析的函数签名和 docstring。
:::

## 工具层（core/）

| 模块 | 说明 |
|------|------|
| [`core.cache`](/api/core/cache) | `TtlLRUCache` 线程安全 LRU + TTL 缓存 |
| [`core.constants`](/api/core/constants) | 全局常量（贸易中心 ID 映射） |
| [`core.container`](/api/core/container) | IOC 容器 — 15+ 服务生命周期管理 |
| [`core.eve_formulas`](/api/core/eve_formulas) | EVE Online 游戏公式（税率、经纪人费率、精炼产出率等） |
| [`core.hot_reload`](/api/core/hot_reload) | dev.py 热重载支持 |
| [`core.logger`](/api/core/logger) | 日志配置 |
| [`core.paths`](/api/core/paths) | 所有路径集中管理 |
| [`core.single_instance`](/api/core/single_instance) | 单实例锁（防止多开） |
| [`core.version`](/api/core/version) | 单一版本源（`__version__`） |

## 业务层 — 核心服务（services/）

| 模块 | 说明 |
|------|------|
| [`services.scoring_service`](/api/services/scoring_service) | 评分核心 — ScoringCache + 定价查询 + 制造/贸易/精炼评分 |
| [`domain/formulas.py`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/blob/main/domain/formulas.py) | 制造计算核心（材料用量/安装费/生产时长） |
| [`services.pricing_service`](/api/services/pricing_service) | 统一定价 + 成交量 + 系统成本指数 |
| [`services.bom_expander`](/api/services/bom_expander) | BOM 递归展开（T2/T3 产业链完整材料树） |
| [`services.logistics`](/api/services/logistics) | 物流运费估算与利润计算 |
| [`services.refining_service`](/api/services/refining_service) | 精炼价值计算 |
| [`services.inventory_manager`](/api/services/inventory_manager) | 库存 CRUD + 加权平均成本 |
| [`services.plan_aggregator`](/api/services/plan_aggregator) | 计划数据聚合 |
| [`services.database_manager`](/api/services/database_manager) | 多库连接管理（ATTACH DATABASE） |
| [`services.init_check`](/api/services/init_check) | 数据初始化状态检测 |
| [`services.init_service`](/api/services/init_service) | 初始化服务（SDE/ESI 数据拉取） |

## 业务层 — 数据仓库（services/repositories/）

| 模块 | 说明 |
|------|------|
| [`services.repositories.item_repository`](/api/services/repositories/item_repository) | 物品数据仓库 |
| [`services.repositories.market_repository`](/api/services/repositories/market_repository) | 市场数据仓库 |
| [`services.repositories.blueprint_repository`](/api/services/repositories/blueprint_repository) | 蓝图数据仓库 |
| [`services.repositories.plan_repository`](/api/services/repositories/plan_repository) | 生产计划仓库 |

## 业务层 — 其他（services/）

| 模块 | 说明 |
|------|------|
| [`services.blueprint_reader`](/api/services/blueprint_reader) | 蓝图数据读取 |
| [`services.name_resolver`](/api/services/name_resolver) | 物品名称解析 |
| [`services.terminology`](/api/services/terminology) | EVE 术语查询 |
| [`services.char_config_resolver`](/api/services/char_config_resolver) | 角色配置合并解析 |
| [`services.char_config_validator`](/api/services/char_config_validator) | 角色配置验证 |
| [`services.schema_migrations`](/api/services/schema_migrations) | 数据库 Schema 迁移 |
| [`services.watchlist_manager`](/api/services/watchlist_manager) | 关注列表管理 |
| [`services.price_history`](/api/services/price_history) | 价格历史查询与缓存 |
| [`services.client`](/api/services/client) | ESI HTTP 客户端 |

## 业务层 — 数据导入器（services/importers/）

| 模块 | 说明 |
|------|------|
| [`services.importers.getprices`](/api/services/importers/getprices) | 市场价格拉取 |
| [`services.importers.getindustry`](/api/services/importers/getindustry) | 工业系统成本指数拉取 |
| [`services.importers.getcontracts`](/api/services/importers/getcontracts) | 合同数据拉取 |

## UI 数据模型（ui_qml/models/）

> 这些表模型是 QML 页面与残留 Widgets 控制器共用的基础模型：QML 侧读
> `*_qml_model.py` 适配层。原先在 `ui_pyside6/models/`，批次 6.0 迁来
> （`ui_pyside6/` 包已在批次 7.5 整个删除）。

| 模块 | 说明 |
|------|------|
| [`ui_qml.models.industry_models`](/api/ui_qml/models/industry_models) | 工业制造 Qt 数据模型（生产计划表） |
| [`ui_qml.models.contract_models`](/api/ui_qml/models/contract_models) | 合同数据模型 + 过滤代理 |
| [`ui_qml.models.trade_models`](/api/ui_qml/models/trade_models) | 贸易评分 Qt 数据模型 |
| [`ui_qml.models.estimate_models`](/api/ui_qml/models/estimate_models) | 估价 Qt 数据模型 |
| [`ui_qml.models.all_items_models`](/api/ui_qml/models/all_items_models) | 全部物品 Qt 数据模型 |
| [`ui_qml.models.compare_models`](/api/ui_qml/models/compare_models) | 批量对比数据模型 + ISK/等级格式化 |
| [`ui_qml.models.inventory_helpers`](/api/ui_qml/models/inventory_helpers) | 仓库 / 蓝图表模型 |
| [`ui_qml.models.query_models`](/api/ui_qml/models/query_models) | 物品查询表模型 + 行格式化 |
| [`ui_qml.models.watchlist_models`](/api/ui_qml/models/watchlist_models) | 关注列表表模型 |
| [`ui_qml.models.plan_table_constants`](/api/ui_qml/models/plan_table_constants) | 生产计划表列索引常量 |

## UI 异步 Workers（ui_qml/workers/）

| 模块 | 说明 |
|------|------|
| [`ui_qml.workers.base_worker`](/api/ui_qml/workers/base_worker) | Worker 基类（评分 / 批量评分） |
| [`ui_qml.workers.industry_workers`](/api/ui_qml/workers/industry_workers) | 工业制造 Worker |
| [`ui_qml.workers.trade_workers`](/api/ui_qml/workers/trade_workers) | 贸易评分 Worker |
| [`ui_qml.workers.contract_workers`](/api/ui_qml/workers/contract_workers) | 合同取数 Worker |
| [`ui_qml.workers.all_items_workers`](/api/ui_qml/workers/all_items_workers) | 全部物品分类树 / 物品 / 搜索 Worker |
| [`ui_qml.workers.init_workers`](/api/ui_qml/workers/init_workers) | 数据初始化 Worker |
| [`ui_qml.workers.refine_worker`](/api/ui_qml/workers/refine_worker) | 精炼计算 Worker |
| [`ui_qml.workers.npc_seller_workers`](/api/ui_qml/workers/npc_seller_workers) | NPC 收购单 Worker |
| [`ui_qml.workers.score_worker`](/api/ui_qml/workers/score_worker) | 评分线程 `ScoreW`（全物品 / 可制造页共用） |
| [`ui_qml.workers.query_workers`](/api/ui_qml/workers/query_workers) | 查询页搜索 / 候选 / 类别树线程 |
| [`ui_qml.workers.order_workers`](/api/ui_qml/workers/order_workers) | 订单缓存 + ESI 取数线程 |
| [`ui_qml.workers.batch_price_workers`](/api/ui_qml/workers/batch_price_workers) | 批量查价线程与搜索助手 |
| [`ui_qml.workers.mfg_tree_worker`](/api/ui_qml/workers/mfg_tree_worker) | 可制造物品分类树线程 |
| [`ui_qml.workers.price_history_worker`](/api/ui_qml/workers/price_history_worker) | 价格历史取数线程 |
| [`ui_qml.workers.blueprint_import_worker`](/api/ui_qml/workers/blueprint_import_worker) | 蓝图剪贴板导入线程 |
| [`ui_qml.workers.blueprint_plan_worker`](/api/ui_qml/workers/blueprint_plan_worker) | 蓝图批量加入规划的指标计算线程 |
| [`ui_qml.workers.estimate_workers`](/api/ui_qml/workers/estimate_workers) | 估价 / 剪贴板解析线程 |
| [`ui_qml.workers.compare_chart`](/api/ui_qml/workers/compare_chart) | 批量对比计算线程 + 搜索辅助 |
| [`ui_qml.workers.watchlist_workers`](/api/ui_qml/workers/watchlist_workers) | 关注列表候选搜索线程 |

## UI 页面概览

> UI 主体是 QML（页面在 `ui_qml/qml/pages/`，Python 桥在 `ui_qml/bridge/`），
> 以下只列**仍在 Python 侧**的视图模块概览，详细签名请直接查看源码。

### views/（残留的 Widgets 业务控制器）

| 文件 | 功能 |
|------|------|
| `ui_qml/views/industry_view.py` | 工业制造页控制器（页面「5 区布局」的样板） |
| `ui_qml/views/procurement_tab.py` | 采购页控制器 |

### views/industry/

| 文件 | 功能 |
|------|------|
| `ui_qml/views/industry/plan_table.py` | 生产计划表格的业务逻辑（21 列；视图是 `ui_qml/qml/pages/PlanTablePane.qml`） |
| `ui_qml/views/industry/production_launcher.py` | 产线启动小助手（独立工具窗） |
| `ui_qml/views/industry/complete_plans_dialog.py` | 下线落库与「发明结果回填」的编排（不再是 `QDialog`） |

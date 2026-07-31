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
| [`services.manufacturing_calculator`](/api/services/manufacturing_calculator) | 制造计算核心（材料用量/安装费/生产时长） |
| [`services.pricing_service`](/api/services/pricing_service) | 统一定价 + 成交量 + 系统成本指数 |
| [`services.bom_expander`](/api/services/bom_expander) | BOM 递归展开（T2/T3 产业链完整材料树） |
| [`services.logistics`](/api/services/logistics) | 物流运费估算与利润计算 |
| [`services.refining_service`](/api/services/refining_service) | 精炼价值计算 |
| [`services.inventory_manager`](/api/services/inventory_manager) | 库存 CRUD + 加权平均成本 |
| [`services.plan_aggregator`](/api/services/plan_aggregator) | 计划数据聚合 |
| [`services.production_scheduler`](/api/services/production_scheduler) | 生产调度 |
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
| [`services.scoring`](/api/services/scoring) | 评分入口（委托给 ScoringService） |

## 业务层 — Workers（services/workers/）

| 模块 | 说明 |
|------|------|
| [`services.workers.getprices`](/api/services/workers/getprices) | 市场价格拉取 Worker |
| [`services.workers.getindustry`](/api/services/workers/getindustry) | 工业系统成本指数拉取 |
| [`services.workers.getcontracts`](/api/services/workers/getcontracts) | 合同数据拉取 |

## UI 数据模型（ui_pyside6/models/）

| 模块 | 说明 |
|------|------|
| [`ui_pyside6.models.industry_models`](/api/ui_pyside6/models/industry_models) | 工业制造 Qt 数据模型 |
| [`ui_pyside6.models.trade_models`](/api/ui_pyside6/models/trade_models) | 贸易评分 Qt 数据模型 |

## UI 异步 Workers（ui_pyside6/workers/）

| 模块 | 说明 |
|------|------|
| [`ui_pyside6.workers.base_worker`](/api/ui_pyside6/workers/base_worker) | Worker 基类 |
| [`ui_pyside6.workers.industry_workers`](/api/ui_pyside6/workers/industry_workers) | 工业制造 Worker |
| [`ui_pyside6.workers.trade_workers`](/api/ui_pyside6/workers/trade_workers) | 贸易评分 Worker |
| [`ui_pyside6.workers.init_workers`](/api/ui_pyside6/workers/init_workers) | 数据初始化 Worker |
| [`ui_pyside6.workers.refine_worker`](/api/ui_pyside6/workers/refine_worker) | 精炼计算 Worker |

## UI 页面概览

> 以下为 UI 层页面模块概览，详细签名请直接查看源码。

### views/query/

| 文件 | 功能 |
|------|------|
| `query_page.py` | 物品查询主页面 |
| `query_search.py` | 搜索组件 |
| `query_order_popup.py` | 深层次订单弹窗 |
| `query_chart.py` | 价格走势图 |

### views/industry/

| 文件 | 功能 |
|------|------|
| `top_toolbar.py` | 工具栏（蓝图导入 + 双行价格设置） |
| `plan_table.py` | 生产计划表格（19 列） |
| `plan_edit_dialog.py` | 计划编辑对话框 |
| `gantt_view.py` | 甘特图视图 |
| `price_source_widget.py` | 材料/成品独立价格来源 |
| `action_buttons.py` | 底部操作按钮 |
| `status_bar.py` | 底部状态栏 |
| `blueprint_dialog.py` | 蓝图表弹窗 |
| `materials_dialog.py` | 材料总表 |
| `output_dialog.py` | 产出总表 |
| `cost_breakdown_dialog.py` | 成本明细 |
| `char_usage_dialog.py` | 人物占用表 |
| `flow_layout.py` | 自动换行布局 |

### views/inventory/

| 文件 | 功能 |
|------|------|
| `inventory_page.py` | 仓库主页面 |
| `hangar_tab.py` | 机库 Tab |
| `blueprint_tab.py` | 蓝图管理 Tab |
| `blueprint_import_worker.py` | 蓝图批量导入 |
| `inventory_helpers.py` | 辅助函数 |
| `review_dialog.py` | 入库审核对话框 |

### views/compare/

| 文件 | 功能 |
|------|------|
| `compare_dialog.py` | 物品对比对话框 |
| `compare_chart.py` | 对比图表 |
| `compare_models.py` | 对比数据模型 |

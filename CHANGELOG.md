# 更新日志

本项目的版本遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。当前处于 **0.x 开发阶段**：功能与 API 均可能随时变化，每次发版递增次版本号（MINOR），PATCH 位在 0.x 阶段不用于常规递增。

本文件是唯一更新日志源：发版时由 python-semantic-release 自动在版本列表标记处插入新版本段，无需手动维护。

<!-- version list -->

## v0.3.0 (2026-07-31)

### Bug Fixes

- CI mypy 平台配置 + PyInstaller 依赖（解决 Linux CI 上 windll 报错与 release 打包缺依赖）
  ([`d61349a`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d61349aab6eb61008f0f33b9384d240ad3d57bba))

### Chores

- 触发文档站部署（GitHub Pages 已启用）
  ([`c84a9eb`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/c84a9eb46727943b30eeb34d564126c09240b230))

## v0.2.0 (2026-07-31)

### Added

- 语义化版本管理：新增 `core/version.py` 单一版本源；接入 python-semantic-release，push main 自动发版（解析 Conventional Commits → bump 版本 → 更新 CHANGELOG → 打 tag → 建 GitHub Release → 打包上传安装包）
- CI 版本一致性校验（`scripts/check_version.py`）：`core/version.py` / CHANGELOG 最新版本段 / git tag 三者不一致即阻断合并
- VitePress 中文文档站（`docs/`），函数级 API 参考自动生成（`scripts/gen_api_docs.py`），GitHub Actions 自动部署到 GitHub Pages

### Changed

- 依赖管理统一迁移到 uv：`uv sync --dev` 安装依赖；移除 `requirements.txt` 与全部 pip 安装路径
- `build_release.py` 版本号改为从 `core/version.py` 读取，不再硬编码
- 历史 1.x 版本段降级为归档记录（见下文「历史遗留」）

### Removed

- 移除 `build_release.py` 中已废弃的 pyperclip hidden-import（代码已改用 Qt `QApplication.clipboard()`）

## 历史遗留（v0.2.0 之前）

> 产品现处于 0.x 开发阶段。以下 1.x 版本段仅作归档，不代表当前版本状态。

### v1.4.0 (2026-07-27)

#### 架构重构

- IOC 容器化：`AppContainer` 统一管理 15+ 服务生命周期，消除模块级全局 DB 单例
- 新增 `core/cache.py`：`TtlLRUCache` 线程安全 LRU+TTL 缓存，替代旧 `ScoringCache`
- 新增 `services/repositories/`：4 个数据仓库（Item/Market/Blueprint/PlanRepository），封装跨库查询
- 新增 `services/pricing_service.py`：`PricingService` 统一定价 + 成交量 + 系统成本指数查询
- 新增 `services/char_config_resolver.py`：角色配置四源合并解析器
- 新增 `services/refining_service.py`：精炼价值计算独立服务
- 新增 `services/bom_expander.py BomExpander` / `services/logistics.py LogisticsService` 等 6 个可注入服务类
- `services/scoring_service.py` 瘦身：972 行 → 536 行，移除 437 行死代码（ScoringCache、模块级缓存函数、resolve_char_config、get_price 等迁移到新模块）

#### 安装费修复

- 安装费改为读取 ESI **adjusted_price**（7 日均价）计算 EIV，而非市场实时卖出价
- 系统成本指数（SCI）降级：`system_id=None` 时自动从 `sell_hub` 名称（Jita/Amarr等）查找对应太阳系 ID，使用真实 SCI 值
- 安装费 breakdown 按游戏类目拆分：`system_cost` / `facility_tax` / `scc_surcharge` / `installation_fee`

#### 材料损耗公式修正

- **关键修复**：SDE `blueprint_materials.quantity` 存储的是 **ME 0 实际用量**（已含基础浪费），旧代码当作「真实基础量」又加了一层浪费
- 新公式：`actual = ceil(db_qty × (1 + wf/100/(1+ME)) / (1 + wf/100) × 结构减免)`
- ME 0 时用量与游戏完全一致，ME 上升时逐步减少

#### 消费者迁移

- 4 个 UI Worker → 通过容器注入服务，不再模块级引用
- 8 个 UI View → 改用容器 + `TtlLRUCache`
- 2 个 Service 文件 → `PricingService` 替代模块级 `get_price`
- 6 个测试文件 → 更新 mock 路径与断言

#### 测试

- 653 测试全部通过，0 失败 0 错误
- 测试基础设施改进：`conftest.py` 修复 18 个 UI 测试 RuntimeError

#### 新功能

- 生产计划管理：计划表编辑、甘特图视图、多计划切换（Phase 3）
- 精炼计算：矿物精炼产出与效率计算（Phase 3）
- 设置对话框：应用设置集中管理界面（Phase 3）
- Universe 数据缓存：SDE 星系/空间站数据缓存加速（Phase 3）
- 甘特图主题：生产进度可视化与双主题适配（Phase 3）

#### Bug 修复

- 修复工业界面 5 个问题：SpinBox 重叠、ComboBox 主题/Hub 中文名、蓝图等级参与计算、角色技能读取、制造时长未生效
- 修复待采购弹窗图标/矿物名/窄高尺寸/InputDialog 关键字
- BSD YAML 列表格式 station 数据写入
- 状态栏显示具体哪项数据未初始化便于诊断
- 移除 universe 检查避免每次提示初始化
- SDE zip 文件名映射 + universe 路径解析 + operationServices 不存在修复

#### 性能优化

- SDE zip 共享缓存加速多 Worker 并行导入
- 全量 SDE 数据集成（三人团队并行实施）

#### 代码质量

- mypy 类型警告修复、测试基础设施改进
- 过滤 Qt 字体大小警告

### v1.2.0 (2026-07-01)

#### 新功能

- 价格走势图：订单弹窗→走势图按钮，历史价格趋势可视化（Wave 2）
- 批量导出 CSV/Excel：查询页、全物品浏览页均支持导出（Wave 0-1）
- 代采购管理：IndustryPage 新增第4Tab，管理代采购订单与供应商（Wave 3-4）
- 价格变化自动检测：关注列表 60s 定时器，自动检测价格变动并通知（Wave 3-4）
- 合同视图：查看和管理游戏内合同（Wave 6-7）
- 物流距离计算：自动计算并补全物流距离数据（Wave 6）
- 系统通知：集成系统桌面通知（Wave 7）

#### Bug 修复

- 修复启动时忽略自动更新设置的 bug
- 修复主题架构 — 从 `from import VAR` 改为 `import theme as module`
- 修复多项 UI 颜色与样式问题
- 数据库初始化流程修复

#### 代码质量

- 安全修复 + 依赖注入 + 测试基础设施重构（第一阶段）
- UI 拆分 + 依赖注入消除 + DB 清理（第二、三阶段）
- 配色规范化，双主题支持全面强化
- 项目结构清理：移除废弃文档、.vscode/、.github/、缓存文件
- 引入 ruff 作为统一 lint/format 工具（pyproject.toml 配置）
- 所有视图添加 `add_theme_listener` + `_on_theme_changed` 模式
- AGENTS.md 替代废弃的 PROMPT.md
- 设计文档精简为 4 篇核心文档

#### 测试

- 测试总数从约 50 增加到 204 个
- 新增测试文件：
  - `test_contract_view.py` — 492 行，合同视图功能测试
  - `test_logistics.py` — 537 行，物流距离计算测试
  - `test_watchlist_manager.py` — 285 行，关注列表与价格变化检测测试
  - `test_procurement.py` — 182 行，代采购管理测试
  - `test_price_history.py` — 180 行，价格走势图数据测试
  - `test_export_helper.py` — 104 行，批量导出测试
  - `test_scoring_core.py` — 评分核心逻辑测试
  - `test_theme_listeners.py` — 主题监听模式测试
  - `test_database_manager.py` — 数据库连接管理器测试
  - `test_paths.py` — 路径管理测试
- 新增 `conftest.py` 共享测试 fixtures

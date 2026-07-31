# 更新日志

本项目的版本遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。`feat` 递增 MINOR（0.7.0 → 0.8.0），`fix`/`perf` 递增 PATCH（0.7.0 → 0.7.1），其余提交不触发发版；大版本（1.0.0 及以后）由发布者手动决定。

本文件是唯一更新日志源：发版时由 python-semantic-release 自动在版本列表标记处插入新版本段，无需手动维护。

<!-- version list -->

## v0.8.0 (2026-07-31)

### Bug Fixes

- 审计 P0 — 精炼查错表、迁移原子性、char_config 反依赖下沉
  ([`79e9128`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/79e9128c546580351d8c4c83702c9b6b5ae16505))

- 审计 P1 — 评分缓存接线、ESI 限流、费用差额计费、busy_timeout 等 10 项
  ([`71006bf`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/71006bf6d7c9b0d2b0df4f3b4a7b41ff84fe1565))

- 审计 P1 尾 — theme 监听器弱引用、fetch_time 索引、schema 迁移收敛、删 scheduler
  ([`79b93d2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/79b93d254206dec892d7223cebc2f8220f2d8ed3))

### Chores

- Ruff 格式化存量文件（21 个历史未格式化文件清零）
  ([`2452e0a`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2452e0a98731173845f249de5b6986d5daa210f3))

- 清理过期文档与残留文件（-1022 行）+ 修正引用
  ([`bb4909d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/bb4909d7b81f1cd035b33382acce28605eff2246))

### Documentation

- 新增 2026-07-31 审计报告 — 4 P0 + 20 P1 问题清单与修复状态
  ([`49f7a1c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/49f7a1c92059591d3011ce04c29b677e290dc6d3))

- 澄清材料浪费公式误报 + 防错机制落地（字段契约 + 金标准测试）
  ([`d410f58`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d410f58220539d4b07c1a8f8f0b8c236965b087d))

### Features

- 文档联动机制 — 提交时自动生成 API 文档 + README/链接校验 + 变更提醒
  ([`e3015db`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/e3015dbf04e51f414a769df5fd7f99989599dd14))


## v0.7.0 (2026-07-31)

### Bug Fixes

- 补 blueprint_tab 蓝图函数 patch，修复 CI 主题监听测试
  ([`4cd4f7b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/4cd4f7be9a1a2fb971140f3b3bebd3c5f527ca60))


## v0.6.0 (2026-07-31)

### Bug Fixes

- 补 hangar_tab 模块 patch，修复 CI 上 inventory 主题监听测试
  ([`452d74b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/452d74b313a72d29b35489fddff8224b77962f1c))


## v0.5.0 (2026-07-31)

### Bug Fixes

- 修复 UI 测试依赖真实数据库目录导致 CI(Linux) 失败（patch blueprint_tab get_container）
  ([`d5e76f2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d5e76f210e4c4280743ce61683429e57f27dac92))


## v0.4.0 (2026-07-31)

### Bug Fixes

- 修复 test_init_check 依赖真实数据库路径导致 CI(Linux) 失败
  ([`4ad8c53`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/4ad8c53cace2241303dfc55e347253898252f1f0))

### Chores

- 修复 CHANGELOG 头部被 semantic-release 拆断的结构
  ([`a375571`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a37557106c58c43ee95c58f8ad9c5efef9a052db))

### Continuous Integration

- 添加 libEGL/libGL 系统库解决 Linux 上 PySide6 导入失败
  ([`0655c94`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/0655c946e648914bc70b4e6d25f07921a18521f5))


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

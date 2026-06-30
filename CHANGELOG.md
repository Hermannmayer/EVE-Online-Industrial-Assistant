# 更新日志

## v1.2.0 (2026-07-01)

### 新功能
- 价格走势图：订单弹窗→走势图按钮，历史价格趋势可视化（Wave 2）
- 批量导出 CSV/Excel：查询页、全物品浏览页均支持导出（Wave 0-1）
- 代采购管理：IndustryPage 新增第4Tab，管理代采购订单与供应商（Wave 3-4）
- 价格变化自动检测：关注列表 60s 定时器，自动检测价格变动并通知（Wave 3-4）
- 合同视图：查看和管理游戏内合同（Wave 6-7）
- 物流距离计算：自动计算并补全物流距离数据（Wave 6）
- 系统通知：集成系统桌面通知（Wave 7）

### Bug 修复
- 修复启动时忽略自动更新设置的 bug
- 修复主题架构 — 从 `from import VAR` 改为 `import theme as module`
- 修复多项 UI 颜色与样式问题
- 数据库初始化流程修复

### 代码质量
- 安全修复 + 依赖注入 + 测试基础设施重构（第一阶段）
- UI 拆分 + 依赖注入消除 + DB 清理（第二、三阶段）
- 配色规范化，双主题支持全面强化
- 项目结构清理：移除废弃文档、.vscode/、.github/、缓存文件
- 引入 ruff 作为统一 lint/format 工具（pyproject.toml 配置）
- 所有视图添加 `add_theme_listener` + `_on_theme_changed` 模式
- AGENTS.md 替代废弃的 PROMPT.md
- 设计文档精简为 4 篇核心文档

### 测试
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

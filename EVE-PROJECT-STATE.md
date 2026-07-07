# EVE Online Industrial Assistant — 项目状态

> 最后更新: 2026-07-07 · 146 commits · 620 测试用例

---

## 📊 项目规模

| 指标 | 数值 |
|---|---|
| Python 源文件（不含测试） | 100 |
| 测试文件 | 50 |
| 总 Python 文件 | 152 |
| 代码行数 | 37,884 |
| 测试用例数 | 620 |
| SQLite 数据库 | 4 (`reference.db`, `market.db`, `user.db`, `blueprint.db`) |
| Git 提交数 | 146 |
| 外部依赖 | 8（PySide6, aiohttp, aiosqlite, tenacity, tqdm, pyperclip, pyyaml, openpyxl） |

---

## ✅ 已完成功能清单

### 核心功能
- [x] **多区域价格查询** — 四大贸易中心（Jita/Amarr/Dodixie/Rens）价格一键查询
- [x] **物品搜索** — 中文/英文名模糊搜索，自动补全
- [x] **制造利润计算** — 基于蓝图的 BOM 展开、成本核算、利润/利润率评分
- [x] **贸易评分系统** — 跨区域价格比较、利润率/成交量/风险综合评分
- [x] **估价功能** — 剪贴板粘贴→批量获取物品价格
- [x] **库存管理** — 机库物品 CRUD、库存价值统计
- [x] **价格走势图** — 历史价格趋势可视化（Wave 2）
- [x] **代采购管理** — IndustryPage 第 4 Tab，管理代采购订单与供应商（Wave 3-4）
- [x] **价格变化自动检测** — 关注列表 60s 定时器，自动检测价格变动并通知（Wave 3-4）
- [x] **合同视图** — 查看和管理游戏内合同（Wave 6-7）
- [x] **物流距离计算** — 自动计算并补全物流距离数据（Wave 6）
- [x] **批量查价功能** — 批量价格查询窗口（Wave 18）
- [x] **批量导出 CSV/Excel** — 查询页、全物品浏览页均支持导出
- [x] **生产计划管理** — 生产排程、BOM 材料汇总、计划表编辑、甘特图
- [x] **精炼计算** — 矿物精炼产出与效率计算
- [x] **设置对话框** — 应用设置集中管理界面
- [x] **Universe 数据缓存** — SDE 星系/空间站数据缓存加速

### 技术基础设施
- [x] **PySide6 桌面 GUI** — 响应式布局、侧边导航、多 Tab 页面
- [x] **双主题系统** — One Dark Pro（暗色） / One Light（亮色），全局 QSS
- [x] **4 库分离架构** — reference.db / market.db / user.db / blueprint.db
- [x] **数据库迁移** — 旧单库→4 库自动迁移 + 蓝图表分离
- [x] **ESI HTTP 客户端** — 基于 aiohttp 的异步 ESI API 调用
- [x] **数据初始化向导** — 首次启动引导（SDE 导入、价格拉取、图标缓存）
- [x] **后台 Worker 线程** — QThread 异步执行，不阻塞 UI
- [x] **价格数据并发拉取** — 优化 ESI 请求并发
- [x] **评分缓存** — scoring_cache 避免重复计算
- [x] **角色配置** — 多角色管理，支持 API Key 与技能配置

### UI 页面
| 页面 | 文件 | 功能 |
|---|---|---|
| 物品查询 | `query_view.py` | 多区域价格、历史趋势、导出 |
| 制造/工业 | `industry_view.py` | BOM 展开、利润计算、生产计划、代采购 |
| 贸易评分 | `trade_view.py` | 跨区域评分排序 |
| 库存管理 | `inventory_view.py` | 机库物品管理、价值统计 |
| 估价 | `estimate_view.py` | 剪贴板批量估价 |
| 角色设置 | `char_settings_view.py` | 角色管理、技能配置 |
| 合同视图 | `contract_view.py` | 游戏内合同查看管理 |
| 全物品浏览 | `all_items_view.py` | 完整物品列表浏览筛选 |
| 批量查价 | `batch_price_dialog.py` | 批量价格查询 |
| 价格对比 | `compare_dialog.py` | 多物品价格比较 |
| 价格走势图 | `price_chart.py` | 历史价格可视化 |
| 首次启动向导 | `init_wizard.py` | 数据库初始化引导 |
| 关注列表 | `watchlist_view.py` | 价格变动监控 |

### 开发基础设施
- [x] **热重载开发模式** — 文件变更自动重启 + 状态保存/恢复
- [x] **Pre-commit Hooks** — 提交前自动代码检查
- [x] **mypy 类型检查** — 静态类型验证
- [x] **UI 测试框架** — pytest-qt 集成测试
- [x] **GitHub Actions CI** — 自动化测试流水线

---

## 🏗 架构概览

```
Main.py ──▶ ui_pyside6/
               ├── main_window.py (13+ 视图/对话框)
               ├── views/industry/  (制造: 甘特图、计划表、物料…)
               ├── views/inventory/ (库存: 机库、蓝图、导入)
               ├── views/compare/   (价格对比)
               ├── views/query/     (查询: 搜索、走势图、订单)
               ├── dialogs/         (通用弹窗)
               └── workers/         (QThread 后台 UI Worker)
                  │
                  ▼
            services/  (业务逻辑层)
               ├── scoring, logistics, bom_expander, production...
               └── workers/  (ESI 数据拉取: blueprint/price/icon/contract...)
                  │
          ┌──────┴──────┐
          ▼              ▼
    database/         core/
   (SQLite × 4)      (工具 + 常量)
```

### 分层说明

| 层 | 目录 | 职责 |
|---|---|---|
| **入口** | `Main.py` | App 初始化、数据库迁移、主题加载 |
| **UI** | `ui_pyside6/` | 主窗口、20+ 视图/对话框、子包视图 |
| **业务** | `services/` | ESI 客户端、评分、库存、物流、价格历史、Woker 数据拉取 |
| **数据** | `database/` | 4 个 SQLite 库（参考/市场/用户/蓝图） |
| **工具** | `core/` | 路径管理、日志、常量、EVE 公式 |

### 关键设计决策
- **QThread Worker 模式**：所有网络请求在后台线程执行，通过 Signal 通知 UI
- **主题热切换**：`theme.py` 管理所有颜色变量；视图通过 `add_theme_listener` 注册刷新回调
- **数据库分离**：按数据性质分 4 库，`database_manager.py` 统一管理连接
- **颜色铁律**：所有颜色从 `theme` 导入，禁止 hex/rgb/颜色名；QColor 只传 theme 模块变量

---

## 🧪 测试覆盖

| 模块 | 测试文件 | 重点覆盖 |
|---|---|---|
| Core | `test_core.py`, `test_paths.py`, `test_logger.py`, `test_single_instance.py` | 路径、日志、常量、单例 |
| Services | `test_scoring.py`, `test_scoring_cache.py`, `test_scoring_service.py`, `test_scoring_core.py` | 评分逻辑、缓存 |
| Services | `test_client.py`, `test_database_manager.py`, `test_init_check.py` | HTTP 客户端、DB 连接、初始化 |
| Services | `test_inventory_manager.py`, `test_logistics_cost.py`, `test_logistics_distance.py`, `test_price_history.py` | 库存、物流距离、价格历史 |
| Services | `test_bom_expander.py`, `test_production_scheduler.py`, `test_watchlist_manager.py` | BOM、排程、关注列表 |
| Services | `test_char_config_validator.py` | 角色配置校验 |
| Workers | `test_getblueprints.py`, `test_getcontracts.py`, `test_geticon.py`, `test_getitems.py`, `test_getprices.py`, `test_getimplantdata.py`, `test_getindustry.py`, `test_sde_loader.py` | 数据拉取 Worker + SDE 导入 |
| UI Models | `test_industry_models.py`, `test_trade_models.py`, `test_models_industry.py`, `test_models_trade.py` | Qt 数据模型 |
| UI Views | `test_contract_view.py`, `test_compare_dialog.py`, `test_score_dialogs.py`, `test_export_helper.py`, `test_theme_listeners.py`, `test_procurement.py`, `test_contract_ui.py`, `test_batch_price_dialog.py` | 视图功能、主题监听、批量查价 |
| UI Views | `test_industry_view.py`, `test_inventory_view.py`, `test_ui_industry.py`, `test_ui_inventory.py`, `test_ui_main_window.py` | 集成 UI 测试 |
| UI Workers | `test_workers_getblueprints.py`, `test_workers_getimplantdata.py`, `test_workers_industry.py`, `test_workers_trade.py` | UI Worker 线程 |

---

## 🔧 技术栈

| 技术 | 用途 |
|---|---|
| **Python 3.14** | 运行时 |
| **PySide6** (Qt 6 Widgets) | 桌面 GUI |
| **aiohttp** | 异步 HTTP（ESI API） |
| **aiosqlite** | 异步 SQLite 访问 |
| **tenacity** | 请求自动重试 |
| **openpyxl** | Excel 导出 |
| **Pillow** | 图标缓存处理 |
| **pyperclip** | 剪贴板操作 |
| **tqdm** | 进度条 |
| **pytest** | 测试框架 |
| **ruff** | 代码检查 + 格式化 |
| **mypy** | 类型检查 |
| **pre-commit** | 提交前自动检查 |
| **pytest-qt** | UI 测试框架 |
| **pytest-cov** | 测试覆盖率 |

---

## 📋 关键命令

```bash
# 运行应用
python Main.py

# 热重载开发（文件变更自动重启）
python dev.py

# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_scoring.py -v

# 按名称运行测试
pytest -k "test_calc_score" -v

# 代码检查
ruff check .

# 代码格式化
ruff format .

# 构建发布包
python build_release.py
```

---

## 🔗 项目文件

- `AGENTS.md` — 开发规则与指令
- `CHANGELOG.md` — 版本更新日志
- `README.md` — 项目介绍与使用说明
- `docs/设计文档_综合版.md` — 综合设计文档
- `pyproject.toml` — Ruff / pytest 配置

---

## 📌 已知技术债务

- `_replace_systems.py` — 临时替换脚本，待清理
- `build_release.py` — PyInstaller 打包脚本，需验证兼容性
- 数据库文件（`.db`）初始化状态为空（需要运行首次初始化）
- 部分测试依赖 mock DB，集成测试覆盖不足
- 配色铁律自查命令：`grep -nE '#[0-9a-fA-F]{3,6}|color:\s*white|QColor\("' ui_pyside6/views/*.py ui_pyside6/main_window.py`

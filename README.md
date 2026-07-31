# EVE 商人助手

> 一个基于 PySide6（Qt for Python）的桌面应用程序，为 EVE Online 玩家提供多区域市场价格查询、物品搜索、制造利润计算、贸易评分等功能。

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## 📦 项目结构

```
EVE-Online-Industrial-Assistant/
├── Main.py                         # 入口点，PySide6 App
├── build_release.py                # PyInstaller 打包脚本
├── dev.py                          # 热重载开发工具
├── README.md
├── CHANGELOG.md                  # 更新日志
├── LICENSE                         # Apache 2.0
│
├── core/
│   ├── __init__.py
│   ├── paths.py                    # 所有路径集中管理（含4库路径）
│   └── logger.py                   # 日志配置
│
├── ui_pyside6/
│   ├── __init__.py
│   ├── main_window.py              # 主窗口 + 侧边导航 + 弹窗管理
│   ├── theme.py                    # One Dark Pro / One Light 主题
│   └── views/
│       ├── __init__.py
│       ├── query_view.py           # 物品查询页面（核心功能）
│       ├── estimate_view.py        # 估价页面（剪贴板粘贴→价格查询）
│       ├── industry_view.py        # 工业/制造页面
│       └── views/industry/
│           ├── __init__.py
│           ├── top_toolbar.py       # 工具栏（蓝图导入 + 双行价格设置 + 搜索候选）
│           ├── price_source_widget.py # 材料/成品独立价格来源设置组件
│           ├── plan_table.py        # 生产计划表格
│           ├── plan_edit_dialog.py  # 计划编辑对话框
│           ├── gantt_view.py        # 甘特图
│           ├── flow_layout.py       # 自动换行布局
│           ├── status_bar.py        # 底部状态栏
│           ├── action_buttons.py    # 底部操作按钮
│           ├── blueprint_dialog.py  # 所需蓝图表
│           ├── char_usage_dialog.py # 人物占用表
│           ├── cost_breakdown_dialog.py # 成本明细
│           ├── materials_dialog.py  # 材料汇总表
│           └── output_dialog.py     # 产出总表
│       ├── inventory_view.py       # 仓库/库存页面
│       ├── trade_view.py           # 贸易评分页面
│       ├── char_settings_view.py   # 角色设置页面
│       ├── init_wizard.py          # 首次启动向导
│       ├── all_items_view.py       # 全物品浏览弹窗
│       └── dialogs/
│           ├── industry_dialogs.py   # 加入制造计划对话框
│           ├── npc_seller_dialog.py  # 蓝图 NPC 卖家查询
│           └── production_wizard.py  # 产线启动小助手
│
├── services/
│   ├── client.py                   # ESI HTTP 客户端（aiohttp）
│   ├── database_manager.py         # 多库连接管理器（ATTACH DATABASE）
│   ├── scoring.py                  # 制造/贸易评分计算逻辑
│   ├── scoring_cache.py            # 评分结果缓存
│   ├── inventory_manager.py        # 库存管理 CRUD
│   ├── init_check.py               # 数据初始化状态检测
│   └── workers/
│       ├── getitems.py             # 物品数据库初始化（SDE）
│       ├── getprices.py            # 市场价格拉取（ESI，并发优化）
│       ├── geticon.py              # 图标缓存下载
│       ├── getblueprints.py        # 蓝图数据拉取
│       ├── getindustry.py          # 工业系统成本指数拉取
│       └── getimplantdata.py       # 工业植入体数据拉取
│
├── database/
│   ├── reference.db                # 静态参考数据（item, industry_* 等）
│   ├── market.db                   # 市场价格快照
│   ├── user.db                     # 用户数据（机库、库存、生产计划）
│   └── blueprint.db                # 蓝图数据（activities, materials 等）
│
├── scripts/
│   └── migrate_split_db.py         # 单库→4库迁移脚本
│
├── data/
│   ├── search_history.json         # 搜索历史
│   ├── settings.json               # 用户设置（主题、价格更新等）
│   ├── update_progress.json        # 更新进度
│   ├── window_geometry.json        # 窗口状态
│   ├── char_config.json            # 角色配置（多角色）
│   └── caches/icons/               # 图标缓存目录
│
├── EVE——docs/
│   ├── 01-架构概览.md               # 精简版设计文档
│   ├── 02-功能规格.md
│   ├── 03-UI设计.md
│   └── 04-开发路线图.md
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_contract_view.py
│   ├── test_core.py
│   ├── test_database_manager.py
│   ├── test_export_helper.py
│   ├── test_logger.py
│   ├── test_logistics.py
│   ├── test_paths.py
│   ├── test_price_history.py
│   ├── test_procurement.py
│   ├── test_scoring.py
│   ├── test_scoring_cache.py
│   ├── test_scoring_core.py
│   ├── test_theme_listeners.py
│   └── test_watchlist_manager.py
│
├── .pre-commit-config.yaml         # Pre-commit hooks 配置
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions CI
├── CLAUDE.md                       # Claude Code 项目约束
├── AUDIT-20260731.md               # 2026-07-31 代码审计报告
│
├── pyproject.toml                  # 项目配置 + 依赖声明（uv 管理）
└── uv.lock                         # 依赖锁文件（uv sync 生成）
```

---

## 🚀 快速开始

### 环境要求
- Python 3.14+
- Windows / macOS / Linux

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant.git
cd EVE-Online-Industrial-Assistant

# 创建虚拟环境并安装依赖（含 dev 测试工具）
# 需要先安装 uv（官方安装脚本）：
#   Windows (PowerShell): powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
#   macOS / Linux:        curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --dev

# 激活虚拟环境
# Windows (CMD/PowerShell):
.venv\Scripts\activate
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS / Linux:
source .venv/bin/activate

# 运行开发版本
python Main.py
```

> 首次启动会自动：
> 1. 创建 SQLite 数据库
> 2. 从 SDE 拉取物品数据
> 3. 从 ESI 拉取吉他（The Forge）市场价格
> 4. 缓存物品图标

### 打包为 EXE

```bash
python build_release.py
```

输出目录：`dist/EVE商人助手/`

---

## ✅ 已完成功能

### 一、物品查询（核心功能）

| 功能 | 说明 |
|------|------|
| 🔍 **模糊搜索** | 输入中/英文名实时下拉候选 |
| 📂 **类别搜索** | 输入类别名自动展示该类别所有物品 |
| 📊 **结果表格** | 显示图标、ID、中/英文名、类别、买单/卖单/均价、体积 |
| 🔢 **订单数量** | 价格后括号显示该方向订单数量 |
| 📋 **单击复制** | 单击任意价格自动复制到剪贴板 |
| 📖 **深度订单** | 双击行展开 Top5 买单 / Top5 卖单（实时拉取） |
| ⬆️ **列排序** | 单击表头按 ID、价格、均价等排序 |
| 🕐 **搜索历史** | 聚焦搜索框显示最近 20 条记录 |
| 🚨 **倒挂高亮** | 买单高于卖单时行背景高亮 |
| 📊 **价格走势图** | 订单弹窗→走势图按钮，历史价格趋势可视化 |
| 📋 **批量导出** | 查询结果导出为 CSV/Excel（查询页、全物品浏览页） |

### 二、贸易评分系统

| 功能 | 说明 |
|------|------|
| ⭐ **利润评分** | 基于跨区域价差、日均成交量、税收综合评分 |
| 🌍 **跨区域价格** | 支持遍历多个区域评估最优贸易路线 |
| 📈 **每日真实利润** | 考虑税费、经纪费后的净利评估 |
| 👤 **多角色支持** | 管理多个角色的技能、所在地和资金配置 |
| 📊 **排序与筛选** | 按评分、利润率、成交量等多维度排序 |

### 三、价格数据（基础设施）

| 功能 | 说明 |
|------|------|
| ⚡ **高速拉取** | 并发拉取 ESI 分页数据，3-5 秒完成全市场订单（优化前 20-30 秒） |
| 🔄 **自动更新** | 启动检查价格时效，过期自动更新；支持在系统设置中关闭/开启，可自定义间隔（0-1440 分钟） |
| 📈 **实时进度** | 底部状态栏显示进度条 + 阶段文字 |
| 🗄️ **物品数据库** | 从 SDE 拉取中/英文名、类别、体积、图标 |
| 🖼️ **图标缓存** | 本地缓存物品图片 |
| 🔔 **价格变化检测** | 关注列表 60s 定时器自动检测价格变化并通知 |

### 四、全局 UI

| 功能 | 说明 |
|------|------|
| 🎨 **双主题** | One Dark Pro / One Light，运行时一键切换，偏好自动保存 |
| 📌 **紧凑导航** | 侧边栏导航（估价、查询、制造、贸易、仓库） |
| 📊 **底部状态栏** | 价格更新时间、更新按钮、进度条、自动更新开关 |
| ⚙️ **系统设置** | 弹窗式设置面板：主题切换、自动更新开关、更新间隔、数据初始化、关于 |

### 五、工业制造

| 功能 | 说明 |
|------|------|
| 📋 **生产计划管理** | 添加、编辑、删除生产计划，表格展示 19 列完整信息 |
| 🔍 **蓝图搜索候选** | 输入框实时搜索建议，支持中/英文名称模糊匹配，选择即添加 |
| 🏷️ **双行价格设置** | 材料/成品独立配置 Hub 来源、卖价/买价、倍率系数 |
| ⚡ **定向价格刷新** | 仅拉取活跃计划涉及物品，5 分钟缓存 TTL + 并发 50 请求 |
| 📊 **数据视图/甘特图** | 表格数据视图和产线甘特图一键切换 |
| 📋 **多种汇总弹窗** | 采购小助手、所需蓝图表、材料总表、产出总表、人物占用 |
| 📦 **自动入库** | 成品制造完成后自动存入指定机库 |

---

## 🔲 待开发功能

| 功能 | 说明 |
|------|------|
| 🌐 **多语言** | 英文 UI 支持（待开发） |

---

## 🗄️ 数据库架构

数据库按数据生命周期拆分为 4 个独立 SQLite 文件（`database/` 目录下），通过 `services/database_manager.py` 的 `ATTACH DATABASE` 机制支持跨库联合查询。

### `reference.db` — 静态参考数据（SDE，只读，~4 MB）

| 表 | 说明 |
|----|------|
| `item` | 物品基础信息（16 字段：type_id, 中/英文名, 组, 市场分类, 体积, 图标等） |
| `market_tree` | 市场分类树 |
| `industry_system_costs` | 工业系统成本指数 |
| `item_dogma` | 物品 dogma 属性 |

### `market.db` — 市场价格数据（频繁覆写，~18 MB）

| 表 | 字段 | 说明 |
|----|------|------|
| `market_prices` | type_id, buy_price, sell_price, buy_volume, sell_volume, fetch_time | 实时订单价格快照 |
| `market_volume_snapshots` | type_id, volume, fetch_time | 成交量快照 |

### `blueprint.db` — 蓝图数据（只读）

| 表 | 说明 |
|----|------|
| `blueprint_activities` | 蓝图活动信息 |
| `blueprint_materials` | 蓝图材料清单 |
| `blueprint_products` | 蓝图产出 |
| `blueprint_skills` | 蓝图所需技能 |

### `user.db` — 用户数据（增删改）

| 表 | 说明 |
|----|------|
| `hangars` | 机库定义（矿仓/组件仓/产品仓等） |
| `inventory_items` | 库存物品（type_id, 数量, 加权平均成本） |
| `user_blueprints` | 用户拥有的蓝图（ME/TE/数量） |
| `production_plans` | 生产计划 |
| `user_skills` | 角色技能 |

> 旧版单库 `items.db` 已通过迁移脚本拆分为以上 4 库，原文件保留不动作为备份。

---

## 🧪 测试

| 指标 | 数值 |
|------|------|
| 📊 **测试总数** | 657 个 |
| 🔧 **框架** | pytest |
| 📁 **测试目录** | `tests/` |
| 🏃 **运行命令** | `pytest` |

### 测试文件

覆盖主要模块（完整清单以 `tests/` 目录为准，pytest 自动收集）：

| 文件 | 说明 |
|------|------|
| `test_core.py` / `test_paths.py` / `test_logger.py` | 核心工具层测试 |
| `test_database_manager.py` | 数据库连接管理器测试 |
| `test_scoring.py` / `test_scoring_core.py` / `test_scoring_service.py` | 评分计算测试 |
| `test_personal_margin.py` | 个人利润率测试 |
| `test_bom_expander.py` | BOM 展开测试 |
| `test_refining_service.py` | 精炼价值测试 |
| `test_manufacturing_calculator_golden.py` | 制造公式金标准（游戏实测数值锁定） |
| `test_schema_migrations.py` / `test_migration_recovery.py` | Schema 迁移与失败恢复测试 |
| `test_client.py` / `test_getprices.py` | ESI 客户端与价格拉取测试 |
| `test_price_history.py` | 价格走势图数据测试 |
| `test_watchlist_manager.py` | 关注列表与价格变化检测测试 |
| `test_contract_models.py` / `test_contract_ui.py` | 合同视图测试 |
| `test_logistics_cost.py` / `test_logistics_distance.py` | 物流计算测试 |
| `test_theme_listeners.py` | 主题监听模式测试 |
| `test_ui_industry.py` / `test_ui_inventory.py` / `test_ui_main_window.py` | UI 冒烟测试 |
| `test_workers_*.py` | 后台 Worker 测试 |

---

## 🌐 数据源

### SDE（Static Data Export）
- 基础地址：`https://sde.jita.space/latest`
- 用途：物品名称、组信息、市场分类、图标

### ESI（EVE Swagger Interface）
- 基础地址：`https://esi.evetech.net/latest`
- 用途：市场价格、空间站名称
- 区域：伏尔戈（The Forge，ID: 10000002）

---

## 🔧 技术栈

| 技术 | 用途 |
|------|------|
| [PySide6](https://www.qt.io/qt-for-python) | Python UI 框架（Qt6） |
| [aiohttp](https://docs.aiohttp.org/) | 异步 HTTP 请求 |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | 异步 SQLite 操作 |
| [tenacity](https://tenacity.readthedocs.io/) | 请求重试 + 指数退避 |
| [PyInstaller](https://pyinstaller.org/) | 打包为可执行文件 |
| mypy | 类型检查 |
| pre-commit | 提交前自动检查 |
| pytest-qt | UI 测试框架 |
| pytest-cov | 测试覆盖率 |

## 📝 贡献指南

欢迎提交 Issue 和 Pull Request！

- 提交 PR 前请确保代码风格符合项目规范
- PR 描述请使用中文（参见 [PR 模板](.github/pull_request_template.md)）
- 提交信息请使用中文

---

## 📄 许可

本项目基于 **Apache License 2.0** 协议开源，详情请参见 [LICENSE](LICENSE) 文件。

EVE Online 及相关商标属于 CCP Games。数据来源于 ESI 和 SDE，使用请遵守 EVE Online 第三方开发者协议。

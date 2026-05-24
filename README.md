# EVE 商人助手

> 一个基于 PySide6（Qt for Python）的桌面应用程序，为 EVE Online 玩家提供多区域市场价格查询、物品搜索、制造利润计算、贸易评分等功能。

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## 📦 项目结构

```
EVE-Online-Industrial-Assistant/
├── Main.py                         # 入口点，PySide6 App
├── build_release.py                # 打包脚本
├── README.md
├── LICENSE                         # Apache 2.0
│
├── core/
│   ├── __init__.py
│   ├── paths.py                    # 所有路径集中管理
│   ├── logger.py                   # 日志配置
│   └── scoring.py                  # 贸易/制造评分引擎
│
├── ui_pyside6/
│   ├── __init__.py
│   ├── main_window.py              # 主窗口 + 弹窗管理
│   ├── theme.py                    # 主题与样式
│   └── views/
│       ├── __init__.py
│       ├── query_view.py           # 物品查询页面
│       ├── industry_view.py        # 工业/制造页面
│       ├── inventory_view.py       # 仓库/库存页面
│       ├── trade_view.py           # 贸易评分页面
│       ├── char_settings_view.py   # 角色设置页面
│       ├── init_wizard.py          # 首次启动向导
│       └── all_items_view.py       # 全物品浏览弹窗
│
├── services/
│   ├── client.py                   # ESI HTTP 客户端
│   ├── data/                       # 运行时数据
│   └── workers/
│       ├── getitems.py             # 物品数据库初始化（SDE）
│       ├── getprices.py            # 市场价格拉取（ESI，并发优化）
│       ├── geticon.py              # 图标缓存下载
│       └── getblueprints.py        # 蓝图数据
│
├── database/
│   └── items.db                    # SQLite 数据库
│
├── data/
│   ├── search_history.json         # 搜索历史
│   ├── update_progress.json        # 更新进度
│   ├── window_geometry.json        # 窗口状态
│   ├── char_config.json            # 角色配置（多角色）
│   └── caches/icons/               # 图标缓存目录
│
├── .github/
│   └── pull_request_template.md    # PR 模板
│
└── requirements.txt                # Python 依赖
```

---

## 🚀 快速开始

### 环境要求
- Python 3.10+
- Windows / macOS / Linux

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant.git
cd EVE-Online-Industrial-Assistant

# 创建虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows (CMD/PowerShell):
.venv\Scripts\activate
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS / Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

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
| 🔄 **自动更新** | 启动检查价格是否在 30 分钟内，过期自动更新 |
| 📈 **实时进度** | 底部状态栏显示进度条 + 阶段文字 |
| 🗄️ **物品数据库** | 从 SDE 拉取中/英文名、类别、体积、图标 |
| 🖼️ **图标缓存** | 本地缓存物品图片 |

### 四、全局 UI

| 功能 | 说明 |
|------|------|
| 🎨 **暗色主题** | #1a1a2e 深蓝主题 |
| 📌 **紧凑导航** | 侧边栏导航（查询、贸易、工业、仓库、角色设置） |
| 📊 **底部状态栏** | 价格更新时间、更新按钮、进度条 |

---

## 🔲 待开发功能

| 功能 | 说明 |
|------|------|
| 🔧 **制造利润计算** | 输入蓝图/材料，计算制造成本与利润 |
| 📦 **仓库管理** | 库存查询、导入与导出 |
| ⚙️ **设置页** | 数据库管理、代理配置、更新日志 |
| 📊 **价格走势图** | 历史价格趋势可视化 |

### 已砍掉的功能
- ❌ 价格监控（需历史数据 + 图表）
- ❌ 运输分析（已合并入贸易评分）
- ❌ 行星工业
- ❌ 忠诚点价值

---

## 🗄️ 数据库结构

### `item` 表（物品基础数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| `type_id` | INTEGER PK | 物品 ID |
| `en_name` | TEXT | 英文名 |
| `zh_name` | TEXT | 中文名 |
| `group_id` | INTEGER | 组 ID |
| `en_group_name` | TEXT | 英文组名 |
| `zh_group_name` | TEXT | 中文组名 |
| `market_group_id` | INTEGER | 市场分类 ID |
| `en_market_group_name` | TEXT | 英文市场分类名 |
| `zh_market_group_name` | TEXT | 中文市场分类名 |
| `volume` | REAL | 体积（m³） |
| `iconID` | INTEGER | 图标 ID |

### `market_prices` 表（市场价格快照）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTO | 自增主键 |
| `type_id` | INTEGER | 物品 ID |
| `buy_price` | REAL | 最高买单价格 |
| `sell_price` | REAL | 最低卖单价格 |
| `buy_volume` | BIGINT | 买单数量 |
| `sell_volume` | BIGINT | 卖单数量 |
| `fetch_time` | TIMESTAMP | 抓取时间（默认当前时间） |

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

## 📝 贡献指南

欢迎提交 Issue 和 Pull Request！

- 提交 PR 前请确保代码风格符合项目规范
- PR 描述请使用中文（参见 [PR 模板](.github/pull_request_template.md)）
- 提交信息请使用中文

---

## 📄 许可

本项目基于 **Apache License 2.0** 协议开源，详情请参见 [LICENSE](LICENSE) 文件。

EVE Online 及相关商标属于 CCP Games。数据来源于 ESI 和 SDE，使用请遵守 EVE Online 第三方开发者协议。
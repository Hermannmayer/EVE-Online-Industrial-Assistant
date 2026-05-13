# EVE 商人助手

> 一个基于 Flet（Python UI 框架）的桌面应用程序，为 EVE Online 玩家提供吉他（Jita）市场价格查询、物品搜索、制造利润计算等功能。

---

## 📦 项目结构

```
EVE-Online-Industrial-Assistant/
├── Main.py                         # 入口点，Flet App
├── build_release.py                # 打包脚本
├── EVE商人助手.spec                 # PyInstaller 配置
├── README.md                       # 本文件
│
├── core/
│   ├── __init__.py
│   └── paths.py                    # 所有路径集中管理
│
├── ui/
│   ├── __init__.py
│   ├── config.py                   # 全局配置（字体、ESI 地址等）
│   └── views/
│       ├── __init__.py
│       ├── query_view.py           # 查询页面（已实现）
│       ├── manufacturing_view.py   # 制造/精炼页面（占位符）
│       ├── market_view.py          # 贸易页面（已删除功能）
│       └── inventory_view.py       # 仓库页面（待修复）
│
├── services/
│   ├── data/
│   │   └── update_progress.json    # 进度文件（运行时）
│   └── workers/
│       ├── getitems.py             # 物品数据库初始化（SDE）
│       ├── getprices.py            # 市场价格拉取（ESI，已优化并发）
│       └── geticon.py              # 图标缓存下载
│
├── database/
│   └── items.db                    # SQLite 数据库
│
├── data/
│   ├── search_history.json         # 搜索历史
│   ├── update_progress.json        # 更新进度
│   ├── window_geometry.json        # 窗口状态
│   └── caches/icons/              # 图标缓存目录
│
└── documents/
    ├── 界面设计.md
    ├── cursor_.md
    └── EVE_ESI_API.xlsx
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

### 二、价格数据（基础设施）

| 功能 | 说明 |
|------|------|
| ⚡ **高速拉取** | 并发拉取 ESI 分页数据，3-5 秒完成全市场订单（优化前 20-30 秒） |
| 🔄 **自动更新** | 启动检查价格是否在 30 分钟内，过期自动更新 |
| 📈 **实时进度** | 底部状态栏显示进度条 + 阶段文字 |
| 🗄️ **物品数据库** | 从 SDE 拉取中/英文名、类别、体积、图标 |
| 🖼️ **图标缓存** | 本地缓存物品图片 |

### 三、全局 UI

| 功能 | 说明 |
|------|------|
| 🎨 **暗色主题** | #1a1a2e 深蓝主题 |
| 📌 **紧凑导航** | 侧边栏 4 项（查询、制造/精炼、仓库、设置） |
| 📊 **底部状态栏** | 价格更新时间、更新按钮、进度条 |

---

## 🔲 待开发功能

### 🔧 第一阶段（高优先级）

| 功能 | 说明 |
|------|------|
| 🏭 **估价与精炼** | 输入蓝图/材料，计算制造成本与利润 |
| 🔧 **制造业** | 制造配方查询、材料需求计算（与估价合并） |
| 📦 **仓库修复** | 修复 `inventory_view.py` 查询不存在的表，改为查 `item`+`market_prices` |
| ⚙️ **设置页** | 数据库管理、代理配置、更新日志 |

### 📐 已砍掉的功能
- ❌ 价格监控（需历史数据 + 图表）
- ❌ 运输分析（需跨区域数据）
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
| [Flet](https://flet.dev/) | Python UI 框架（Flutter 底层） |
| [aiohttp](https://docs.aiohttp.org/) | 异步 HTTP 请求 |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | 异步 SQLite 操作 |
| [tenacity](https://tenacity.readthedocs.io/) | 请求重试 + 指数退避 |
| [PyInstaller](https://pyinstaller.org/) | 打包为可执行文件 |

---

## 📝 代码规范

| 项目 | 规范 |
|------|------|
| 文件命名 | 小写蛇形（`query_view.py`） |
| 类命名 | 大驼峰（`QueryPage`） |
| 函数/方法 | 小写蛇形（`_do_search`） |
| 常量 | 全大写蛇形（`CONCURRENCY`） |
| 异步 | 所有网络/DB 操作使用 `async/await` |
| UI 异步 | 通过 `page.run_task()` 启动 |

---

## 📄 许可

本项目仅供学习交流使用。EVE Online 及相关商标属于 CCP Games。数据来源于 ESI 和 SDE，使用请遵守 EVE Online 第三方开发者协议。
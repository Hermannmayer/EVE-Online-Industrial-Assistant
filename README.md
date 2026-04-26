# EVE 工业助手  开发文档

> 版本：0.2 - 基础框架已搭建
> 目标：为 EVE Online 玩家提供制造、市场、资产管理的桌面辅助工具
> 技术栈：Python 3.10+ / tkinter / SQLite3 / aiohttp

---

## 1. 项目概述

本项目旨在使用 Python 开发 EVE 工业辅助工具，帮助玩家快速查询物品信息、计算制造成本、分析市场利润、追踪库存与蓝图。

**核心设计原则：**
- 使用 Python 标准库 `tkinter` 构建 GUI，零额外 GUI 依赖，保证跨平台兼容性。
- 数据源采用 `sde.jita.space` 提供的 REST API，自动获取最新的 SDE 物品数据（含中英文名称）。
- 异步请求使用 `aiohttp` + `asyncio`，数据抓取通过网络完成，无需本地 SDE 文件。
- 业务逻辑与界面分离，便于测试和维护。

---

## 2. 功能需求

### 2.1 物品查询系统（已实现）
- 物品模糊搜索（中/英文名称匹配）
- 显示物品 Type ID、中英文名称、分组、体积
- 从本地 SQLite 数据库查询，响应即时

### 2.2 仓库管理（基础实现）
- 物品仓库：通过剪贴板读取 Eve 客户端数据并导入
- 蓝图仓库：通过剪贴板读取蓝图数据并导入
- 数据存储与展示

### 2.3 制造系统（待实现）
- 蓝图管理：显示蓝图信息（材料/时间效率、制造/发明需求）
- 材料计算：根据蓝图和运行次数计算所需矿物、行星产物、组件
- 成本核算：基于实时市场价格计算制造成本和利润
- 生产计划：生成制造队列，估算完工时间

### 2.4 市场交易（待实现）
- 市场价格查询（买价/卖价，取自 ESI 或本地缓存）
- 订单利润分析：对比制造/采购成本与售价
- 价格历史图表

### 2.5 行星开发 (PI)（待实现）
- 设施产出计算（基础工厂、高级工厂、高科技工厂）
- 行星资源需求与税收计算
- 运输体积/重量估算

### 2.6 系统辅助（待实现）
- 角色技能加载（技能对制造时间/成本的修正）
- 设施成本设置（POS/工程复合体加成）
- 数据更新管理（手动/自动更新市场价格）

---

## 3. 系统架构

采用分层架构（表现层 → 业务逻辑层 → 数据访问层），配合数据模型层与工具层。

当前项目实际结构分为：`ui/`（界面）、`services/`（业务）、`data/`（数据访问）、`core/`（工具）四层。

```
+-------------------+       +-------------------+       +-------------------+
|    UI Layer       | --->  |   Service Layer    | --->  |   Data Layer      |
| (tkinter Views)   |       | (Business Logic)   |       | (SQLite / REST)   |
+-------------------+       +-------------------+       +-------------------+
        |                           |
        v                           v
+-------------------+       +-------------------+
|    Core / Utils    |       |    Workers         |
| (类型定义、工具函数)|       | (多进程计算/抓取)  |
+-------------------+       +-------------------+
```

各层职责：

| 层 | 职责 | 核心文件 |
|----|------|----------|
| UI Layer | 窗口、控件、事件绑定、数据展示，调用 Service 获取数据 | `main.py`, `ui/views/*.py` |
| Service Layer | 核心计算（制造成本、利润）、市场分析、数据更新调度 | `services/*.py` |
| Data Layer | 本地 SQLite 数据库读写、REST API 请求、缓存管理 | `data/*.py`, `getitems.py` |
| Core | 通用类型定义、常量、工具函数 | `core/*.py` |

---

## 4. 技术选型

| 组件 | 选择 | 说明 |
|------|------|------|
| 编程语言 | Python 3.10+ | 稳定版本，异步特性成熟 |
| GUI 框架 | tkinter | Python 标准库，无需额外安装，天然跨平台 |
| 本地数据库 | SQLite3 | 标准库自带，免安装，适合单机应用 |
| HTTP 异步库 | aiohttp | 异步请求数据源，避免阻塞 |
| 数据源 | sde.jita.space REST API | 提供最新 SDE 数据，含中/英文名称、分组 |
| 字体 | Microsoft YaHei UI / PingFang SC | 支持中文显示，根据操作系统选择 |
| 打包工具 | PyInstaller | 生成单一可执行文件 |

---

## 5. 项目文件结构

```
eve/
├── main.py                     # 程序入口（tkinter 主窗口 + 导航）
├── getitems.py                 # 数据初始化脚本（从 REST API 抓取物品数据）
├── README.md                   # 项目说明与工作清单
│
├── ui/                         # 用户界面层
│   ├── config.py               # UI 配置（数据库路径、字体设置）
│   ├── views/                  # 功能页面
│   │   ├── __init__.py         # 页面导出
│   │   ├── query_view.py       # 物品查询页面（已实现）
│   │   ├── manufacturing_view.py  # 工业制造页面（骨架）
│   │   ├── market_view.py      # 市场贸易页面（骨架）
│   │   └── inventory_view.py   # 仓库管理页面（基础实现，含剪贴板导入）
│   └── components/             # 可复用 UI 控件
│       └── (待添加)
│
├── services/                   # 业务逻辑层
│   ├── workers/                # CPU 密集型工作函数
│   │   ├── compute_tree.py     # 制造树展开（占位）
│   │   └── price_worker.py     # 价格聚合计算（占位）
│   └── (待添加：manufacturing, market, scheduler 等)
│
├── data/                       # 数据访问层
│   ├── repositories/           # 数据仓库封装
│   │   └── (待添加)
│   ├── esi/                    # EVE ESI 接口层
│   │   └── (待添加)
│   └── caches/                 # 缓存存储
│       └── (待添加)
│
├── core/                       # 核心工具
│   └── (待添加：类型定义、工具函数)
│
├── database/                   # 数据库
│   └── items.db                # SQLite 数据库文件
│
├── documents/                  # 文档
│   ├── # EVE 工业助手 (Python版) 开发文档.md
│   └── cursor_.md
│
└── tests/                      # 单元测试
    └── (待添加)
```

---

## 6. 数据库设计

### 6.1 本地 SQLite 表结构

当前数据库 `database/items.db` 包含一张核心物品表：

```sql
-- 物品表（数据来自 sde.jita.space REST API）
CREATE TABLE IF NOT EXISTS item (
    type_id               INTEGER PRIMARY KEY,
    en_name               TEXT,
    zh_name               TEXT,
    group_id              INTEGER,
    en_group_name         TEXT,
    zh_group_name         TEXT,
    market_group_id       INTEGER,
    en_market_group_name  TEXT,
    zh_market_group_name  TEXT,
    volume                REAL,
    iconID                INTEGER
);
```

**字段说明：**
- `type_id`：EVE 物品唯一标识
- `en_name` / `zh_name`：物品中英文名称
- `group_id` / `en_group_name` / `zh_group_name`：物品分组信息
- `market_group_id` / `en_market_group_name` / `zh_market_group_name`：市场分组信息
- `volume`：物品体积（m³）
- `iconID`：物品图标 ID

### 6.2 数据初始化流程

1. 运行 `python getitems.py` 启动数据抓取脚本。
2. 脚本从 `sde.jita.space/latest` 获取所有物品 Type ID。
3. 对每个 Type ID 异步请求详细信息，并发数 50，批量写入 SQLite。
4. 自动过滤无 `market_group_id` 的物品，仅保留可交易物品。
5. 数据抓取后 `items.db` 可被主程序直接使用。

---

## 7. 核心模块说明

### 7.1 物品查询页面 `ui/views/query_view.py`（已实现）

功能：
- 输入框中/英文名称模糊搜索
- 查询本地 `items.db` 数据库
- 显示 Type ID、中英文名称、分组名称、体积

实现方式：直接使用 `sqlite3` 同步查询 + `tkinter.Text` 展示结果。

### 7.2 仓库管理页面 `ui/views/inventory_view.py`（基础实现）

功能：
- 物品仓库子页面：读取剪贴板中 Eve 客户端导出的物品数据
- 蓝图仓库子页面：读取剪贴板中的蓝图数据
- 数据展示在 `tkinter.Text` 控件中

### 7.3 数据获取脚本 `getitems.py`

功能：
- 从 `sde.jita.space/latest` REST API 抓取物品数据
- 使用 `aiohttp` + `asyncio` 异步并发请求
- 使用 `aiosqlite` 批量写入数据库
- 带重试机制（`tenacity` 库）
- 带进度条显示（`tqdm` 库）
- 自动过滤无市场分组的物品

### 7.4 主窗口 `main.py`

- 使用 `tkinter.Tk` 创建主窗口（1280×720）
- 顶部导航栏包含 4 个按钮：查询物品、工业、贸易、仓库
- 使用 `tkinter.Frame` + `tkraise()` 实现页面切换
- 当前 4 个页面：`QueryPage`, `IndustryPage`, `TradePage`, `WarehousePage`

### 7.5 UI 配置 `ui/config.py`

- 根据操作系统选择中文字体（Windows: Microsoft YaHei UI，其他: PingFang SC）
- 自动计算数据库文件路径

---

## 8. 开发阶段与里程碑

### 阶段一：基础架构 + 物品数据（✅ 已完成）

- [x] 创建项目结构，初始化 Git
- [x] 实现 `main.py` 主窗口框架（tkinter）
- [x] 实现 `getitems.py` 数据抓取脚本
- [x] 实现物品查询页面 `query_view.py`
- [x] 实现仓库管理页面基础框架（含剪贴板导入）
- [x] 实现 4 页面导航切换

### 阶段二：市场查询模块（待开始）

- [ ] 实现 ESI 客户端封装（`data/esi/client.py`）
- [ ] 实现市场订单查询页面
- [ ] 实现价格缓存机制
- [ ] 显示买价/卖价及简单分析

### 阶段三：制造计算模块（待开始）

- [ ] 设计蓝图数据模型与数据库表
- [ ] 实现材料展开与制造树计算
- [ ] 实现成本与利润计算
- [ ] 创建制造计算界面

### 阶段四：资产管理 + 行星开发（待开始）

- [ ] 完善仓库数据导入与持久化
- [ ] 资产估值功能
- [ ] 行星设施产出计算器

### 阶段五：优化与打包（待开始）

- [ ] UI 美化与响应优化
- [ ] 自动更新市场数据定时器
- [ ] 使用 PyInstaller 打包成可执行文件
- [ ] 编写用户文档

---


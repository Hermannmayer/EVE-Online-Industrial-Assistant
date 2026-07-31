# 项目简介

## EVE 工业助手是什么

EVE Online 工业制造助手是一个基于 **PySide6**（Qt6 for Python）的开源桌面应用程序，为 [EVE Online](https://www.eveonline.com/) 玩家提供工业制造全链路支持：

- 🔍 **物品查询** — 多区域市场价格查询、深层次订单、价格走势
- ⭐ **制造利润计算** — 生产计划管理、蓝图搜索、精确成本核算
- 📦 **BOM 递归展开** — T2/T3 产业链完整材料树
- 🚚 **物流规划** — 跨区域运费估算、利润评估
- 🏭 **精炼计算** — 矿物精炼产出与效率
- 📊 **贸易评分** — 多维度商品贸易机会评分
- 🗄️ **库存管理** — 机库、蓝图、加权平均成本

## 技术栈

| 组件 | 技术 |
|------|------|
| UI 框架 | PySide6（Qt6 Widgets） |
| 异步 HTTP | aiohttp |
| 数据库 | aiosqlite + 4 个分离的 SQLite 库 |
| 请求重试 | tenacity |
| 打包 | PyInstaller |
| 依赖管理 | uv |
| 代码质量 | ruff（lint + format）+ mypy（类型检查）|
| 测试 | pytest + pytest-qt + pytest-cov |

## 数据库架构

按数据生命周期拆分为 4 个独立 SQLite 文件（`database/` 目录下）：

| 库名 | 用途 | 预估大小 |
|------|------|----------|
| `reference.db` | 静态参考数据（SDE 物品、市场分类、系统成本指数） | ~4 MB |
| `market.db` | 市场价格快照（频繁覆写） | ~18 MB |
| `blueprint.db` | 蓝图数据（活动、材料、产出、技能） | 中等 |
| `user.db` | 用户数据（机库、库存、蓝图、生产计划、角色技能） | 增长 |

通过 `services/database_manager.py` 的 `ATTACH DATABASE` 机制支持跨库联合查询。

## 项目状态

- **版本阶段**：当前 v0.7.0，功能与 API 均可能随时变化
- **测试**：661+ 个测试，使用 pytest 运行
- **许可证**：Apache License 2.0
- **来源数据**：ESI（市场价格）+ SDE（物品参考数据）

> ⚠️ 本项目为半成品开发阶段，部分功能仍在完善中。欢迎 [提交 Issue](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/issues) 或 Pull Request。

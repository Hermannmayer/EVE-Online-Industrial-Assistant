# EVE-Online-Industrial-Assistant

## 项目概述
EVE Online 工业制造助手，使用 PySide6 + SQLite 构建的桌面应用。

## 代码风格和约束

### 语言和版本
- Python 3.14+
- PySide6 6.8+
- 使用 ruff 进行格式化和 linting

### 禁止事项
- ❌ Python 2 语法（如 `except ExcType, var:`）
- ❌ 裸 `except: pass`（必须记录日志或重新抛出）
- ❌ 超过 30 行的重复代码（必须提取公共函数）
- ❌ 硬编码常量（使用 `core/constants.py` 中的定义）
- ❌ SQL F-string 拼接（使用参数化查询或转义引号）
- ❌ 模块级全局 DB 单例（使用依赖注入）

### 必须遵守
- ✅ 所有异步代码使用 `async with` 管理资源
- ✅ 所有 SQL 使用参数化查询
- ✅ 所有依赖使用 `~=` 固定版本
- ✅ 新代码添加类型注解
- ✅ 新功能添加测试（覆盖率 > 70%）
- ✅ 每个 except 块记录日志 `logger.exception(...)`

### 架构约束
- 三层分离：`core/`（工具）→ `services/`（业务）→ `ui_pyside6/`（UI）
- 依赖注入使用 `core/container.py`
- 4 库独立管理：`reference.db` / `market.db` / `user.db` / `blueprint.db`
- 数据库管理使用 `services/database_manager.py`
- UI 组件使用 Qt Worker 处理异步任务（QThread + Signal 模式）
- **配色铁律**：所有颜色从 `ui_pyside6.theme` 导入，禁止 hex/rgb/颜色名（违反将导致亮/暗主题失效）
- 新 UI 组件必须 `add_theme_listener` + 实现 `_on_theme_changed`

### 测试要求
- 单元测试使用 `pytest`
- UI 测试使用 `pytest-qt`
- 集成测试使用真实数据库（temp_db fixture）
- 运行：`pytest tests/ -v`

### 提交前检查清单
1. ✅ `ruff check .` 无错误
2. ✅ `mypy` 无类型错误
3. ✅ `pytest` 全部通过
4. ✅ `/code-review` 无严重问题
5. ✅ 无新增的 `except: pass`

### 安全要求
- ✅ 不硬编码 API 密钥或密码
- ✅ 使用 `yaml.safe_load()` 加载 YAML
- ✅ 对用户输入进行验证
- ✅ 使用参数化查询防止 SQL 注入

## 常用命令

### 开发
```bash
python dev.py              # 启动开发服务器（支持热重载）
python Main.py             # 启动生产版本
```

### 测试
```bash
pytest tests/ -v           # 运行所有测试
pytest tests/ -v --cov=.   # 运行测试并生成覆盖率报告
```

### Linting
```bash
ruff check .               # 检查代码风格
ruff check . --fix         # 自动修复
mypy .                     # 类型检查
```

### 预提交
```bash
pre-commit run --all-files # 运行所有 pre-commit 检查
```

## 项目结构

```
├── Main.py                  # 应用入口
├── dev.py                   # 热重载开发模式
├── build_release.py         # PyInstaller 打包
├── _replace_systems.py      # 临时替换脚本
│
├── core/                    # 工具层
│   ├── constants.py         # 常量定义
│   ├── container.py         # 依赖注入
│   ├── eve_formulas.py      # EVE 公式计算
│   ├── hot_reload.py        # 热重载支持
│   ├── logger.py            # 日志配置
│   ├── paths.py             # 路径管理
│   └── single_instance.py   # 单例运行锁
│
├── services/                # 业务逻辑层
│   ├── database_manager.py  # 4 库统一管理
│   ├── client.py            # ESI HTTP 客户端
│   ├── scoring.py           # 评分算法
│   ├── scoring_service.py   # 评分服务类
│   ├── inventory_manager.py # 库存管理
│   ├── logistics.py         # 物流距离计算
│   ├── price_history.py     # 价格历史
│   ├── bom_expander.py      # BOM 展开
│   ├── production_scheduler.py # 生产排程
│   ├── watchlist_manager.py # 关注列表
│   ├── char_config_validator.py # 角色配置校验
│   ├── init_check.py        # 初始化检查
│   └── workers/             # 数据拉取 Worker
│       ├── getcontracts.py
│       ├── getindustry.py
│       └── getprices.py
│
├── tools/                   # 独立初始化工具
│   ├── init.py              # CLI: python tools/init.py
│   ├── downloaders/         # 初始化下载器（items/blueprints/SDE/图标/植入体）
│   └── requirements.txt     # 额外依赖（pyyaml, aiosqlite）
│
├── ui_pyside6/              # UI 层
│   ├── main_window.py       # 主窗口（侧边导航、多 Tab）
│   ├── main_window_fix.py   # 主窗口修复补丁
│   ├── theme.py             # 双主题系统（暗色/亮色）
│   ├── models/              # Qt 数据模型
│   │   ├── industry_models.py
│   │   └── trade_models.py
│   ├── workers/             # UI 工作线程
│   │   ├── base_worker.py
│   │   ├── industry_workers.py
│   │   ├── refine_worker.py
│   │   └── trade_workers.py
│   ├── views/               # 视图组件
│   │   ├── query_view.py & query/        # 物品查询 + 价格走势
│   │   ├── industry_view.py & industry/  # 制造/工业（含计划表、甘特图等）
│   │   ├── inventory_view.py & inventory/# 库存管理
│   │   ├── compare_dialog.py & compare/  # 价格对比
│   │   ├── trade_view.py                 # 贸易评分
│   │   ├── estimate_view.py              # 估价
│   │   ├── contract_view.py              # 合同
│   │   ├── all_items_view.py             # 全物品浏览
│   │   ├── settings_view.py              # 设置
│   │   ├── char_settings_view.py         # 角色设置
│   │   ├── watchlist_view.py             # 关注列表
│   │   ├── procurement_tab.py            # 代采购
│   │   ├── score_dialogs.py              # 评分弹窗
│   │   ├── batch_price_dialog.py         # 批量查价
│   │   ├── init_wizard.py                # 首次启动向导
│   │   ├── manufacturable_items_dialog.py# 可制造物品弹窗
│   │   ├── price_chart.py                # 价格走势图
│   │   └── export_helper.py              # CSV/Excel 导出
│   └── dialogs/             # 通用对话框
│       ├── industry_dialogs.py
│       ├── npc_seller_dialog.py
│       └── production_wizard.py
│
├── scripts/                 # 维护脚本
│   └── migrate_split_db.py  # 单库→4 库迁移
│
├── tests/                   # 测试（38 文件, 599+ 用例）
│   ├── conftest.py
│   ├── test_core*.py        # 核心模块测试
│   ├── test_services*.py    # 业务逻辑测试
│   ├── test_workers*.py     # Worker 测试
│   ├── test_ui_*.py         # UI 测试
│   └── test_models*.py      # 数据模型测试
│
├── specs/                   # 设计文档/规范
│   └── sde-integration-impl-spec.json
│
├── database/                # SQLite 数据库（自动生成）
│   ├── reference.db         # 参考数据（SDE）
│   ├── market.db            # 市场数据
│   ├── user.db              # 用户数据
│   └── blueprint.db         # 蓝图数据
│
├── data/                    # 运行时数据
│   ├── settings.json        # 应用设置
│   ├── score_settings.json  # 评分参数
│   ├── char_config.json     # 角色配置
│   └── *.yaml/*.json        # SDE YAML 数据、缓存等
│
├── docs/                    # 设计文档
├── specs/                   # 实现规范
├── pyproject.toml           # Ruff / pytest / mypy 配置
├── requirements.txt         # 依赖清单
├── CLAUDE.md                # 本文件
├── AGENTS.md                # 开发规则
├── EVE-PROJECT-STATE.md     # 项目状态概览
├── CHANGELOG.md             # 版本日志
└── README.md                # 使用说明
```

## 常见问题和解决方案

### 问题：AI 生成 Python 2 语法
**解决：** 检查 `except` 语句，使用元组形式 `except (Exc1, Exc2):`

### 问题：重复代码
**解决：** 提取到 `core/` 或 `services/` 的公共模块

### 问题：错误处理不当
**解决：** 每个 except 块必须 `logger.exception(...)` 或重新抛出

### 问题：SQL 注入风险
**解决：** 使用参数化查询或转义引号 `.replace("'", "''")`

### 问题：依赖版本冲突
**解决：** 使用 `~=` 固定版本，定期运行 `pip list --outdated`

## 相关技能

使用 Claude Code 技能进行质量检查：
- `/audit` - 全面代码审计（每周）
- `/code-review` - 代码审查（每次提交）
- `/security-review` - 安全扫描（发布前）
- `/verify` - 验证代码更改（每次修改后）

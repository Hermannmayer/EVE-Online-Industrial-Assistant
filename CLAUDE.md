# EVE-Online-Industrial-Assistant

## 项目概述
EVE Online 工业制造助手，使用 PySide6 + SQLite 构建的桌面应用。

## 代码风格和约束

### 语言和版本
- Python 3.14+
- PySide6 6.5+
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
- 数据库管理使用 `services/database_manager.py`
- UI 组件使用 Qt Worker 处理异步任务

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
├── core/                    # 工具层
│   ├── constants.py         # 常量定义
│   ├── container.py         # 依赖注入
│   ├── eve_formulas.py      # EVE 公式计算
│   ├── hot_reload.py        # 热重载支持
│   └── paths.py             # 路径管理
├── services/                # 业务逻辑层
│   ├── database_manager.py  # 数据库管理
│   ├── scoring.py           # 评分计算
│   ├── scoring_service.py   # 评分服务类
│   └── workers/             # 运行时后台任务（价格/工业/合同更新）
├── tools/                   # 独立初始化工具（一次性操作）
│   ├── init.py              # CLI: python tools/init.py
│   ├── downloaders/         # 初始化下载器（items/blueprints/SDE/图标/植入体）
│   └── requirements.txt     # 额外依赖（pyyaml, aiosqlite）
├── ui_pyside6/              # UI 层
│   ├── main_window.py       # 主窗口
│   ├── views/               # 视图组件
│   ├── models/              # 数据模型
│   └── workers/             # UI 工作线程
├── tests/                   # 测试
├── database/                # SQLite 数据库
└── data/                    # 运行时数据
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

# EVE-Online-Industrial-Assistant

PySide6 + SQLite 构建的 EVE Online 工业制造助手桌面应用。

## 语言和工具

- Python 3.14+ / PySide6 6.11+ / ruff 格式化 + linting
- 所有依赖使用 `~=` 固定版本，声明于 `pyproject.toml`，用 uv 管理：`uv sync --dev`（生成 `uv.lock`）

## 代码规则

### 禁止
- ❌ Python 2 语法（`except ExcType, var:`）
- ❌ 裸 `except: pass`（必须 `logger.exception(...)` 或重新抛出）
- ❌ 超过 30 行的重复代码（提取公共函数）
- ❌ 硬编码常量（用 `core/constants.py`）
- ❌ SQL F-string 拼接（用参数化查询）
- ❌ 模块级全局 DB 单例（用依赖注入）

### 必须
- ✅ 异步代码用 `async with`
- ✅ 所有 SQL 用参数化查询
- ✅ 新代码加类型注解
- ✅ 新功能加测试（覆盖率 > 70%）
- ✅ 安全：`yaml.safe_load()`、不硬编码密钥

### 架构
- 三层分离：`core/`（工具）→ `services/`（业务）→ `ui_pyside6/`（UI）
- 依赖注入用 `core/container.py`
- 4 库独立：`reference.db` / `market.db` / `user.db` / `blueprint.db`
- DB 管理用 `services/database_manager.py`
- UI 异步用 QThread + Signal 模式
- 新 UI 组件必须 `add_theme_listener` + `_on_theme_changed`

### 铁律
- 🎨 **配色**：所有颜色从 `ui_pyside6.theme` 导入，禁止 hex/rgb/颜色名
- 📖 **术语**：EVE 术语（技能名/蓝图活动/UI 标签）通过 `services.terminology` 获取，技能 key 需在 `data/terminology.json` 注册
- 🗄️ **Schema 变更**：所有数据库表结构变更必须在 `services/schema_migrations.py` 注册迁移函数：`DB_SCHEMA_VERSIONS[库名] += 1`，新增 `MIGRATIONS[库名][旧版本] = 迁移函数`。不得在业务代码中写 ALTER TABLE。`tests/conftest.py` 中对应表的 PRAGMA user_version 同步更新。

## 测试

按档位跑，避免每次都全量（全量含 Qt，~1.5min）：

```bash
scripts/run_tests.sh            # 日常快速回归（跳过 Qt，~23s）
scripts/run_tests.sh target     # 只跑主窗口相关（~4s），改动涉及 UI 时优先
scripts/run_tests.sh full       # 全量回归（含 Qt，~1.5min），仅提交前
```

- 开发循环只跑 `target` / `quick`；`full` 仅在提交前。
- `pytest --lf` 可只重跑上次失败的测试，快速确认无回归。
- 提交前检查：`ruff check .` + `mypy .` + `scripts/run_tests.sh full` 全通过，无新增 `except: pass`。

## 常用命令

```bash
uv sync --dev              # 安装依赖（首次 / 依赖变更后）
python dev.py              # 热重载开发
python Main.py             # 生产启动
ruff check . --fix         # 自动修复风格
mypy .                     # 类型检查
pre-commit run --all-files # 预提交检查
```

## EVE 术语来源（按优先级）

1. **SDE 数据库** `database/reference.db` → `item` 表（CCP 官方翻译）
   - `SELECT zh_name FROM item WHERE category_id=16 AND en_name='Reprocessing'`
2. **`data/terminology.json`** — 项目术语中心，`services/terminology.py` 统一查询
3. 公式中的技能 key → 先在 `terminology.json` 的 `skill_names` 注册

## 项目结构

```
core/          工具层（constants, container, eve_formulas, paths, logger）
services/      业务层（database_manager, scoring_service, inventory_manager, etc.）
ui_pyside6/    UI 层（main_window, theme, models/, workers/, views/, dialogs/）
tools/         独立初始化工具
scripts/       维护脚本（migrate_split_db）
tests/         测试
database/      SQLite 库（自动生成）
data/          运行时数据（settings, score_settings, char_config）
```

## Claude 技能

- `/code-review` — 代码审查
- `/security-review` — 安全扫描
- `/audit` — 全面审计

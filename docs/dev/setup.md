# 开发环境

## 环境搭建

### 前置条件

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.14+ | 运行时 |
| uv | 0.11+ | 依赖管理器 |
| Node.js | 18+ | 文档站构建（VitePress） |
| Git | 2.30+ | 版本控制 |

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant.git
cd EVE-Online-Industrial-Assistant

# 2. 安装 uv（如果还没有）
# Windows:  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 安装 Python 依赖（含 dev 工具）
uv sync --dev

# 4. 安装文档站依赖
cd docs && npm install && cd ..

# 5. 启动开发
python dev.py   # 热重载开发模式
```

## 开发工具

### dev.py — 热重载

```bash
python dev.py
```

监听 `.py` 文件变更，自动重启应用。无需手动 stop/restart。

### build_release.py — 打包

```bash
python build_release.py            # 完整打包（exe + zip）
python build_release.py --skip-zip # 仅打包 exe
```

版本号自动从 `core/version.py` 读取（由 python-semantic-release 自动维护）。

### pre-commit hooks

```bash
# 安装 pre-commit 钩子（首次）
pre-commit install

# 手动运行全部检查
pre-commit run --all-files
```

钩子列表：
- **ruff** — lint + format
- **mypy** — 类型检查
- **trailing-whitespace** — 去尾空
- **end-of-file-fixer** — 文件末尾换行
- **check-yaml** — YAML 格式
- **check-added-large-files** — 大文件检测（>1MB）

## 日常开发流程

```bash
# 1. 创建功能分支
git checkout -b feat/my-feature

# 2. 开发（热重载模式）
python dev.py

# 3. 运行测试
pytest tests/ -q --quick --maxfail=1  # 快速模式（~20s，跳过 Qt 测试）

# 4. 代码质量检查
ruff check . --fix
mypy .

# 5. 提交前全量验证
ruff check . && ruff format --check . && mypy . && pytest tests/ -q --quick

# 6. 提交（中文信息）
git add .
git commit -m "feat: 新功能描述"
```

## 项目约束

详见 [CLAUDE.md](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/blob/main/CLAUDE.md) 中的完整代码规则，关键要点：

- 所有 SQL 参数化查询
- 颜色从 `ui_pyside6.theme` 导入
- 数据库 Schema 变更通过 `services/schema_migrations.py` 注册
- 新 UI 组件必须 `add_theme_listener` + `_on_theme_changed`

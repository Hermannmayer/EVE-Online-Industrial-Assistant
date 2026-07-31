# 安装与启动

## 环境要求

- **Python 3.14+**
- **Windows / macOS / Linux**（主开发和测试平台为 Windows）

## 1. 安装 uv（依赖管理器）

[uv](https://docs.astral.sh/uv/) 是本项目的依赖管理器，替代传统 pip：

::: code-group

```powershell [Windows (PowerShell)]
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash [macOS / Linux]
curl -LsSf https://astral.sh/uv/install.sh | sh
```

:::

::: tip
安装完成后执行 `uv --version` 确认安装成功。
:::

## 2. 克隆仓库并安装依赖

```bash
git clone https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant.git
cd EVE-Online-Industrial-Assistant

# 安装全部依赖（含开发测试工具）
uv sync --dev

# 激活虚拟环境（可选，uv run 会自动使用）
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

## 3. 启动应用

```bash
# 正常启动
python Main.py

# 热重载开发模式（文件变更自动重启）
python dev.py

# 调试模式（开启详细日志）
python Main.py --debug
```

::: info 首次启动
首次启动会自动完成以下初始化：
1. 创建 4 个 SQLite 数据库（`database/` 目录下）
2. 从 SDE 拉取物品数据（名称、分类、体积等）
3. 从 ESI 拉取吉他（The Forge）市场价格
4. 缓存物品图标到 `data/caches/icons/`
:::

## 4. 打包为 EXE（可选）

```bash
python build_release.py          # 完整打包
python build_release.py --skip-zip  # 仅打包 exe，不压缩
```

输出目录：`dist/EVE商人助手_v{version}/`

> 版本号自动从 `core/version.py` 读取，由 python-semantic-release 自动维护。

## 故障排除

### 数据未初始化

状态栏会显示具体哪项数据未初始化。通过 **设置 → 数据初始化** 手动触发。

### PySide6 安装失败

确保 Python 版本为 3.14+。Windows 上 PySide6 需要 Visual C++ Runtime（通常已预装）。

### 蓝图数据缺失

如果 `blueprint.db` 不存在，应用会从 reference.db 自动迁移蓝图表。

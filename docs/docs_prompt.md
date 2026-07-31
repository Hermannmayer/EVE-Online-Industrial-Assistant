## 任务
为 EVE Online Industrial Assistant 项目做两件事：
1. 引入语义化版本管理（semver 2.0.0）：单点版本定义 + CHANGELOG + 打 tag 自动发版
2. 创建 VitePress 中文文档站（效果参考 https://www.gyjerp.com/doc/archive.html：左侧导航、搜索、暗色模式），GitHub Actions 自动部署到 GitHub Pages

## 项目背景（读 AGENTS.md 和代码确认）
- Python 3.14 + PySide6 (Qt6 Widgets) 桌面应用，aiohttp / aiosqlite / tenacity
- 入口 Main.py，热重载 dev.py，打包 build_release.py（PyInstaller）
- 模块结构：
  - core/ — 核心逻辑（路径、日志、常量、container、formulas）
  - services/ — 业务逻辑（scoring 评分、SDE、logistics 物流、BOM、workers）
  - ui_pyside6/ — PySide6 界面（main window、views、dialogs、theme、models）
  - database/ — SQLite 数据库（reference / market / user / blueprint）
  - data/ — 缓存、设置、YAML 数据
  - scripts/ — 维护脚本
  - specs/ — 实现规格
  - tests/ — 50 个测试文件，620+ 测试
- 测试 pytest + pytest-qt，lint ruff（line-length=120），type mypy，pre-commit
- 现状：build_release.py 硬编码 VERSION = "1.0.0"，但 git 最新 tag 是 v1.0.1（不一致，需对齐）；代码中无 __version__；无 CHANGELOG

## Part A：版本管理

1. 新增 core/version.py（单一版本来源）：
   ```python
   """单一版本来源。发版只改这里。"""
   __version__ = "1.0.1"        # 与 git 最新 tag v1.0.1 对齐
   __version_info__ = (1, 0, 1)
   ```
2. 修改 build_release.py：删除第 23 行硬编码 `VERSION = "1.0.0"`，改为 `from core.version import __version__ as VERSION`。确认 zip 包名和 dist 目录名（EVE商人助手_v{VERSION}.zip）全部由导入的 VERSION 驱动，跑一遍 `python -c "import build_release"` 或轻量验证导入无误
3. 新增根目录 CHANGELOG.md（Keep a Changelog 格式）：
   - 顶部 Unreleased 段
   - 用 `git log --oneline` 提取历史，整理出 v1.0.1 段（及 alpha 段如有内容）
   - 中文，每个版本按 Added / Changed / Fixed 分类
4. 新增 .github/workflows/release.yml：当 push 的 tag 匹配 v* 时：
   - 设置 Python 3.14、安装依赖、`python build_release.py`
   - 上传产物 zip 到 GitHub Release（softprops/action-gh-release），release notes 自动取 CHANGELOG.md 中对应版本段
5. 文档站增加 dev/versioning.md 页面（见 Part B 栏目），内容：
   - semver 规则表：MAJOR=破坏性变更（删功能/改数据库/UI 大改），MINOR=新功能兼容，PATCH=修 bug
   - 发版铁律：core/version.py 版本号必须与 git tag 完全一致
   - 手动发版 checklist（改版本→更新 CHANGELOG→build_release.py→验证→commit→tag→push --tags）
   - 自动发版说明（push v* tag 触发 release.yml）

## Part B：文档站

1. 在项目根创建 docs/ 目录和 VitePress 骨架：docs/package.json（scripts: dev/build/preview，devDependencies: vitepress ^1.6）+ docs/.vitepress/config.mts（lang zh-CN、标题"EVE 工业助手"、导航栏、完整侧边栏）
2. 按以下栏目写 markdown 页面（全部中文，内容必须读真实代码生成，不得编造）：
   - index.md 首页：项目简介 + 核心功能列表 + 快速链接
   - guide/intro.md 简介：项目用途、功能概述（读 README 和 Main.py）
   - guide/install.md 安装部署：Windows 桌面版安装、build_release.py 打包方法、首次启动
   - guide/quickstart.md 快速开始：使用流程
   - guide/changelog.md 更新日志：内容用 VitePress 的 markdown include 语法 `<!-- @include: ../../CHANGELOG.md -->` 直接引用根 CHANGELOG.md（保持单一来源，不要复制内容）
   - user/overview.md 界面总览：主窗口布局和导航（读 ui_pyside6/main_window.py、views/）
   - user/industry.md 工业计算：评分/工业计算功能（读 services/scoring.py 等）
   - user/logistics.md 物流规划：物流功能（读 services/logistics.py）
   - user/bom.md BOM 管理（读 services 中 BOM 相关模块）
   - user/sde.md SDE 数据（读 services/sde.py）
   - dev/setup.md 开发环境：Python 3.14、pip install -e .、dev.py 热重载、build_release.py
   - dev/architecture.md 架构说明：core/services/ui_pyside6/database 分层职责，用 mermaid 画架构图
   - dev/data.md 数据格式：SQLite 库结构、data/ 下文件格式（如 terminology.json）
   - dev/testing.md 测试与规范：pytest、ruff、mypy、pre-commit 的使用规范
   - dev/versioning.md 版本管理：Part A 第 5 步的内容
3. 配置 .github/workflows/docs.yml：push 到 main 时安装依赖 → vitepress build → actions/deploy-pages 部署
4. 运行 npm install 和 npm run build，确保构建通过无报错
5. 用 git 提交（中文提交信息），推送

## 约束
- 只写项目真实存在的功能；已砍掉/不存在的功能一律不提
- 允许修改的文件：新增 core/version.py、新增 CHANGELOG.md、新增 .github/workflows/release.yml、修改 build_release.py（仅版本来源一处）、新增 docs/ 和 .github/workflows/docs.yml。除此之外任何业务代码一律不动
- 版本号统一用 1.0.1（与 v1.0.1 tag 对齐），不得引入其他版本号
- 文档中文，代码示例可保留英文注释
- 配色铁律只约束 UI 代码，文档站不涉及；VitePress 用默认主题即可
- 每页要有清晰标题层级、段落说明、适当用表格/列表/代码块
- 完成后报告：创建的文件清单 + npm run build 结果 + ruff 检查结果 + 是否已 push

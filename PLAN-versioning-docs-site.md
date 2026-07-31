# 版本管理 + 文档站 — 详细实施计划（v0.2.0 基线）

> 依据：`docs/docs_prompt.md` + 用户补充要求（版本基线 0.2.x、函数级 API 文档、图形流程、自动版本控制）
> 状态：**调研完成，待评审**

---

## 0. 现状核对（已逐项调研，含代码确认）

| 项 | 现状 | 问题 |
|---|---|---|
| 版本源 | `build_release.py:23` 硬编码 `VERSION = "1.0.0"` | 无 `core/version.py` 单点源 |
| git tag | `v1.0.1` + `alpha`（`git describe`: v1.0.1-140-gc80a054） | 其后 140 个提交未发版 |
| CHANGELOG | `CHANGELOG.md` 存在（98 行，v1.4.0/v1.2.0 段），**非** Keep-a-Changelog 格式，无 Unreleased | 需重构 |
| **CI** | `.github/workflows/ci.yml` 存在（push main/develop + PR） | **`pip install -r requirements.txt` 引用已删除文件，CI 必然失败** |
| 依赖管理 | 已切 uv（`pyproject.toml` + `uv.lock` + `uv sync --dev`） | ci.yml / README / AGENTS.md 仍是 pip 旧写法 |
| pre-commit | `.pre-commit-config.yaml` 存在 | 需确认是否含 uv 相关钩子 |
| Node | v24.15.0 / npm 11.12.1 | 可跑 VitePress |
| docs/ | 有 `docs_prompt.md`（本任务）+ `eve_wiki_knowledge_base.md`（EVE 知识库素材） | 无 VitePress 骨架 |
| 代码规模 | 116 py 文件、**1329 函数、134 类** | 函数级文档必须自动生成 |
| 项目状态 | `EVE-PROJECT-STATE.md`（620 测试、37k 行、8 依赖） | 含已删的 pyperclip，过时 |

**版本冲突**：tag v1.0.1 ≠ CHANGELOG v1.4.0 ≠ 你的决定 **v0.2.0**。
**结论**：产品是 0.x 半成品，统一切到 **0.2.0**，旧 tag 保留不动，发版时打新 `v0.2.0`。

---

## 1. 版本控制方案（回答"每次提交会不会自动更新"）

**核心原则**：`core/version.py` 是唯一版本源；`CHANGELOG.md` 是唯一更新日志源；git tag 必须与二者一致。自动化分三层：

### 1.1 一致性强制校验（必须做，每次 push 生效）
新增 CI 校验 job（并入修复后的 ci.yml）：
```yaml
# .github/workflows/ci.yml 中新增
- name: 版本一致性校验
  run: |
    python scripts/check_version.py
```
`scripts/check_version.py` 校验：
1. `core/version.py.__version__` 与 `CHANGELOG.md` 顶部 `## [Unreleased]` 下方最新版本段**一致**
2. （发版时）`__version__` 与 git tag `v{version}` **完全一致**
3. 任一项不符 → CI fail（**阻断合并**）

### 1.2 版本号自动更新（已定：全自动 python-semantic-release）

**采用 `python-semantic-release`，push main 自动发版**：
- 每次合并到 main → 解析 Conventional Commits → 自动提升版本 → 更新 `core/version.py` + `CHANGELOG.md` → 打 tag → 创建 GitHub Release → 打包上传
- **明确回答**：push main 后版本号由 CI 自动更新，无需手动改任何文件
- **0.x 递增规则（依据 `docs/semver-zh.md` 官方 FAQ）**：
  - 0.y.z 处于开发初始阶段，一切可随时改变；**每次发行递增次版本号**（0.1.0→0.2.0→0.3.0…），PATCH 位在 0.x 阶段不用于常规递增
  - 正文 MINOR/PATCH 严格规则有 `x>0` 前提，不适用于 0.x
  - "1.0.0 界定公共 API 形成"：功能稳定、API 被依赖后升 1.0.0
- 实施要点：`python-semantic-release` 默认对破坏性变更升 MAJOR（0.x 下会错跳 1.0.0），**必须配置 0.x 阶段任何 bump 都走 MINOR**（如 `minor_on_breaking` + 自定义 bump map），并以 `v{version}` 前缀打 tag（v 是 tag 名，0.2.0 才是版本号）
- pyproject 配置（示意）：
  ```toml
  [tool.semantic_release]
  version_variable = "core/version.py:__version__"   # 自动改写唯一版本源
  commit_parser = "angular"                          # 与现有 commit 风格一致
  tag_format = "v{version}"
  changelog_file = "CHANGELOG.md"                    # 自动生成 Keep-a-Changelog
  ```
- ⚠️ **副作用（需知晓）**：每次合并到 main 都产生一个新版本 + 一个 GitHub Release（0.x 期较频繁）。若嫌吵，后续可改为仅 `release` 分支触发或 `--prerelease` 模式

### 1.3 发版触发链（自动，单 workflow）
```
合并到 main
  └─> release.yml:
        1. python-semantic-release publish → 自动 bump + 更新 core/version.py + CHANGELOG + 打 tag + 建 GitHub Release
        2. python build_release.py → EVE商人助手_vX.Y.Z.zip
        3. softprops/action-gh-release 上传 zip 到该 Release
```
> ⚠️ 关键机制：semantic-release 用 `GITHUB_TOKEN` push 版本提交/tag 时**不会再次触发本 workflow**（GitHub 防止 token 触发链），恰好避免死循环；CI（ci.yml）也只在语义提交时跑，不受影响。
> 版本一致性校验（§1.1）在 ci.yml 中保留：若有人手动改了版本号与 CHANGELOG 不符 → 阻断。

---

## 2. 文档站版本记录自动更新（回答"会不会自动更新"）

**会，设计为自动**，机制：
- `docs/guide/changelog.md` 用 VitePress include 直接引用根 CHANGELOG：
  ```md
  <!-- @include: ../../CHANGELOG.md -->
  ```
- `docs.yml` 在 **push main 时自动重建**文档站 → 根 CHANGELOG 一改，站点更新日志页自动同步，**无需手动改两份**
- 版本选择器（可选增强）：VitePress 多版本目录 `docs/0.2/` 存档历史版本文档，导航栏版本下拉切换

---

## 3. 文档站完整内容清单（含 docs_prompt 未列的补充）

### 3.1 用户文档（最终用户）
| 页面 | 内容 | 依据源码 |
|---|---|---|
| `index.md` | 首页：简介 + 功能列表 + 快速链接 | README |
| `guide/intro.md` | 项目用途、功能总览 | README, Main.py |
| `guide/install.md` | **uv 安装**（非 pip）、首次启动、数据初始化 | 已重构的安装流程 |
| `guide/quickstart.md` | 使用流程：搜索→估价→制造→物流 | 各 view |
| `user/overview.md` | 主窗口布局、导航、各页面 | `main_window.py`, `views/` |
| `user/industry.md` | 制造利润计算、生产计划、甘特图 | `industry_view.py`, `scoring_service.py` |
| `user/logistics.md` | 物流规划、运输利润 | `services/logistics.py` |
| `user/bom.md` | BOM 管理/展开 | `services/bom_expander.py` |
| `user/refining.md` | 精炼价值计算 | `services/refining_service.py` |
| `user/inventory.md` | 库存管理、机库、蓝图 | `inventory_manager.py` |
| `user/pricing.md` | 价格查询、贸易评分 | `pricing_service.py`, `scoring_service.py` |
| `guide/faq.md`（补充） | 常见问题、已知 bug 状态 | 半成品声明 + issue |

### 3.2 开发者文档
| 页面 | 内容 | 依据 |
|---|---|---|
| `dev/setup.md` | **uv** 环境、dev.py 热重载、build_release 打包 | 已重构 |
| `dev/architecture.md` | 分层架构 + **mermaid 架构图** | `core/`, `services/`, `ui_pyside6/` |
| `dev/data.md` | 4 个 SQLite 库 schema + data/ 格式 | `schema_migrations.py`, `database_manager.py` |
| `dev/testing.md` | pytest/ruff/mypy/pre-commit 规范 | 现状 |
| `dev/versioning.md` | semver 0.x 规则、发版 checklist、CI 校验 | 本计划 §1 |
| `dev/contribution.md`（补充） | 贡献指南：分支、commit 规范、PR 流程 | git-workflow |
| `dev/api-reference.md`（补充，核心） | **函数级 API 参考**（见 §4） | 自动生成 |

### 3.3 参考 / 其它
| 项 | 说明 |
|---|---|
| `dev/database-er.md`（补充） | 4 库 **ER 图**（mermaid） |
| `dev/glossary.md`（补充） | EVE 术语表（基于 `terminology.json` + 知识库） |
| `guide/changelog.md` | 根 CHANGELOG include（自动同步） |
| 旧 `EVE-PROJECT-STATE.md` | 迁移/更新，避免与新文档站两套说法 |

---

## 4. 函数级 API 文档方案（1329 函数怎么覆盖）

**结论：手写不可能，采用「自动生成 + 人工精选」**：

1. 新增 `scripts/gen_api_docs.py`：
   - 用 Python `ast` 遍历 `core/`、`services/`、`ui_pyside6/models/`、`ui_pyside6/workers/` 等模块
   - 提取每个 `class` / `def` / `async def` 的**签名 + docstring + 所在行号**
   - 输出 markdown 到 `docs/api/<module>.md`（VitePress 页面）
   - 无 docstring 的函数标注 `⚠️ 待补 docstring`（倒逼补文档）
2. `docs.yml` 构建前运行 `python scripts/gen_api_docs.py`，**保证 API 页与代码同步**（每次 push 自动刷新）
3. 分级策略：
   - **一级（全函数）**：`core/`、`services/scoring_service.py`、`manufacturing_calculator.py`、`logistics.py`、`inventory_manager.py`、`pricing_service.py`、`refining_service.py`、`bom_expander.py` —— 业务核心，别人要靠它理解
   - **二级（模块级概览 + 关键函数）**：`ui_pyside6/views/`、`workers/`（UI 层，docstring 少的先列签名）
4. 人工精选重点函数写**详细文档 + 公式 + 示例**：`calc_manufacturing_score`、`calculate_personal_margin`、`calc_job_cost_fees`、`calc_material_per_run` 等（用 `dev/api-reference.md` 或内联注释）

---

## 5. 图形流程清单（mermaid，全部基于真实代码）

| 图 | 位置 | 内容 |
|---|---|---|
| 架构分层图 | `dev/architecture.md` | core → services → ui_pyside6 → database 依赖方向 |
| 启动流程 | `guide/intro.md` | Main.py → AppContainer → 初始化检查 → 数据下载 → 主窗口 |
| 工业制造计算流程 | `user/industry.md` | 计划 → `calculate_plan_metrics` → 材料/安装费/税费 → 利润/评分 |
| 个人利润率流程 | `user/industry.md` | 市场利润率 + 库存成本混合 → 个人利润率 |
| 物流规划流程 | `user/logistics.md` | 需求 → 运输 → 利润 |
| 数据库 ER 图 | `dev/database-er.md` | 4 库表关系 |
| 发版流程 | `dev/versioning.md` | bump → tag → release.yml → GitHub Release |

**VitePress mermaid 支持**：安装 `@vitepress-demo-plugin` 或 `vitepress-plugin-mermaid`，在 `config.mts` 注册 markdown-it 插件。

---

## 6. GitHub Actions 全套（3 个 workflow）

| Workflow | 触发 | 内容 | 状态 |
|---|---|---|---|
| `ci.yml` | push main/develop, PR | **修复**：`pip install -r requirements.txt` → `uv sync --dev`；保留 ruff/mypy/pytest；新增版本一致性校验 job | 🔴 现坏，必改 |
| `release.yml` | **push main** | **windows-latest**：`python-semantic-release publish`（bump+CHANGELOG+tag+Release）→ `build_release.py` → 上传 zip | 🆕 新建（语义化发版） |
| `docs.yml` | push main | uv → `gen_api_docs.py` → `npm ci && npm run build` → deploy-pages | 🆕 新建 |

ci.yml 修复要点：`actions/setup-python@v5` + `pip install uv && uv sync --dev`（或 `astral-sh/setup-uv@v5`），跑 `uv run ruff` / `uv run mypy .` / `uv run pytest`。

---

## 7. 分阶段实施

| 阶段 | 内容 | 产出 |
|---|---|---|
| **P0 修 CI** | ci.yml 改 uv + 版本校验脚本 | CI 恢复绿 |
| **P1 版本管理** | `core/version.py`(0.2.0)、改 `build_release.py`（版本来源 + **删 pyperclip hidden-import**）、接入 `python-semantic-release`（pyproject 配置 + 首次 baseline tag v0.2.0）、`scripts/check_version.py` | 自动发版就绪 |
| **P2 文档站骨架** | docs/VitePress + config.mts + mermaid 插件 | 站点能 build |
| **P3 文档内容** | §3 全部页面 + `gen_api_docs.py` 自动生成 API 页 + mermaid 图 | 完整文档站 |
| **P4 workflow** | `release.yml`（semantic-release + 打包）+ `docs.yml` | 自动发版 + 自动部署 |
| **P5 一次性手动** | GitHub Settings → Pages 源设为 "GitHub Actions"；本地 `npm run build` 验证 | 首次部署成功 |

---

## 8. 约束与风险

**约束**（沿用 docs_prompt）：业务代码一律不动；只改 `core/version.py`(新)、`CHANGELOG.md`、`build_release.py`（版本来源一行 + 删 pyperclip hidden-import）、`.github/workflows/*`、`docs/*`、新增 `scripts/gen_api_docs.py` + `scripts/check_version.py`；配色铁律不约束文档站（默认主题）。

**风险**：
- ⚠️ **GitHub Pages 需你在 GitHub 网页端一次性设置**（Settings → Pages → Source: GitHub Actions），我无法代做
- ci.yml 当前是红的（引已删 requirements.txt），**P0 优先级最高**
- 1329 个函数中不少无 docstring，自动生成会暴露注释缺口——这是特性不是 bug（驱动补文档）
- release.yml 首次触发需要 push 一个 `v0.2.0` tag（你决定何时发版）
- 旧 `v1.0.1`/`alpha` tag、旧 `EVE-PROJECT-STATE.md`、旧 CHANGELOG 1.x 段：保留但标注"历史遗留，产品现为 0.x 阶段"

---

## 8.5 函数文档覆盖审计（实测，供 API 文档分级）

| 目录 | 总 def | 缺 docstring | 覆盖率 | 最缺的模块 |
|---|---|---|---|---|
| core | 67 | 41 | 39% | `container.py`(19)、`hot_reload.py`(8)、`cache.py`/`logger.py`(各6) |
| services | 250 | 71 | 72% | `inventory_manager.py`(14)、`scoring_service.py`(14)、`terminology.py`(7)、`repositories/` |
| ui_pyside6 | 851 | 558 | 34% | views/workers 大量方法无文档 |
| tools | 45 | 10 | 78% | — |
| scripts | 4 | 0 | 100% | — |

**结论：**
- 核心层（core+services）约 **112 个函数缺 docstring**，是 `gen_api_docs.py` 首轮要优先补齐的（尤其 `scoring_service` 的 `calc_manufacturing_score` / `calc_job_cost_fees` / `calculate_personal_margin` 等算法函数——本会话已为新写的个人利润率函数补过）
- ⚠️ `scoring_service.py` 的 `get/set/invalidate/_evict_expired_locked/__len__` 疑似**残留的旧 ScoringCache 类方法**——CHANGELOG 说已移除死代码但可能没删干净，实施时确认，存在则清理（属"业务代码"，需你确认后再动）
- ui_pyside6 66% 缺文档 → 印证"UI 层只列模块概览 + 关键函数"策略，避免 558 个占位页

## 8.6 计划自身 Bug / 风险审计（新增，实施前必须处理）

| # | 风险 / Bug | 严重度 | 处理 |
|---|---|---|---|
| 1 | **release.yml 用 ubuntu 会失败**：`build_release.py` 产出 `EVE商人助手.exe`，必须 **windows-latest** | 🔴 | release.yml 的 build job 用 `windows-latest` |
| 2 | **`build_release.py:66` 的 `--hidden-import pyperclip` 引用已删依赖**：代码 0 引用 pyperclip（已改 Qt `QApplication.clipboard()`），uv 环境无此包 → PyInstaller 报错 | 🔴 | 删除该行（docs_prompt 允许改 build_release.py） |
| 3 | **VitePress `base` 路径**：Pages URL 是 `/EVE-Online-Industrial-Assistant/`，不设 base 则静态资源 404 | 🟠 | `config.mts` 设 `base: '/EVE-Online-Industrial-Assistant/'` |
| 4 | **semantic-release 并发竞态**：连续 push main → 两个 release job 同时 bump → tag 冲突 | 🟠 | release.yml 加 `concurrency: {group: release, cancel-in-progress: true}` |
| 5 | **semantic-release 需完整 git 历史 + 凭据**：`actions/checkout` 需 `fetch-depth: 0` + `persist-credentials: true` + 配置 git user | 🟠 | checkout 参数 + git config 步骤 |
| 6 | **CHANGELOG 首跑被重写**：semantic-release 首次生成会清空现有 v1.4.0/v1.2.0 段 | 🟠 | 先手工并入"历史遗留"段 → 打 `v0.2.0` baseline tag → 再启用 |
| 7 | **docs.yml 与 release.yml 并发干扰**（都推 main 触发） | 🟠 | 各自 `concurrency` 控制 |
| 8 | **`check_version.py` 的 Unreleased 态**：未打 tag 时不能强制 `version==tag` | 🟡 | 分"开发态 / 发版态"两档校验 |
| 9 | **mermaid 插件 ESM/SSR 兼容**（VitePress 1.6） | 🟡 | 实施时验证 `vitepress-plugin-mermaid`，备选客户端 `<pre class="mermaid">` 脚本 |
| 10 | **`gen_api_docs.py` 中文 / 复杂类型注解解析** | 🟡 | ast 提取 + `typing.get_type_hints` 兜底，失败项标注待补 |
| 11 | **PyInstaller onefile 在 CI 上较慢** | 🟡 | 接受（~2-3min） |

## 9. 已确认决策

| 决策 | 选择 |
|---|---|
| 版本基线 | **0.2.0**（半成品阶段，旧 tag/CHANGELOG 1.x 标注为历史遗留） |
| 0.x 递增规则 | **按 semver-zh.md：每次发行递增 MINOR**（0.2.0→0.3.0→…），PATCH 位 0.x 阶段不用 |
| 版本 bump 方式 | **全自动 python-semantic-release**（push main 自动 bump+tag+Release） |
| API 文档深度 | **核心（core + services）全函数 + UI 层（views/workers）概览 + 关键函数** |
| 版本一致性校验 | 保留在 ci.yml（version.py == CHANGELOG == tag，不符阻断） |
| 安装方式文档 | 全部写 **uv**（`uv sync --dev`），不写 pip |

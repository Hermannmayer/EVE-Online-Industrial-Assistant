# 缺陷与待办台账

首版登记：2026-10-10。本页是**唯一**的待办收口处 —— `docs/dev/audit-report.md` 是历史快照（2026-07-31，不代表现状，只作溯源），
`docs/dev/feature-inventory.md` 是功能清单，两者都不承担台账职能。

## 怎么用

1. 新发现的缺陷 / 待决策项**先登记到本页**，再决定怎么修；**不要先就地 hotfix**（先登记 → 再定修法，避免零散热修越修越乱）。
2. 每条必须**可复核**：证据栏写本次真实跑过的命令 + 真实输出，或真实读到的 `文件:行号`。「感觉有问题」不入账。
3. 修掉后**不删条目**：把 `状态` 改成 `已关闭`，并在括号里写上修复 commit（`已关闭（abc1234）`）。
4. **一次性、无法复现**的问题不入账（与 CLAUDE.md「测试判定表」一致）；宁可少写。
5. 状态取值：`open`（待修）/ `deferred`（等用户决策或外部条件）/ `已关闭`（已核实不成立或已修）。

---

## BL-001 查询页用户手册写了工具栏里已不存在的两个按钮

- 类型：缺陷
- 状态：open
- 证据：
  - `docs/user/query.md:24-30` 的工具栏表列了 5 项：全物品、**批量查价**、清空、**制造配方**、区域（右上角下拉）。
  - 实测代码：`ui_qml/qml/pages/QueryPage.qml:57-163` 的工具栏只有 4 个控件 —— `allItemsButton`（`:69`，文案「全物品 / 返回」）、
    `searchInput`（`:91`）、「清空」按钮（`:126`）、`区域:` 标签（`:148-153`）+ `regionCombo`（`:155-162`）。**没有**「批量查价」「制造配方」按钮。
  - `git grep -n "recipeButton"`（不带 pathspec）→ 全仓 **2 处**引用：`docs/dev/ui-blueprint.md:96`（「改挂工具栏按钮 `#recipeButton`（没选中物品时不可点）。」，叙事文字）
    与 `ui_qml/qml/pages/QueryPage.qml:403`（注释）—— **两处都是叙事/注释，没有任何按钮定义**。
    （口径备注：本条初版写「全仓只有 1 行」，当时用的是带 pathspec 的 `git grep -n "recipeButton" -- '*.py' '*.qml'` → 1 处，漏掉了 `.md` 里那一处。）
    同文件 `:14` 的注释也仍写「工具栏（全物品 / 搜索框+候选 / 清空 / 批量查价 / 区域）」。
  - `git grep -n "openBatchPrice"` → 只有 `ui_qml/bridge/query_bridge.py:410` 的定义，**无任何调用方**（QML 与 Python 都没有）。
  - 对照：`docs/dev/feature-inventory.md:302` 早已记录同一条事实（「`QueryPage.qml` 工具栏只有「全物品 / 清空 / 区域」三个控件 | 曾挂在查询页工具栏，现已移除按钮」），
    `docs/dev/feature-inventory.md:334` 又把 query.md 列为待改 —— 所以**该改的是 `docs/user/query.md`，不是 `feature-inventory.md`**。
- 影响：查询页是打开软件后的第一屏；用户照手册找「批量查价」「制造配方」，界面上根本没有，且 `QueryBridge.openBatchPrice` 成了永远进不去的死入口。
  而且**两份文档都指向这个不存在的控件** —— 除 query.md 的工具栏表外，`docs/dev/ui-blueprint.md:96` 也写「改挂工具栏按钮 `#recipeButton`」。
- 下一步：改 `docs/user/query.md:22-30` 删掉这两行（若确定要保留功能则补回按钮 —— 需用户决策）；顺手清掉 `QueryPage.qml:14`、`:403` 与 `docs/dev/ui-blueprint.md:96` 的过时注释/叙事。纯文档/注释改动，按判定表不补测试。

## BL-002 文档站侧边栏漏登记 5 个页面，其中 2 个是必读页

- 类型：缺陷
- 状态：open
- 证据：提取 `docs/.vitepress/config.mts` 的 `link: '...'` 去重得 29 条，与 `docs/**/*.md`（排除 `.vitepress`、`docs/api/`）31 页做差集，实测 5 页无入口：
  ```
  === 差集：有 md 但 sidebar 无 link ===
    /dev/demo-data
    /dev/feature-inventory
    /dev/schema-migration
    /promo
    /user/query
  ```
  - CLAUDE.md「文档索引」节原文：「新增页面必须在 `nav`/`sidebar` 登记，否则站点里点不到」。
  - `/promo` 是**有意**不入站（CLAUDE.md 明写「不在文档站侧边栏内，发布前按其末尾清单自检」），不算缺陷。
- 影响：`docs/dev/schema-migration.md` 是 CLAUDE.md「任务导航」要求「改 schema 前先读」的页，`docs/user/query.md` 是面向用户的主功能页（物品查询），
  两者在文档站里都没有任何入口 —— 站点访问者与后续会话都找不到。
- 下一步：在 `docs/.vitepress/config.mts:59-79` 的 `/dev/` 与 `:45-58` 的 `/user/` 侧边栏各补一条 `link`（`/dev/schema-migration`、`/user/query`）；
  `demo-data` / `feature-inventory` 是否入站等用户决策。**不新增 `scripts/check_*.py`**（克制条款 5），靠人工核对。

## BL-003 「ScoringCache 去留」待决策项已实际落地（类已不存在）

- 类型：待决策
- 状态：已关闭（实测复核；仓库里没有记录这次整改的单一 commit）
- 证据：
  - `docs/dev/audit-report.md:47` 的现状描述「审计确认**仍被模块级便利函数使用**（非死代码，CHANGELOG 声称已移除但实际仍在使用）」**已不成立**：
    `git grep -n "ScoringCache"`（大小写敏感、不带 pathspec）→ 全仓 **9 处命中 / 5 个文件**（`git grep -c "ScoringCache"` 逐文件：
    `CHANGELOG.md:2`、`docs/api/services/scoring_service.md:2`、`docs/dev/api-reference.md:1`、`docs/dev/audit-report.md:2`、`services/scoring_service.py:2`），
    其中**没有任何 `class ScoringCache` 定义**；`services/scoring_service.py` 只剩 `:2` 与 `:5` 两行 docstring 文字。
    （口径对照：本条初版写的「17 处」用的是 `git grep -n -e "ScoringCache" -e "scoring_cache"` → 17 处，
    多算的 8 处是**现行**属性/方法名字样 —— `bootstrap/container.py:22,43,44,46,47,48,106` 共 7 处 `_scoring_cache` / `scoring_cache`，
    加 `tests/test_scoring_service.py:915` 注释里的 `test_scoring_cache` 1 处；旧类名本身的命中数是 9，不是 17。）
  - 缓存现由 `core.cache.TtlLRUCache` 承担：`bootstrap/container.py:43-48`（`scoring_cache()` → `TtlLRUCache(max_size=500, ttl_seconds=1800)`）、
    `services/scoring_service.py:17` 的 import、`services/scoring_service.py:305` 的 `ScoringService.__init__(self, db, cache: TtlLRUCache, ...)`。
  - `git log --oneline -S"class ScoringCache" -- services/scoring_service.py` → `bfb571e`、`321e4a1`；`CHANGELOG.md:1278` 记「新增 `core/cache.py`：`TtlLRUCache` 线程安全 LRU+TTL 缓存，替代旧 `ScoringCache`」。
- 影响：不关的话，后续会话会照着 audit-report 重新开启一个已经做完的决策（audit-report.md:73 也还挂着第 5 项待办）。
- 下一步：无需动作。`docs/dev/audit-report.md:47`、`:73` 保持原样（历史快照不改写）；残留的文档描述见 BL-004。

## BL-004 三处文档/生成页仍把 ScoringCache 写成现行评分核心

- 类型：缺陷
- 状态：open
- 证据：`git grep -n "ScoringCache"` 实测 **9 处 / 5 文件**（命令与逐文件计数见 BL-003；大小写敏感的旧类名口径），其中与「现行实现」有关的错处有 **5 行**（类已不存在，见 BL-003）：
  - `services/scoring_service.py:2` 模块 docstring 首行「评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑」
  - `services/scoring_service.py:5` 「- ScoringCache：线程安全、有界 TTL 缓存」
  - `docs/api/services/scoring_service.md:7`、`:10` —— 与上面两行逐字相同，由 `scripts/gen_api_docs.py` 从该 docstring **生成**
  - `docs/dev/api-reference.md:27` 表格写「评分核心 — ScoringCache + 定价查询 + 制造/贸易/精炼评分」
- 影响：读者会以为存在一个叫 `ScoringCache` 的缓存类，实际是 `core.cache.TtlLRUCache`；生成物与手写索引页两头都是错的，且生成物会一直把错的 docstring 复制下去。
- 下一步：改 `services/scoring_service.py:2,5` 的 docstring（改成 `TtlLRUCache` 的实际职责），跑 `scripts/gen_api_docs.py` 重新生成 `docs/api/services/scoring_service.md`，再改 `docs/dev/api-reference.md:27`。改注释/生成物，按判定表不补测试。

## BL-005 CI 不再校验 ruff format，而当初跳过的理由已经失效

- 类型：待决策
- 状态：open
- 证据：
  - `.github/workflows/ci.yml:38-42`：lint step 只有 `uv run ruff check .`，紧跟两行注释
    「注：不跑 `ruff format --check .` —— 仓库存在 30 个历史未格式化文件（超出本任务「业务代码一律不动」约束），跑则 CI 恒红。整改应单独立项。」
  - 本次实测：`.venv/Scripts/python.exe -m ruff format --check .` →
    `warning: `M` has been remapped to `RUF100`.` + `403 files already formatted`，exit 0；`git ls-files '*.py'` 计数也是 **403** ——
    即全部受版本控制的 py 文件都已格式化，注释里「30 个历史未格式化文件」这个前提已不存在。
  - `docs/dev/audit-report.md:46` 点名的三个文件：`Test-Path scripts/startup_check.py` → `False`（文件已不存在）；
    `ui_qml/workers/init_workers.py`、`scripts/migrate_split_db.py` 单独跑 `ruff format --check` 均输出 `1 file already formatted`。
- 影响：格式漂移现在没有第二道护栏（只靠本地），CI 注释还会继续误导下一个维护者以为仓库仍是脏的。
- 下一步：删掉 `ci.yml:41-42` 的过时注释，把 `uv run ruff format --check .` 加回 lint step。属 CI 配置改动 —— 本条即登记，改动前先确认。

## BL-006 本地无法验证文档站构建（缺 docs/node_modules）

- 类型：已知限制
- 状态：open
- 证据：`Test-Path docs/node_modules` → `False`；`docs/` 下有 `package.json`、`package-lock.json`、`.vitepress/`、`index.md`、`api/`、`dev/`、`guide/`、`user/`、`public/`，但没有安装产物。
  CI 侧 `.github/workflows/docs.yml` 存在（`name: Deploy Docs`，`on: push: branches: [main]`，job `build-and-deploy`）；
  `docs/dev/audit-report.md:32` 在审计环境里 `npm run build`（docs/）曾 ✅ build complete。
- 影响：本地改 `docs/**` 或 `config.mts` 后只能跑 `scripts/check_docs_links.py`（只查死链，不查侧边栏、不查渲染/编译错误）。
  构建期错误（先例：docstring 里 `{ "items": bool }` 被 markdown-it-attrs 当 HTML 属性导致 Vue `Duplicate attribute`，见 audit-report.md:26 第 1 条）本地看不见，要等 push 后由 docs.yml 暴露。
- 下一步：需要本地验证时执行 `cd docs && npm install`（首次），再 `npm run build`；或明确接受「文档站构建由 CI 兜底」。等用户决定是否安装 node 依赖。

## BL-007 audit-report 记的「30 个 ruff format 失败文件」现状复核：0 个

- 类型：缺陷
- 状态：已关闭（实测复核；仓库里没有记录这次整改的单一 commit）
- 证据：
  - `.venv/Scripts/python.exe -m ruff format --check .` → `warning: `M` has been remapped to `RUF100`.` + `403 files already formatted`，exit 0。
  - `git ls-files '*.py'` 计数 = 403（与 ruff 实际检查的文件数一致，说明没有靠 exclude 蒙过）。
  - `docs/dev/audit-report.md:46` 点名的三个文件已复核：`scripts/startup_check.py` 不存在；`ui_qml/workers/init_workers.py`、`scripts/migrate_split_db.py` 单独跑均 `1 file already formatted`。
- 影响：`docs/dev/audit-report.md:46`、`:72` 的「单独立项整改（`ruff format .` 一次性格式化 + 恢复 CI format 检查）」不再需要重复开项；本条只保留「已核实」的结论，避免后续会话重新捡起。
- 下一步：无需动作。关闭依据是**本次实测**而非某个 commit —— 试过 `git log --oneline -S"ruff format --check ." -- .github/workflows/ci.yml`，只返回当年加入该步骤的 `7dc9f26`（跳过动作只把命令改成了注释，`-S` 捕捉不到）。恢复 CI 校验的动作见 BL-005。

## BL-008 GitHub Pages 的 Source 设置是否已完成 —— 需仓库外确认

- 类型：待决策
- 状态：deferred
- 证据：仓库侧流程已就绪 —— `.github/workflows/docs.yml` 存在，`on: push: branches: [main]`，`permissions` 含 `pages: write` / `id-token: write`。
  但 `docs/dev/audit-report.md:60-61` 要求的是网页端设置：「1. **GitHub Pages 设置**（网页端，Claude 无法代做）：> 仓库 → Settings → Pages → Source: 选择 **GitHub Actions**」——
  该设置在仓库文件里**看不出来**，无法从仓库判断是否已勾选。
- 影响：若 Source 未设为 GitHub Actions，docs.yml 的部署不会发布站点，文档站 404 而 CI 看起来仍在跑。
- 下一步：需用户到 GitHub 网页端确认（或看最近一次 docs.yml run 的结论）。**标注：需仓库外确认，不猜。** 本条在确认前保持 deferred。

## BL-009 生产计划表列数：文档写 19，代码是 20

- 类型：缺陷
- 状态：open
- 证据：
  - 实测 `ui_qml/models/industry_models.py:61-81` 的 `_HEADERS`：用 `ast` 解析计数 → `_HEADERS len = 20`，`first = ☐`（勾选列）、`last = 个人利润率%`，与源码里 `# 0` ~ `# 19` 的索引注释一致。
  - `docs/user/industry.md:79` 写「生产计划表格（`plan_table.py`）包含 19 列数据：」（`plan_table.py` 实体在 `ui_qml/views/industry/plan_table.py`）。
  - `ui_qml/models/plan_qml_model.py:4`、`:18` 的类 docstring 也各写一次「19 列」。
  - 对照：`docs/dev/feature-inventory.md:336` 已把这条列为待改，并提醒「`ui_qml/models/plan_qml_model.py` 的类 docstring 自己也写着「19 列」，同样过时，别当依据」。
- 影响：维护者照 19 列改表会从勾选列开始整体错位一列；代码里的过时 docstring 还会被当成依据。
- 下一步：改 `docs/user/industry.md:79` 与 `ui_qml/models/plan_qml_model.py:4,18` 为 20 列并说明第 0 列是勾选/备料列。纯文档/注释改动，按判定表不补测试。

---

## 复核记录（本轮实测）

| 命令 | 输出摘要 |
|------|----------|
| `.venv/Scripts/python.exe -m ruff format --check .` | `403 files already formatted`，exit 0（`git ls-files '*.py'` = 403） |
| `.venv/Scripts/python.exe scripts/check_docs_links.py` | 建本页前：2 个孤儿链接（`docs\index.md → /dev/decisions`、`docs\index.md → /dev/backlog`）；`/dev/backlog` 由本页补齐 |
| `git grep -n "ScoringCache"` / `git grep -c "ScoringCache"` | **9 处 / 5 文件**（`CHANGELOG.md:2`、`docs/api/services/scoring_service.md:2`、`docs/dev/api-reference.md:1`、`docs/dev/audit-report.md:2`、`services/scoring_service.py:2`），**无 `class ScoringCache` 定义** |
| `git grep -n -e "ScoringCache" -e "scoring_cache"` | 17 处（= 旧类名 9 + `bootstrap/container.py` 的现行 `_scoring_cache`/`scoring_cache` 7 + `tests/test_scoring_service.py:915` 的 `test_scoring_cache` 1）——这是初版误用的宽口径 |
| `git grep -n "recipeButton"` | 2 处：`docs/dev/ui-blueprint.md:96`、`ui_qml/qml/pages/QueryPage.qml:403`，均为叙事/注释，无按钮定义 |
| `git grep -n "ui_pyside6"`（`*.py`/`*.md`/`*.qml`） | 12 处命中，**全部**是「批次 6.0/7.5 已迁走 / 已删除」的沿革叙述或禁令原文本身，**无一处把 `ui_pyside6/` 当现行路径使用** → 未入账 |
| 侧边栏差集（`config.mts` 的 `link:` vs `docs/**/*.md`） | 5 页无入口 → BL-002 |

**查过但未成立、因此不入账的来源**：

- `ui_pyside6` 残留（CLAUDE.md 禁令）：12 处命中均为历史叙述（`CHANGELOG.md:670,676,821,830`、`CLAUDE.md:91-92`、`docs/dev/api-reference.md:73-74`、`docs/dev/architecture.md:163`、`docs/dev/ui-blueprint.md:13`、`docs/dev/feature-inventory.md:337`、`docs/user/inventory.md:58`），无一按现行路径引用 → 不构成 BL 条目。
- `docs/index.md:49-50` 指向 `/dev/decisions`、`/dev/backlog` 的死链：这两个文件是本批次正在新建的产物（`/dev/backlog` 即本页），属在途状态而非缺陷 → 不登记。
- `docs/dev/feature-inventory.md` §12 的其余各行（`overview.md`、`pricing.md`、`quickstart.md` 等）：本轮只对 §12 中 `query.md` 与 `industry.md` 两行做了独立复核（分别落在 BL-001、BL-009），其余未逐条实测 → 不登记，留待逐条取证。

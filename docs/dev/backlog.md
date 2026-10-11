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

## BL-010 科研作业时长漏套 3388 高级工业理论（发明偏长 15%），且错误地对全部科研活动乘 TE 系数

- 类型：缺陷
- 状态：已关闭（5f502eb）
- 证据：
  - 缺陷源码（**HEAD 口径**：`git show HEAD:domain/research.py`。工作区已被 task-1 修改，现行行号变成 `:224-289`，下面全是 HEAD 的行号）：
    `:224-229` 的技能归属注释断言「发明：没有任何技能文案提到发明时长（Wiki 也只说结构/钻机减免）→ 不套技能」；
    `:242` 形参只有 `te_level`，**没有**「高级工业理论」；`:248` 公式串写 `time = base_time × 技能系数 × (1 − 0.01×TE) × 结构系数`；
    `:259` 只 import `METALLURGY_SKILL_MULT, RESEARCH_SKILL_MULT, SCIENCE_SKILL_MULT, TE_MULT_PER_LEVEL`（3409/3403/3402 + TE）；
    `:268` `mult *= 1.0 - TE_MULT_PER_LEVEL * max(0, int(te_level))` —— 对所有活动（含拷贝/发明）一律乘 `(1 − 0.01×TE)`。
    实测命令：`git show HEAD:domain/research.py | Select-String -Pattern '科学作业（拷贝/发明/研究）|发明：没有任何技能|te_level: int = 0|TE_MULT_PER_LEVEL'`
    → 命中 `224:`、`228:`、`242:`、`259:`、`268:`（行号即上述）。
  - 客户端 SDE `data/typeIDs.yaml` 的 `3388:` 条目原文（本机实读）：
    `zh: 高效使用工业设施的技能。每升一级，所有制造和研究时间减少3%。`
    `en: Skill at efficiently using industrial facilities. 3% reduction in all manufacturing and research times per skill level.`（YAML 里折成两行）
    `name.zh: 高级工业理论`。即 3388 覆盖的是**所有研究时间**，不是只管制造。
  - EVE University Wiki「[Research](https://wiki.eveuniversity.org/Research)」页（HTTP 200；页脚 Last modified 2026-03-21）Skills 节原文：
    `Advanced Industry (3x) - reduces all manufacturing and research times by 3% per level`；
    互斥归属由同节另四条界定 —— `Science (1x) - reduces the time required to copy a BPO by 5% per level`、
    `Research (1x) - reduces the time required for Time Efficiency research, by 5% per level`、
    `Metallurgy (3x) - reduces the time required for Material Efficiency research, by 5% per level`、
    `Laboratory Operation ... allows you to perform one additional research or copying job per level`／
    `Advanced Laboratory Operation ... perform further additional research or copy jobs per level`（**只加并发槽位，不减时长**）。
    Copying 节原文：`Copy time is also NOT affected by the level of TE on the BPO.`
  - 实测数值（`database/user.db`，只读连接 `sqlite3.connect("file:database/user.db?mode=ro", uri=True)`）：
    计划 `id=364`：`activity='invention'`、`product_type_id=43611`、`runs=10`、`parallels=5`、`te_level=0`、`me_level=0`、
    `mat_hangar_id=8`、`char_name='MayerHermann'`、`calculated_time=578850.0`。
    基准时长来自 T1 蓝图 43546 的 invention 行：`database/blueprint.db` 的 `blueprint_activities` → `(43546, 'invention', 68100, 50)`；
    `blueprint_products` → `(43546, 'invention', 43611, 10, 0.34)`（产出正是计划的 43611，数量 10）。
    机库 8 在 `hangars` 表里是 `facility_type='raitaru'`、`rigs='[]'`；实测 `services.hangar_industry_config.resolve_hangar_industry_config(8)` 输出
    `{'structure_mat_saving': 0.99, 'structure_time_mod': 0.85, 'structure_cost_mult': 0.97, 'facility_tax': 1.0, 'facility_type': 'raitaru', 'rig_ids': []}`
    （倍率出自 `services/hangar_industry_config.py:273-277`）。
    于是 `578850 / 10 = 57885` 且 `68100 × 0.85 = 57885` → **技能系数恰为 1.0**（HEAD 的科研侧只乘 `(1 − 0.01×te_level)`，该计划 `te_level=0`）。
    角色技能：`data/char_config.json:109` 是 `"MayerHermann": {` 块，`:112` 为 `"高级工业理论": 5`；
    交叉核对 `database/user.db` 的 `user_skills`（该表只有 `skill_type_id`/`level` 两列）→ `(3388, 5)`。
    修复后应有值：`57885 × (1 − 0.03×5) = 49202.25` s/次，计划级 `492022.5`（存库口径 492022）—— 相对 HEAD 的 `578850` 正好少 **15%**（约 24 小时）。
  - 结构/钻机旁证（同一偏差的另一半）：`production_plans` 里 `mat_hangar_id` 只有两种取值 —— 制造计划 9 条用 4
    （`hangars` 表 `facility_type='npc'`、`rigs='[]'` → `structure_time_mod=1.0`），invention 计划 5 条用 8（raitaru → 0.85）。
    若实际作业在带钻机的工程复合体里做，应用时间还会再偏长 15%~30%。
  - TE 项的现实影响面：`production_plans` 中 `activity='invention'` 的 5 条 `te_level` **全为 0** →
    本次「TE 误乘」暂无实际数值影响，属潜在偏差（科研计划一旦带上非 0 `te_level` 就会额外多减时间）。
- 影响：用户报的「发明/拷贝/制造时间跟游戏对不上」在科研侧的主因。科研角色基本都会把高级工业理论练到 V，
  届时发明/拷贝/ME-TE 研究时长在应用里**整体偏长 15%**，直接影响作业排队、占用槽位时长与利润率判断；
  计划 364 就是 578850 s vs 正确的 492022 s。拷贝侧另有潜在偏差：TE 等级本不影响拷贝/发明时长，现行实现却对所有科研活动乘 `(1 − 0.01×TE)`。
- 下一步：修复在 task-1 中进行（工作区已改、**未提交**）：`domain/research.py` 新增 `adv_industry_skill` 形参、按 `1 − 0.03×高级工业理论` 覆盖全部活动，并删掉对全部科研活动乘的 TE 项；
  `services/scoring_service.py:979`（工作区行号）传 `skills.get(ADV_INDUSTRY_TIME_SKILL, 5)`，与制造侧 `domain/scoring.py:177` 的兜底 5 同口径；
  回归用例见 `tests/test_research_formulas.py:202-207`（引用同一组数值）。本条目等修复提交落库后改 `已关闭（<commit>）`。

## BL-011 工作区 shell 脚本被 core.autocrlf 转成 CRLF，WSL/Linux 下直接跑不了

- 类型：缺陷
- 状态：已关闭（aa4a9c8）
- 证据：
  - 本机 Git 配置会把 `.sh` 检出成 CRLF：`git config --get core.autocrlf` → `true`；仓库此前**没有** `.gitattributes`
    （本轮复核：`git cat-file -e HEAD:.gitattributes` → `fatal: path '.gitattributes' exists on disk, but not in 'HEAD'`），
    因此修复前 `git check-attr text eol -- scripts/run_tests.sh` 为 `text: unspecified` / `eol: unspecified`（Lead 实测；HEAD 无该文件已由本轮证实）。
  - 仓库里存的是 LF，被工作区转换过：`git show HEAD:scripts/run_tests.sh` 字节统计 **CRLF=0 / bare LF=103**；
    本轮 2026-10-11 **13:11:38** 实测工作区 `scripts/run_tests.sh` **CRLF=103 / bare LF=0**、`scripts/setup_worktree.sh` **CRLF=81 / bare LF=0**。
  - WSL 的 bash 本身没问题：`bash --version` → `GNU bash, version 5.3.9(1)-release (x86_64-pc-linux-gnu)`；
    `bash -c 'set -euo pipefail; echo ok'` → `ok`。
  - 同样内容只要带 CRLF 就炸（用**仍是 CRLF** 的 worktree 快照 `.dsh/worktrees/quiet-comet-060f/scripts/run_tests.sh` 复现，实测 CRLF=87：
    `head -3 | cat -A` 每行以 `^M$` 结尾；`sed -n 11p | cat -A` → `set -euo pipefail^M$`）：
    ```
    $ bash -n .dsh/worktrees/quiet-comet-060f/scripts/run_tests.sh
    .dsh/worktrees/quiet-comet-060f/scripts/run_tests.sh: line 20: syntax error near unexpected token `elif'
    .dsh/worktrees/quiet-comet-060f/scripts/run_tests.sh: line 20: `elif [[ -x ".venv/bin/python" ]]; then'
    ```
    同一命令写成 `bash -n ... && echo OK || echo BAD` → `BAD`；逐字执行该文件第 11 行 → `bash: line 1: set: pipefail: invalid option name`
    （`\r` 被并进选项名）。A/B 对照（同一个 WSL bash）：当前已是 LF 的 `scripts/run_tests.sh` → `bash -n` 输出 `PARSE_OK`，执行第 11 行输出 `line11-RC=0`。
  - 为什么以前没暴露：Git Bash（`C:\Users\Nightwatchman\AppData\Local\hermes\git\bin\bash.exe`，同为 5.3.9）容忍 CRLF；
    而裸 `bash` 在本机 PATH 里先命中 `C:\Windows\System32\bash.exe`（WSL）才踩到。CI 侧 Linux checkout 拿到的是仓库里的 LF，同样照不出来。
- 影响：本机 WSL / Linux / 容器里 `bash scripts/run_tests.sh <档>` 直接失败（先报 `set: pipefail: invalid option name`，
  `bash -n` 另报 `line 20` 的 `elif` 语法错误），把「换个解释器 / 换个系统」变成隐雷；
  且 `.dsh/worktrees/*` 下未重建的旧副本仍是 CRLF，会继续复现。属「只在 autocrlf 环境的新克隆/工作区出现」的缺陷 —— CI 与 Git Bash 两条路径都看不见。
- 下一步：修复在 Lead 手中（同一轮并行进行，**未提交**）：新增 `.gitattributes` 钉死 `*.sh text eol=lf`
  （工作区已有该文件，`git status` → `?? .gitattributes`；`git check-attr text eol -- scripts/run_tests.sh` 现已为 `text: set` / `eol: lf`），
  并把工作区两个脚本转回 LF（13:11:43 实测 `scripts/run_tests.sh` CRLF=0 / bare LF=103、`scripts/setup_worktree.sh` CRLF=0 / bare LF=81；
  `git status` → ` M scripts/run_tests.sh`、` M scripts/setup_worktree.sh`）。
  遗留：`.dsh/worktrees/*` 里的旧副本仍是 CRLF，需重建或忽略。本条目待提交落库后由 Lead 改 `已关闭（<commit>）`。

## BL-012 PLEX 未走官方 Global PLEX Market region（19000001），历史只能靠每日快照「攒」

- 类型：缺陷
- 状态：已关闭（ad9ef4e）
- 证据：
  - 官方口径：CCP dev blog《Global PLEX Market and SDE Update: 07-07-25》（By CCP Zelus，Published 2025-07-04，
    `https://developers.eveonline.com/blog/global-plex-market-and-sde-updates`，本轮 web_fetch HTTP 200）原文：
    「This update adds the new Global PLEX Market region (ID: `19000001`). Third-party developers can use the existing ESI market routes to query the current PLEX orders and history with this new region ID.」
  - 本轮实测（真实 HTTP 请求，不是转抄）：`https://esi.evetech.net/latest/markets/19000001/history/?type_id=44992&datasource=tranquility`
    → **HTTP 200 / 404 行**日线；首行 `{"average": 5371000.0, "date": "2025-09-01", "highest": 5594000.0, "lowest": 5341000.0, "order_count": 3224, "volume": 975238}`，
    末行 `{"average": 4724000.0, "date": "2026-10-09", "highest": 4848000.0, "lowest": 4710000.0, "order_count": 2699, "volume": 876925}`；
    `https://esi.evetech.net/latest/markets/19000001/orders/?type_id=44992&datasource=tranquility` → **HTTP 200 / 1000 行**（分页第一页）。
    即「一次请求拿到 404 天 PLEX 历史」是现成能力。
  - 代码里根本没有这个 region：`git grep -n "19000001"`（工作区）与 `git grep -n "19000001" HEAD` **均 0 命中**。
    HEAD 现状（行号口径为 `git show HEAD:services/importers/getprices.py`；该文件由 market-data 修，不属本条目）：
    `:38` 只有 `PLEX_TYPE_ID = 44992`；`:504` 把 PLEX 塞进五个贸易中心的历史候选集；
    `:577-578` 的注释自认「PLEX 的价格全服一致、没有区域划分（ESI 区块历史对它恒空），所以它的时间序列只能靠这个每日快照攒」；
    `:574-608` `save_global_price_snapshot` 退而用 `/markets/prices/` 的价按天写 `global_price_daily`（`:626-629` 在主流程里调用）。
  - 实测数据（`database/market.db` 只读）：`SELECT count(*) FROM price_history WHERE type_id = 44992` → **0**（五个区域全空）；
    `global_price_daily` → **7 行**，`type_id=44992`，`date` ∈ `2026-10-05 ~ 2026-10-11` —— 只能从部署那天开始攒。
  - 读端：`services/market_index_service.py:522-542` `_load_global_observations` 读 `global_price_daily`；
    `:528-530` 明确「这张表只有价格，没有成交」并把成交量固定给 0 —— 而官方 region 的历史**带** `order_count`/`volume`（见上）。
- 影响：大盘 / 走势图里的 PLEX 只有最近 7 天，长周期历史整段缺失（PLEX 是指数固定锚，`market_index_service.py:93` 的 `PLEX_TYPE_ID`），
  而官方 region 一次请求就能补 404 天。属「数据一直公开在那儿，我们没去拿」。
- 下一步（不归我，market-data 负责）：新增 `PLEX_REGION_ID = 19000001`，PLEX 的历史与订单只从该 region 拉并写入 `price_history`；
  读端优先 `price_history`、`global_price_daily` 退为兜底；顺带复核 `:528-530` 的「没有成交」口径是否该改成读官方 region 的 `volume`。

## BL-013 市场历史按「全候选 × 全区域」拉，一轮 26% 的请求注定返回空

- 类型：缺陷
- 状态：已关闭（ad9ef4e）
- 证据：
  - 候选集（`database/blueprint.db` 只读实测）：`blueprint_products` 里 `activity IN ('manufacturing','reaction')` 的产物 **4908** 个，
    `blueprint_materials` 同条件的材料 **1646** 个，并集 **5553**，再 `| {PLEX 44992}` → **5554** 个 type。
    构造处见 HEAD `services/importers/getprices.py:497-504`；五个区域 id 见 `core/constants.py:6-12`
    （Jita `10000002` / Amarr `10000043` / Dodixie `10000032` / Rens `10000030` / Hek `10000028`）。
  - 现状覆盖（`database/market.db` 只读，`price_history` 的 DISTINCT type_id）：
    Jita `10000002` 4772 / Amarr `10000043` 4340 / Dodixie `10000032` 3941 / Rens `10000030` 3451 / Hek `10000028` **2103（38%）**。
  - 用同库 `market_prices`（每轮订单拉取写入；列为 `type_id/region_id/buy_price/sell_price/adjusted_price/buy_volume/sell_volume/fetch_time`）
    的 `COALESCE(buy_volume,0)+COALESCE(sell_volume,0) > 0` 判「该区域有挂单」，与候选集求交：
    Jita 4865 / Amarr 4559 / Dodixie 4194 / Rens 3774 / Hek 2231。
  - 按「有挂单 ∪ 已有历史」过滤，本轮实测（逐区域 union 求和）：
    ```
    现状请求 5554 × 5 = 27770 → 过滤后 20482，省 7288（26%）
    分区域省下：Jita 675（12%）/ Amarr 883（16%）/ Dodixie 1144（21%）/ Rens 1495（27%）/ Hek 3091（56%）
    过滤后各区域请求数：4879 / 4671 / 4410 / 4059 / 2463
    ```
  - 代价侧实测：「有历史但当前无挂单」的 `(type, region)` 只有 **14~285 个/区域**
    （Jita 14 / Amarr 112 / Dodixie 216 / Rens 285 / Hek 232）—— 因为过滤保留了「已有历史」这一支，不会丢已有序列。
  - 根因（HEAD 口径）：`services/importers/getprices.py:386-407` 的 `_pending_history_tasks` 只做 TTL 过滤
    （`:405-406` 是 `type_ids - fresh`），**完全不看该区域有没有挂单**，于是 5554 × 5 个组合全量进队列。
  - 旁证（用户 2026-10-11 贴的后台刷屏）：「市场历史为空/404，跳过 type=… region=…」大量来自 `region=10000043` / `region=10000032`
    —— 即 Amarr / Dodixie 的冷门 type。
  - 口径说明：以上均为 **2026-10-11 本库快照**的实测值，随库更新会浮动，量级稳定。
- 影响：`HISTORY_TTL_SECONDS = 12h`（`getprices.py:34`）到期后，每轮白跑约 **7300** 个注定为空的请求；
  按全局限流 20 req/s 折算约 **6 分钟**纯等待，还把「历史为空/404」的噪声刷进日志、掩盖真正的失败。
- 下一步（不归我，market-data 负责）：在 `_pending_history_tasks` 排队前按 `market_prices` 的挂单量做前置过滤，
  并保留「已有历史」分支以免丢序列；上面这组实测值可直接当回归基线。

## BL-014 制造计划时长被 `hours_per_run` 的 2 位小数 round 量化（确证缺陷）

- 类型：缺陷
- 状态：open
- 证据：
  - 中间量在 domain 层就被砍到 2 位小数：`domain/scoring.py:269` `"hours_per_run": round(hours_per_run, 2)`
    （同形另见 `:233`、`:472`、`:499`）；计划级再由 `services/scoring_service.py:347`（读 round 后的值）
    → `:368` `total_time_hours = hours_per_run * runs_only` → `:663` `"calculated_time": round(total.get("total_time_hours", 0) * 3600)` 放大。
  - 量化步长 ±0.005 h = **±18 s/轮**，随 runs 线性放大（上界 ±0.005×runs×3600）。本轮实测：库值反推的单轮小时数**恰好落在 2 位小数上**（round 的指纹）：
    ```
    id=424 runs=2040 me=10 te=20 hangar=4：calculated_time=146880 → 146880/3600/2040 = 0.02 h/轮（= 72 s/轮）
              verifier 复算精确值 153396.6 s（= 75.1944 s/轮）→ 偏短 6516.6 s（−4.24%）；量化上界 ±36720 s
    id=401 runs=108  me=10 te=20 hangar=4：66096 → 0.17 h/轮（612 s/轮）；精确 66977.3 s（620.16 s/轮）→ −1.32%；上界 ±1944 s
    id=358 runs=10   me=0  te=0   hangar=4：30240 → 0.84 h/轮（3024 s/轮）；精确 30077.8 s（3007.78 s/轮）→ +0.54%；上界 ±180 s
    ```
    即单轮只差 3.19 s，×2040 轮就成了 6516.6 s —— 偏差全部来自 round，不是别的链路。
  - 这是「制造时间跟游戏对不上」的**确证代码原因**，与科研侧 3388 漏套（BL-010）相互独立，属既有缺陷。
  - 消费点（改前必须一并确认；本轮 `git grep -n "hours_per_run"` 实测）：`services/scoring_service.py:347,368,370`（总量 / 日产量 / iskph）、
    `ui_qml/workers/score_worker.py:105`、`ui_qml/workers/compare_chart.py:107,167`、`ui_qml/bridge/all_items_bridge.py:167,237`。
    另注：`domain/scoring.py:247`/`:485` 的单轮 `isk_per_hour` 用的是**未 round** 的局部变量，
    而计划级 iskph（`services/scoring_service.py:369`）用 round 后的值 → 同一指标单轮/整批两个口径。
- 影响：runs 大的制造计划时长最多偏 ±0.005×runs 小时（2040 轮即 **±10.2 h**），本轮实测 −4.24% ~ +0.54%；
  连带 `daily_output`、`iskph` 与交付期判断一起偏。
- 下一步：中间量保留未 round 精度（例如 domain 层另给 `seconds_per_run`，或只在下发给 UI 展示时 round），
  并统一单轮/整批的 iskph 口径；改动前先过一遍上面列的消费点。纯计算改动 → 按判定表补最小回归。

## BL-015 【存疑】蓝图所需技能被当作「每级 −1%」二次计入，与工业/高级工业理论的减免重叠

- 类型：缺陷（待证据定案）
- 状态：deferred（等一次游戏内 A/B；**定案前不要改**）
- 证据：
  - `services/scoring_facade.py:206-216`：注释说意图是「该蓝图制造活动所需技能名 → 每级 −1%」（引 11452 机械工程学的文案），
    但 SQL 只按 `bs.activity = 'manufacturing'` 取**全部**技能名（`:213`），未排除 3380/3388；
    `domain/formulas.py:262-263` 再对每个技能 `bp_mod *= 1 − 0.01×等级`。
  - 而这两个技能的减免已分别由 `domain/formulas.py:258-260` 的 `INDUSTRY_SKILL_MULT`(4%) / `ADV_INDUSTRY_SKILL_MULT`(3%) 计过一次 → 重叠。
    量级：单技能在场最多多减 **5%**；3380 与 3388 同时在场的蓝图最多 **9.75%**（`1 − 0.95×0.95`，两项均 5 级）。
  - 覆盖实测（`database/blueprint.db` 只读）：有 manufacturing 技能的蓝图（distinct blueprint_type_id）共 **4691** 张，
    其中 `blueprint_skills` 带 **3380 工业理论**的 **4260** 张，带 **3388 高级工业理论**的 **19** 张。
  - 反证依据（本轮实测）：
    - 本机 SDE `data/dogmaAttributes.yaml` 的 `1982:` 条目是 `Manufacturing Time Bonus`，文案
      `Skill bonus per level to manufacturing time efficiency. Only applies to skills required to manufacture the blueprint.`
    - ESI 实测 `https://esi.evetech.net/latest/universe/types/11452/` → 机械工程学（group 270）**带 `1982 = -1.0`**；
      `types/3380/`（工业理论，group 268）与 `types/3388/`（高级工业理论，group 268）**都不带 1982**。
    - 文案对不上：3380 自身是「每升一级，制造时间缩短4%」（`data/typeIDs.yaml`）、3388 是「3% / 所有制造和研究时间」，
      两者都不是「只作用于该蓝图所需技能的 −1%」。
    - 即「−1%/级」的适用对象应是带 1982 的技能（verifier 口径：11452 机械工程学等 22 个科学技能 + 6 个船体建造技能共 28 个；
      该计数本轮未在本地复核，标注为 verifier 口径）。
- 影响：若反证成立，T1/T2 制造时长被额外多减 5%（3380+3388 同时在场的蓝图 9.75%），方向与 BL-010 / BL-014 相反（应用偏**短**）。
  另一种解释也存在（CCP 把 3380/3388 也算作「蓝图所需技能」，4%/3% 与 1% 文案叠加），故**未定论**。
- 下一步：跑一次游戏内 A/B（单流程 T1 模块，比 industry 窗口时长），能对上哪一侧就按哪侧改；定案前不动代码。
  定案后再改 `已关闭（<commit>）`，并把结论回写 `domain/formulas.py` / `scoring_facade.py` 的注释。

## BL-016 ME/TE 研究时长用「首级 × 目标等级」线性近似，高等级真值差一个数量级

- 类型：缺陷（已知近似，但被当精确值用）
- 状态：open
- 证据：
  - `services/scoring_service.py:957-982`：ME/TE 研究把 `target_level = max(1, runs)`（`:958`）当作业数（`:967` `job_k = target_level`），
    `science_job_time(base_time, ...)`（`:971-981`）里的 `base_time` 是**首级**时长，`:982` `total_seconds = time_per_job * job_k`
    → 线性乘目标等级；`domain/research.py:272-273` 的 docstring 也自认「base_time 对 research_material/research_time 是**首级**时长……
    本函数不做逐级累加，调用方需知这是首级近似」。
  - 真值要逐级累加：Wiki「How long does research take?」表 105 / 250 / 595 / 1,414 / 3,360 s，且 `Research duration = Base duration × Blueprint rank`。
    本地可交叉验证 rank：bp43546 的 `research_material` 与 `research_time` 首级时长都是 **1260 s**（`database/blueprint.db`），
    `1260 / 105 = 12` **整** → rank 12（Wiki rank 表里 12 正是 T1 warfare links，而 43546 = 游击战指挥脉冲波蓝图 I）。
  - 实测对比：bp43546 研究到 ME5 —— 真值 `12 × (105+250+595+1414+3360)` = **68688 s**，
    应用只算 `1260 × 5` = **6300 s**，**偏短 10.90×**。
  - 代码自己标了近似：`:969` `extra = {"target_level": target_level, "time_is_approximate": True}`；
    UI 侧提示见 `ui_qml/bridge/cost_breakdown_bridge.py:422`（`（时长为首级近似）`）。
  - 知识库那边的措辞比实现更肯定（`docs/eve_wiki_knowledge_base.md:95-96`）—— 本轮已就地补上「实现为首级近似、高等级偏短约 10 倍」的说明。
- 影响：目标等级 ≥2 的 ME/TE 研究计划时长系统性偏短，等级越高越离谱（ME5 约 10.9×）；
  虽然有 `time_is_approximate` 标记，但「研究多久做得完 / 占槽多久」的判断仍会被误导。
- 下一步：在 `domain/research.py` 里改成逐级累加（Wiki 表 + rank，或从 SDE 的等级时长序列取），
  或至少把 UI 近似提示的强度提到与偏差量级相称；改前先确认 `research_target_level` 与 `runs` 的语义
  （现状是拿 `runs` 兼作目标等级，见 `scoring_service.py:958`）。

## BL-017 `HISTORY_KEEP_DAYS = 180` 的裁剪实际无效，库里一路攒到 404 天

- 类型：缺陷
- 状态：deferred（**与「要保留多长的历史窗口」是同一个决策，先登记不要改**）
- 证据：
  - 声明处：`services/importers/getprices.py:79` `HISTORY_KEEP_DAYS = 180`（HEAD 为 `:66`；该文件已被 task-6 的 PLEX region 改动整体下移，本条按**工作区**行号）；
    `:585` 用它算 `date_cutoff`，`:623` 传给 `_save_histories`。
  - 实现处：`services/importers/getprices.py:467-491` `_save_histories` —— `:478` 先
    `DELETE FROM price_history WHERE type_id = ? AND region_id = ? AND date < ?`，`:481-488` 再 `executemany(INSERT OR REPLACE)` **插入本轮拉到的全部行**；
    `:470` 的 docstring 仍写「把每个产物的历史限制在 `HISTORY_KEEP_DAYS` 窗口内」。而 ESI `history` 返回的是**滚动窗口**
    （PLEX 实测 404 天、2025-09-01 起，见 BL-012），于是**新插入的行里早于 cutoff 的部分根本没被裁**，
    下一轮那条 DELETE 也拦不住同一批行被重新插回来。
  - 实测（`database/market.db` 只读，2026-10-11）：`price_history` 最早日期 **2025-09-01**、最晚 **2026-10-09**、
    总行数 **3,544,860**；distinct `(type_id, region_id)` **18,607**（= 各区域覆盖 4772+4340+3941+3451+2103）。
    按同一覆盖密度折算，180 天窗口约 `3,544,860 ÷ 403 天 × 180 ≈ 1.58M` 行。
- 影响：market.db 行数约为设计预期的两倍；注释与实现相反，后续维护者照注释判断会以为窗口是 180 天。
- 下一步：修法有两条 —— 插入时按 `date_cutoff` 过滤 `rows`，或插入后再补一次 DELETE（并同步 `:470` 的 docstring）。
  **但真修会把 PLEX 历史从当前 404 天裁到 180 天**（BL-012 刚把 PLEX 历史接进来），所以等用户对「历史窗口要多长」表态后再动。

## BL-018 【待决策】PLEX 的 `market_prices` 行仍是 baseline 兜底，不是真实盘口

- 类型：缺陷
- 状态：open（需要一次独立任务；动代码前先做只读影响面审计）
- 证据：
  - 库里现状（`database/market.db` 只读，2026-10-11）：`market_prices` 里 44992 五个贸易区域各一行，五条**值完全相同**：
    `buy_price = 4712023.41`、`sell_price = 0.0`、`adjusted_price = 0.0`、`buy_volume = 0`、`sell_volume = 0`（`fetch_time = 2026-10-11 05:00:2x`）。
  - 来源已确认为 baseline：本轮实测 `https://esi.evetech.net/latest/markets/prices/`（HTTP 200，15,988 条）中 44992 是
    `{'adjusted_price': 0.0, 'average_price': 4712023.41, 'type_id': 44992}` —— 与库值逐字段相同。
    写入链：`services/importers/getprices.py:143-159` 把 `average_price` 塞进 `buy_price`、`adjusted_price` 塞进 `sell_price`、两个量写 0；
    `:355-373` 每个区域 `merged = dict(baseline)` 后由订单覆盖，`:374-381` 一次性 INSERT —— PLEX 没有区域订单可覆盖，baseline 原样落库。
    （该机制 HEAD 同样存在：HEAD `:130-146` / `:345` / `:364`，工作树只是行号下移。）
  - 区域市场对 PLEX 已无挂单（本轮实测）：`/markets/10000002/orders/?type_id=44992&order_type=all` → HTTP 200 / **0 条**；
    `/markets/10000002/history/?type_id=44992` → HTTP 200 / **0 条**（最后一个交易日已滚出窗口）。
  - 真实盘口在官方 GPMR：`/markets/19000001/orders/?type_id=44992&order_type=all` → HTTP 200 / **1000 条** / `X-Pages: 2`，
    首条 `{"price": 5090000.0, "volume_remain": 530, "is_buy_order": false, "location_id": 60004462, "system_id": 30000119, ...}`；
    响应头 `X-Ratelimit-Group: market-order`、`X-Ratelimit-Limit: 12000/15m`、`X-Esi-Cache-Status: HIT`（另有 `Expires` / `Cache-Control: public`）。
  - task-6 按指令**只修历史、订单侧未动**：PLEX 历史现在走 `PLEX_REGION_ID`（`getprices.py:50`，拉取见 `:563`），
    但本轮实测 `price_history` 里 44992 仍是 **0 行**（新链路尚未跑过一轮）。
- 影响：贸易页 / 大盘上 PLEX 的「挂单价 / 买卖量」是假的 —— 成交均价冒充买价、卖价恒 0、量恒 0；
  而区域市场对 PLEX 早已没有盘口，读端拿到的却是五条看起来正常的行，无法从数值本身察觉。
- 下一步：单独立项（涉及 `domain/market_depth` 与多个读端）。market-data 在 task-6 报告里已整理 15+ 处受影响读端 `file:line` 清单，动工前先取那份清单；
  建议先做只读影响面审计，确认读端能否区分「baseline 兜底行」与「真实盘口行」，再定写入改造与读端范围。

## BL-019 发明结果回填框「每张 0 流程」+ 尝试次数漏乘 parallels

- 类型：缺陷
- 状态：已关闭（470a966 修「每张 0 流程」；0a6cdf7 修 attempts 口径）
- 证据（2026-10-11 用户截图 + Lead 复算）：
  - 截图：发明结果回填框（游击战指挥脉冲波蓝图 II）显示「成功产线数 10 → = 0 流程」与
    「成功 0 流程…每张 0 流程，共 0 流程」。
  - 根因 1：`ui_qml/views/industry/complete_plans_dialog.py` 的 `_ask_invention_outcome`
    只从 `plan["breakdown"]` 取 `runs_per_bpc`；表格行没跑过评分时 breakdown 为空 → 得 0，
    而那条退化路径要求 `expected_runs > 0`（它同样是 0）→ 失效，`runs_per` 停在 0。
    权威值：`blueprint_products`(43546, 'invention', 43611, quantity=10) + 放大装置解码器
    `runs_mod=+9` → 应为 **19 流程/张**。
  - 根因 2：尝试次数写成 `max(int(plan.get("runs") or 1), 1)`，**漏乘 `parallels`**：
    计划 id=364（runs=10、parallels=5）启动时按 **50 次**扣了解码器 34203×50 与数据核心，
    框里却显示「本计划尝试次数：10」。正确口径同评分侧 `scoring_service` 的
    `total_attempts = runs × parallels`（也就是 `breakdown["attempts"]`）。
- 影响：用户按框架提示填多少条成功产线，都会被换算成 0 流程入库；尝试次数偏小还让
  「期望成功」估算偏低，用户没法判断该填多少。
- 下一步：已修 —— `_invention_defaults_from_sde` 回 SDE 取权威值，并把 breakdown→SDE
  兜底公式抽成单条/列表共用的 `_invention_expected`（`attempts` 优先取
  `breakdown.attempts`，否则 `runs × parallels`）。回归见
  `tests/test_research_dispatch.py::TestInventionOutcomeDefaults` 与
  `tests/test_industry_dialogs.py::TestCompletePlansInventionBatch::test_attempts_multiplies_parallels`。

## BL-020 启动小助手刷新列表后滚动位置跳回顶部

- 类型：缺陷
- 状态：已关闭（ed2780f）
- 证据（launcher-scroll 队友 2026-10-11 用临时离屏探针实测，探针在 `%TEMP%`、未入库；本轮我复核了代码链与回归用例，探针数值按队友口径引用）：
  - 窗口 1000×700、40 行（`contentHeight=2476`、ListView 高 530），先设 `contentY=500`：
    - `_start(pid)`（该行 pending→in_progress，触发 `_on_poll`）→ **500 → 0**，行数与 `contentHeight` 都不变；
    - QTest 真点视口内行内的「启动」按钮 → **500 → 0**。
  - 机制隔离（绕过页面代码直写 `ListView.model`）：换**内容不同**的新数组（长度/行高不变，只改一行 `statusText`）→ **500 → 0**；
    把**同一份内容**原样再给一次 → **500 → 500**。→ Qt `QQuickItemView::setModel()` 对**相等**的 QVariantList 提前返回、不重建，**内容一变**就整视图重建回顶部。
  - 由此「只有点启动才跳」的真相是：点启动必然改动那一行；而 5s 轮询里运行中计划的 `durationText` 每轮都重算，**轮询同样在跳**（实测行数 40→80 → 500→0；同长度只改一行 → 500→0）。
  - 根因链（**工作区行号**；同一提交里 `_sync_rows` 的 docstring 加长 5 行，故 HEAD 行号 = 下面各值 −5，即 HEAD `:983`/`:1322`/`:1367`）：
    `ui_qml/views/industry/production_launcher.py:988` `_on_row_start` → `:1327` `_start` → 成功后 `:1372` `self._on_poll()`
    → `:671` `_apply_filters` → `:825` `_sync_rows`（整表重建）→ `:843` `self._notify_rows()` → `:511-513` 桥 `notify_rows()`
    → QML 换数组（HEAD 为 `ui_qml/qml/pages/LauncherWindow.qml:301 model: win.launcher ? win.launcher.rows : []`）。
  - 项目自带旁证：`_sync_rows:828` 自述「每次全量重建」；`_on_tick:548-552` 明说「（比整表重置便宜，）也不会把滚动位置与选中态冲掉」。
- 影响：用户滚到列表中间逐条启动产线时，每点一次「启动」列表就跳回开头，得重新滚回原处找下一条（小助手正是逐条启动的主界面，体验直接受损）。
- 下一步：已修（QML 侧自保滚动位置）——`ui_qml/qml/pages/LauncherWindow.qml:317-318` 改为 `model: rowsModel` + `onModelChanged: restoreKeepContentY()`；
  `:320-328` 私有属性 `rowsModel` / `keepContentY` 与 `applyRows()`（**先记 `contentY` 再换数组**，不挂绑定以免每滚一像素重算 model）；
  `:333-341` `restoreKeepContentY()` 内用 `Qt.callLater` 补一拍还原（`setModel()` 返回时 `contentHeight` 可能还没重算完，会把 `contentY` 夹小）；
  `:345` `Component.onCompleted: applyRows()`。Python 侧只加了契约 docstring（`production_launcher.py:825-833`，diff 为 +9/−1），未改逻辑。
  回归：`tests/test_production_launcher.py:1161-1217` 的 `TestLauncherScrollKept.test_list_keeps_scroll_position_when_a_row_changes`（断言 `abs(contentY − 500) ≤ 1.0`，
  失败信息「期望仍在 500，实得 contentY=…」）；敏感性已验证：临时回退 QML 修复后该用例红（实得 `contentY=-0.0`）。
  ⚠️ 该文件 `tests/test_production_launcher.py:20` 有 `pytestmark = pytest.mark.ui`，`validate` 档会跳过 → 验证要走 `ui-retest` 或直接点名这个 node id（CLAUDE.md 的已知假绿坑）。
  改后实测：`_start` 500→500、真点启动按钮 500→496（那 4px 是既有的「把选中行滚进视口」）、纯轮询 700→700。

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

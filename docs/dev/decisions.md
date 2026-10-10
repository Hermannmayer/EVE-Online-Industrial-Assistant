# 决策记录

本页是**决策因果链归档**：把仓库里已经生效、但只有结论没有「为什么」的架构与流程决策，补上背景、理由、证据。

**边界与优先级**

- 本页**以 `CLAUDE.md` 为准**。`CLAUDE.md` 是「当前生效的规则」（祈使句，写给执行者）；本页是「当时的因果链与证据」（叙事 + 出处，写给想改规则的人）。
- **`CLAUDE.md` 的条款变更时，本页只更新对应条目的「后果」引用，不得反向约束 `CLAUDE.md`。** 本页不构成新规则：读到这里发现某条规则「理由不成立」，正确动作是改 `CLAUDE.md`（或先登记到缺陷台账），不是拿本页去否定条款。
- 只收录「已验收确认、后续还会反复影响实现」的规则。一次性 bug、临时修复、无法复现的问题一律不收录。新发现的缺陷/待决策项按 `CLAUDE.md` 文档索引的约定先登记，不写进本页。

**行号坐标**

证据栏里的 `文件:行号` 是本页编写时（本次任务）实际读取到的坐标。行号会随文件改动漂移 —— 复核时以符号名、小节名、提交 hash 为准。

⚠️ 证据栏里 `.claude/` 下的文件（`.claude/audit/*.md`、`.claude/plans/*.md`）**不入仓库**：`.gitignore:113` 有 `.claude/`，`git ls-files .claude` 无输出。它们只在本地工作区可见，属**二手证据**；每条 ADR 的主要证据都是仓库内的文件或 commit hash，`.claude/` 引用只作补强。克隆仓库后复核不到它们属预期，不是文件被删。

**为什么有这一页**

`CLAUDE.md` 里六条克制条款是在一次性重写（提交 `d0a8253`，2026-09-17）中整体写入的，条款本身没有出处注释；铁律与测试边界节同理。于是「为什么」只剩在提交历史、审计报告与测试 docstring 里。本页把它们捡回来。**查不到出处的条目写在末尾「无法溯源的决策」，不猜。**

## 条目索引

| 编号 | 标题 | 状态 | 现行约束 |
|---|---|---|---|
| ADR-001 | 新增抽象层前先证明有两个现存调用方 | 生效 | 克制条款 1 |
| ADR-002 | 组合根冻结：`bootstrap/` 只减不增，`core/container.py` 不推进迁移 | 生效 | 克制条款 2 |
| ADR-003 | 只有 `user.db` 做版本化迁移，且表结构变更只有一个入口 | 生效 | 克制条款 3；铁律 Schema |
| ADR-004 | 测试预算与测试判定表 | 生效 | 克制条款 4 + 测试判定表 |
| ADR-005 | 流程冻结：要新增钩子/CI/检查脚本，先删一个同等成本的 | 生效 | 克制条款 5 |
| ADR-006 | 配色只有一个 token 源：`ui_qml.theme.registry` | 生效 | 铁律 配色 |
| ADR-007 | 术语只有一个来源：`services.terminology` + `terminology.json` | 生效 | 铁律 术语 |
| ADR-008 | 分层边界由测试护栏守，不靠评审 | 生效 | 架构节分层 |
| ADR-009 | `ui_pyside6/` 整体删除，新代码只写 `ui_qml/` | 生效 | 架构节 `ui_pyside6` 禁令 |
| ADR-010 | 4 库分离：reference / market / user / blueprint | 生效 | 架构节 4 库独立 |
| ADR-011 | QML 组件绑定 `Theme` 单例，不用 `add_theme_listener` | 生效 | 架构节 UI 主题 |
| ADR-012 | 测试分档互斥：`validate` 与 `ui-retest`，以及「假绿」这条踩坑 | 生效 | 测试边界节 |
| ADR-013 | `docs/api/**` 由脚本生成，不手改 | 生效 | 文档索引 `docs/api/**` 行 |
| ADR-014 | `CHANGELOG.md` 是唯一更新日志源，由 python-semantic-release 维护 | 生效 | 文档索引 `docs/dev/versioning.md` 行 |

---

## ADR-001 新增抽象层前先证明有两个现存调用方

- **状态**：生效
- **背景**：项目曾按「更符合分层」的直觉建过一层 `application/`（含 `application/scoring_facade.py`），并让 `services/` 依赖它。它没有第二个消费方，长期只承接一个转发调用点。
- **决策**：新建 `services/*.py` 模块 / repository / facade / Protocol / 事件总线 / 缓存层 / 重试框架之前，必须先拿出至少 2 个现存调用方的 `文件:行号`；拿不出就内联在使用处。缺陷修复不受此限（就地改，不顺手重构）。
- **理由**：那一层被证明是纯转发 —— 2026-08-16 的提交 `7b19ce0` 把它整个删掉（`application/__init__.py`、`application/scoring_facade.py`），调用方直接走 `services/scoring_service.py`，而 `services/scoring_service.py` 只改了 6 行。**删掉不需要动业务，说明它当初就没承担职责**：真正在去重或隔离的抽象，删掉必然要改调用点。「以后可能会用」在本仓的实际生命周期是「先多一层、后被删」。「2 个调用方」是这条判断的可执行化：有 2 个真实消费方 = 抽象在承担去重职责；只有 1 个 = 转发。
- **后果**：克制条款 1（`CLAUDE.md` 第 11-13 行）。执行细节：说不清新调用方时，写成模块内函数或直接内联。
- **证据**：
  - `git show --stat 7b19ce0` → 2026-08-16 `refactor: remove dead application layer and align architecture docs`，删除 `application/__init__.py`、`application/scoring_facade.py`，改 `services/scoring_service.py`（6 行）、`CLAUDE.md`（20 行）、`docs/dev/architecture.md`（79 行）。
  - `CLAUDE.md:11-13`。
  - 事后样本：`.claude/plans/2026-09-25-六项改动.md:17`（已批准计划把「不新增 `services/*.py`」写进「不做」清单）。
  - **阈值「2」本身**没有找到推导记录，见「无法溯源的决策」。

## ADR-002 组合根冻结：`bootstrap/` 只减不增，`core/container.py` 不推进迁移

- **状态**：生效
- **背景**：IOC 容器原先在 `core/container.py`（`01bc5d9 refactor: IOC容器化`）。2026-08-16 的 `c72202c` 新建 `bootstrap/container.py`（新增 192 行），同时把 `core/container.py` 削到只剩兼容转发（净减 189 行）。迁移做到一半就停了，两条 import 路径并存。
- **决策**：`bootstrap/container.py` 不再新增服务属性；`core/container.py` 的转发保留、**不推进迁移**；新依赖写构造函数默认值，不走容器。
- **理由**：半程迁移比任何一端都差 —— 两条路径并存时，每个新服务都要重新决定走哪条，而两条都能跑，所以这个决定会被反复做、反复做出不同答案。此处接受的取舍是**两端同时冻住**：旧路径不删（不改动大批调用点）、新路径不加（不扩大表面积）。「新依赖写构造函数默认值」是冻结的出口 —— 需要新依赖时不必解冻容器，因此这条冻结不会挡住功能开发（2026-09-25 已批准的计划正是靠它做到「不碰容器」）。
- **后果**：克制条款 2（`CLAUDE.md` 第 14-15 行）。相关现状描述见 [架构说明](/dev/architecture)：`core/container.py` 标注为**兼容转发**，`AppContainer` 管理 15+ 服务。
- **证据**：
  - `git show --stat c72202c` → `bootstrap/container.py` +192、`core/container.py` −189，提交信息自述 “keep core/container as compatibility shim”。
  - `git log --oneline -1 01bc5d9` → `refactor: IOC容器化 + 安装费/损耗公式修正`。
  - `docs/dev/architecture.md:105`（`container.py` ｜ **兼容转发**）、`:169`（`AppContainer` 管理服务生命周期，`core/container.py` 为兼容转发）、`:94`（“15+ 服务”）。
  - `.claude/plans/2026-09-25-六项改动.md:17`（「不动 `bootstrap/container.py`、`core/container.py`」）。

## ADR-003 只有 `user.db` 做版本化迁移，且表结构变更只有一个入口

- **状态**：生效
- **背景**：四个库都跑 `PRAGMA user_version` 迁移，但 `reference.db` / `market.db` / `blueprint.db` 的内容来自 SDE / ESI 重导，不含用户输入；`user.db` 装的是 `production_plans`、`user_blueprints`、`hangars` 等用户资产，迁移跑一半不可逆。历史上还出现过「迁移函数缺失却静默推进版本号」与「备份失败仍继续迁移」两类问题。
- **决策**：
  1. 只有 `user.db` 需要版本化迁移保护；其余三库视为**可重建缓存**，表结构变了直接重导。迁移前对 `user.db` 必须备份成功，否则**阻断**迁移；缓存库备份失败不阻断。
  2. 表结构变更必须在 `services/schema_migrations.py` 注册，不得在业务代码里写 `ALTER TABLE` / `DROP TABLE`；加列只改 `DB_SCHEMA_VERSIONS` + `_MIGRATIONS` 两处，用 `_add_columns`，不从零手写 `sqlite3.connect` 三段式。
- **理由**：迁移的仪式强度应当由**数据可否重建**决定，而不是由库的数量决定。对可重建库做「备份失败即阻断」，只是给不需要保险的东西买保险（重导一次就恢复）；而 `user.db` 一旦迁到一半，用户数据没有第二次机会 —— 代码里的原话是「user.db 是唯一不可重建的用户数据 —— 没有快照就不许动」。另一半理由是幂等：`_add_columns` 已把「列已存在则跳过」做掉一次，手写三段式意味着这件事要被重复实现几十遍，漏一次就是启动崩溃。`ref` 至今停在 v1（没有任何迁移函数），正是「可重建库不需要迁移史」的极端样本。
- **后果**：克制条款 3（`CLAUDE.md` 第 16-17 行）；铁律 Schema（`CLAUDE.md` 第 99-100 行）。迁移规范见 [Schema 迁移规范](/dev/schema-migration)，落点见 [架构说明](/dev/architecture) 的「Schema 迁移与备份」。
- **证据**：
  - `services/schema_migrations.py:915-919`：「user.db 是唯一不可重建的用户数据 —— 没有快照就不许动；缓存库（ref/mkt/bp）缺列可直接重建，不因备份失败阻断。」以及 `backup is None and db_alias == "user"` 的阻断分支。
  - `services/schema_migrations.py:27-31`：`DB_SCHEMA_VERSIONS = {"ref": 1, "mkt": 4, "user": 22, "bp": 3}`。
  - `services/schema_migrations.py:925-927`：「迁移函数缺失时**不得**推进版本号」及其报错分支。
  - `docs/dev/schema-migration.md:1-4`（集中式管理 + 禁止业务代码 `ALTER TABLE`/`DROP TABLE`）、`:36-48`（`_add_columns` 幂等加列）、`:80-86`（注册清单四步，第 4 步要求补 `tests/test_schema_migrations.py`）。
  - 提交：`bab2e76`（2026-07-31「迁移原子性」）、`b669667`（2026-07-31「schema 迁移收敛」）、`bf40064`（2026-09-18「user 库备份失败阻断迁移；迁移缺失不再静默推版本号」）。
  - 测试：`tests/test_schema_migrations.py:1-9`（覆盖 F9 v0 判定、F15 索引、幂等、备份保留、`_rebuild_table` 回滚）、`:50-70`（v0 库补跑全部迁移）。

## ADR-004 测试预算与测试判定表

- **状态**：生效
- **背景**：测试数长期单向膨胀（2026-09-17 的 `299a635` 一次瘦身把 2526 条削到 2281 条），而不少用例断言的是外观值、标准库行为、纯转发接线（`902847f`，2026-09-17，提交信息自述「删掉脆弱的源码字符串/几何/signature 断言」）。用例越多越慢，UI 档实测 221s~445s，直接拖慢开发循环。
- **决策**：单次任务新增测试 ≤ 被测代码行数 × 0.5；能 `parametrize` 的不写独立用例；纯布局/几何/像素/样式断言不写测试（用截图核对）；修 bug 至少补 1 条最小回归；不为没发生过的场景写预防性用例。**要不要写由「测试判定表」回答，不是每次改动都要补测试。**
- **理由**：判定表的总则把它说清了 ——「测试是给『会坏』的逻辑买的保险」。不含分支/数值的改动（重构、转发/委托层、改注释、格式化、删死代码）没有可坏的东西，为它们写的用例只能证明「代码还是我写的这样」，改实现就红。反向的代价也很实：布局一改就红的几何断言与业务无关，保留下来只会训练出「红了一律当噪音」的习惯。骨架第二次出现时，正确动作是加进参数化列表或收敛成共享实现，而不是抄第二遍（先例：`tests/test_qml_dialogs.py` 的参数化列表把几十个对话框的「能加载 + 无告警」收成一条用例；`6d8444a`（2026-09-20）把 5 份逐字复制的页面加载骨架收敛成各一行）。**结构重复无法自动测**：2026-09-20 试过三种口径（同名 / 同文件同断言 / 跨文件代码块），信噪比都不合格，所以没有做成自动检查，只保留人工三条判据。
- **后果**：克制条款 4（`CLAUDE.md` 第 18-21 行）+ 测试判定表（`CLAUDE.md` 第 26-75 行）。体检工具 `scripts/test_audit.py` 手动跑、只报告不改动（`CLAUDE.md` 第 72-75 行）。
- **证据**：
  - `git show --stat 3eacaa0` → 2026-09-19 `chore(测试规范): 加测试判定表与体检工具`：新增 `scripts/test_audit.py` 260 行、`tests/test_test_audit.py` 47 行、`CLAUDE.md` +41 行。
  - 后续细化：`f5ec120`（2026-09-19，判定表 mock 行细分「替身契约」与「实现细节代理」）、`9b2bb9b`（2026-09-20，补「写在哪」三条）。
  - `docs/dev/testing.md:90-101`（新增用例前先读判定表；新对话框并入统一冒烟用例；布局/几何/像素一律不写断言）、`:86-88`（README 硬编码测试总数那套机制已移除的理由）。
  - `CLAUDE.md:59-62`（唯一例外：断言「渲染存在性」允许，先例是 `tests/test_qml_dialogs.py` 扫帧缓冲 `qAlpha == 0`；实测坐标 `tests/test_qml_dialogs.py:2040`, `:2057`）。
  - `CLAUDE.md:72-75`（三种结构重复口径的失败记录）。
  - 瘦身与清理提交：`299a635`（2526 → 2281）、`902847f`、`6d8444a`。

## ADR-005 流程冻结：要新增钩子/CI/检查脚本，先删一个同等成本的

- **状态**：生效
- **背景**：2026-07-31 的 `8052e29`「文档联动机制」一次性加了三个 pre-commit 钩子并新增 `scripts/check_readme.py`（95 行）、`scripts/check_docs_stale.py`（64 行）、`scripts/check_docs_links.py`（99 行），配套 CI 步骤 +7 行、`.pre-commit-config.yaml` +36 行。它们在 commit 时改写 `docs/api/*.md`、强制同步 README 里的测试总数，制造「提交被拒 → 重新 add → 再提交」的反复摩擦。
- **决策**：不新增 pre-commit 钩子 / CI job / `scripts/check_*.py`；要加必须先删一个同等成本的。
- **理由**：个人维护仓库里，一个检查项的成本不只是运行时间，还有「每次提交被挡一次」的心智打断，而它防的失配往往几乎不发生。2026-09-17 的 `d0a8253` 一次性删掉 `scripts/check_readme.py`（101 行）、`scripts/check_docs_stale.py`（71 行）、`tests/test_check_readme.py`（77 行）、`scripts/test_background_hook.sh`（40 行），`.pre-commit-config.yaml` 净减 32 行，只留 `check-docs-links`（它防的是真实会发生的死链），删除理由写进了钩子旁注释。把规则做成「先删一个同等成本的」而不是「尽量克制」，是为了让它可核对：想加东西的人必须自己指出删哪个，讨论对象从态度变成了预算。同一逻辑后来用在 CI：`994833a`（2026-10-01）删掉永远失败的 Codecov 上传与无人消费的 `--cov`。
- **后果**：克制条款 5（`CLAUDE.md` 第 22 行）。注意 `scripts/check_docs_links.py` 是**既有**检查（不是新增），改文档后仍要跑。
- **证据**：
  - `git show --stat 8052e29`（2026-07-31，新增三个文档检查脚本与钩子）。
  - `git show --stat d0a8253`（2026-09-17，删除 `scripts/check_readme.py` 101 行、`scripts/check_docs_stale.py` 71 行、`tests/test_check_readme.py` 77 行、`scripts/test_background_hook.sh` 40 行；`.pre-commit-config.yaml` −32）。
  - `.pre-commit-config.yaml:33-47`：现存的本地钩子只有 `check-docs-links`，其上方注释写明原先 3 个钩子（gen-api-docs / check-readme / docs-stale-reminder）为何移除。
  - `docs/dev/testing.md:87-88`（`scripts/check_readme.py` 与提交钩子强制同步测试总数「该机制已移除」）、`:149-152`（钩子清单与「需要时手动跑 `python scripts/gen_api_docs.py`」）。
  - `.github/workflows/ci.yml:73-77`（Codecov 步骤与 `--cov` 已删及原因）。

## ADR-006 配色只有一个 token 源：`ui_qml.theme.registry`

- **状态**：生效
- **背景**：主题层原先在 Widgets 侧，带一整套 QSS 生成；QML 侧需要同一份颜色，迁移期还在旧路径下留过一层同名转发器。两套 UI 共用色板时，「同一份」很容易退化成「两份看起来一样的值」。
- **决策**：所有颜色从 `ui_qml.theme.registry` 导入（QML 侧也读这一份），禁止 hex/rgb/颜色名。
- **理由**：registry 的模块 docstring 记着这次搬迁的唯一动机：「本模块原先在 Widgets 主题层，因为 QML 侧要读同一份 token 才搬到 `ui_qml/`」。**「同一份」必须物理上是同一个模块**，否则换主题时必然有地方不同步 —— 而且写死的颜色不会崩、不会报错，只在一块 UI 上露出异色，评审时最难盯住。QML 侧不能套 QSS（它靠 `Theme` 绑定的属性重绘），所以 QSS 生成在 Widgets 外壳删除后成了死代码，随 `bf5b405` 一并删掉。防御手段选了静态扫描而不是人工评审：`test_qml_only_references_existing_theme_tokens` 逐个 QML 文件核对 `Theme.xxx` 是否真实存在（不存在的 token 会**静默**变 `undefined`，实测踩过一次把按钮宽度变成 0）。
- **后果**：铁律 配色（`CLAUDE.md` 第 96 行）；改配色读 [架构说明](/dev/architecture)（`CLAUDE.md` 第 177 行）。
- **证据**：
  - `ui_qml/theme/registry.py:1-15`（单一 token 源；QSS 生成随 Widgets 层删除；「QML 侧不套 QSS，它靠 `Theme` 绑定的属性重绘」）。
  - `tests/test_theme_registry.py:65-70`（注册表只允许 `fluent-dark` / `fluent-light` 一对，旧的 8 套配色已删除）。
  - `tests/test_qml_theme_bridge.py:194-221`（静态扫描全部 `.qml`）、`:24-26`（桥的颜色 token 必须与注册表 schema 完全一致）、`:224-237`（扫描器必须忽略注释，否则在注释里解释 `Theme.accentRed` 就会假红）。
  - `.claude/audit/ui-design-consistency.md:178`：全仓 `#[0-9a-f]{3,8}` 共 9 处命中**全在注释/文档示例里**，「没有一处真的写进 `color:`」。
  - 提交 `bf5b405`（2026-09-16，删 `ui_pyside6/` 时一并删掉 registry 里的 QSS）。

## ADR-007 术语只有一个来源：`services.terminology` + `terminology.json`

- **状态**：生效
- **背景**：技能名 / 蓝图活动 / UI 标签此前散落在公式与视图代码里。`b1b26c6` 建了术语基础设施（`data/terminology.json` 60 行 + `services/terminology.py` 93 行；提交时间为 2026-07-26 18:05 +0000）。但与之配套的一致性校验曾**长期空转**：它依赖 `reference.db` 的 `item.category_id`，该列全为 NULL 时两条检查会 skip，看起来全绿。
- **决策**：EVE 术语通过 `services.terminology` 获取；公式中的技能 key 必须先注册在 `data/terminology.json` 的 `skill_names`。术语来源优先级：SDE `reference.db` 的 `item` 表（CCP 官方翻译）> `data/terminology.json`。
- **理由**：术语错了不会崩，只会静默显示一个玩家不认识的名字 —— 这类缺陷类型检查查不出、评审也难逐条核对，只能靠「唯一来源 + 与 SDE 对账的测试」。而这条 ADR 里更值钱的是后半段：**「检查存在」和「检查生效」是两件事**。带 skip 分支的校验必须在依赖数据缺失时让人看见（而不是安静通过）；`d270fae`（2026-09-17）回填 `item.category_id` 才让校验真正跑起来，期间术语并未因此变坏，但「有护栏」的错觉一直在。
- **后果**：铁律 术语（`CLAUDE.md` 第 97-98 行）；EVE 术语来源优先级（`CLAUDE.md` 第 263-267 行）；查术语读 [术语表](/dev/glossary)。
- **证据**：
  - `tests/test_terminology_consistency.py:1-9`（4 条覆盖：技能名 vs SDE、技能 key vs `skill_names`、矿物名 vs `item_overrides`、公式不直接引用技能名）。
  - `tests/test_terminology_consistency.py:33-55`：「若某份 reference.db 还没跑过那一步（该列全为 NULL），依赖它的检查会 skip 而不是误报 —— 这正是 2026-09-17 之前本机的状态（那两条检查因此长期空转）。」
  - `git show --stat b1b26c6`（2026-07-26，新增 `data/terminology.json`、`services/terminology.py`）。
  - `git log --oneline -1 d270fae` → `fix(数据): 回填 item.category_id，恢复失效的术语一致性校验`。

## ADR-008 分层边界由测试护栏守，不靠评审

- **状态**：生效
- **背景**：反向依赖是「悄悄长出来」的 —— 每迁一个对话框、每接一个 worker 都可能多一条。原护栏文件守的是 `ui_qml` 不得 import Widgets 视图层；QML 迁移把 Widgets 视图层删掉之后，被守的目标消失了。
- **决策**：护栏改成**按层声明**：`domain` / `core` 不得 import `ui_qml`、`services`；`services` 不得 import `ui_qml`。
- **理由**：被守对象消失时，正确做法不是删掉护栏，而是把「挡未来反向依赖」的本意换一条边界继续守 —— 文件 docstring 明写了这次目标切换，并把原文件的判断留着当依据。另一处判断同样重要：**`domain → core` 是合法**的下向依赖（`domain/scoring.py`、`domain/market_depth.py` 用 `core.eve_formulas` / `core.constants` 里的常量），所以护栏只挡「低层依赖高层的行为」，不是禁止一切跨层 import；一刀切会把合法依赖一起判红，然后被人当成噪音绕过。这条护栏是 2026-09-17 `897786c`「恢复分层护栏」时补回来的 —— 说明它曾一度丢失过。
- **后果**：架构节的分层顺序（`CLAUDE.md` 第 84-85 行）；改分层/主题/异步前读 [架构说明](/dev/architecture)（`CLAUDE.md` 第 194 行）。
- **证据**：
  - `tests/test_layer_boundary.py:1-20`（原 `test_qml_import_boundary.py` 的 docstring 与这次目标切换）、`:29-41`（`_FORBIDDEN` 声明及 `domain → core` 为何合法的注释）、`:60-79`（断言与失败提示）。
  - `git show --stat 897786c` → 2026-09-17，新增 `tests/test_layer_boundary.py` 79 行。
  - `docs/dev/architecture.md:5-6`（职责单向依赖，上层依赖下层）。
  - 被删目标那一侧的旁证：`tests/test_layer_boundary.py:18-19`（「`ui_qml → Widgets 视图层` 那条已无意义（包不存在，真写了会当场 ImportError）」）。

## ADR-009 `ui_pyside6/` 整体删除，新代码只写 `ui_qml/`

- **状态**：生效
- **背景**：Fluent Design 迁移期两套 UI 并存 —— `ui_pyside6/`（Widgets 外壳 + 七个页面 + 对话框）与 `ui_qml/`，通过 `QQuickWidget` 渐进嵌入。到批次 7.5 时只剩工业页业务控制器链还在 Widgets。
- **决策**：`ui_pyside6/` 整个删除；仅剩的 Widgets 业务控制器搬进 `ui_qml/views/`；新代码写 `ui_qml/`；代码与文档都不得再引用 `ui_pyside6`（历史审计文档已标注为快照，只作溯源）。
- **理由**：并存期每一处共享件都要额外保证「不反向依赖」—— 2026-09-16 专门有一个提交 `300a5e2`「共享层搬出 `ui_pyside6` —— `ui_qml` 不再反向依赖」为此存在。删掉包之后，那条反向依赖不需要护栏了：真写了会当场 `ImportError`。留着死路径的代价恰好相反、而且是长期复利的：它们会被当成**现状**继续引用。清理审计的统计是 `ui_pyside6` 字面量在非 QML 部分 95 行 → 0 行，其中 14 处是「把已删除的包当现状引用（误导性最强）」——读完会让人去找不存在的文件。
- **后果**：架构节 `ui_pyside6` 禁令（`CLAUDE.md` 第 91-92 行）。残留控制器仍在 `ui_qml/views/`，改它们的入口见任务导航（`CLAUDE.md` 第 173 行）。
- **证据**：
  - 提交链：`300a5e2`（2026-09-16，共享层搬出）、`b7ee2b2`（批次 6.2，51 个模块收到 17 个）、`9d7b37b`（批次 7.4，退役回退脚手架）、`bf5b405`（2026-09-16，`refactor(QML 迁移): 删掉整个 ui_pyside6/ + registry 里的 QSS（批次 7.5，迁移收尾）`）。
  - `docs/dev/architecture.md:163-165`（迁移与最终删除的经过；`views/` 是残留的 Widgets 业务控制器）。
  - `.claude/audit/comment-cleanup.md:19`（`ui_pyside6` 字面量 95 行 → 0）、`:57-77`（14 处「当现状引用」清单）、`:60`（「`CLAUDE.md:91-92` 明令禁止再引用该路径」）、`:188`（`docs/**` 与 `CHANGELOG.md` 里的剩余 8 处是历史快照，按禁令保留）。
  - `.claude/audit/ui-design-consistency.md:213-214`（B11 的注释清理落在 21 个 QML 文件里）、`:228`（B11 明细行；改后 `*.qml` 命中 0）。

## ADR-010 4 库分离：reference / market / user / blueprint

- **状态**：生效
- **背景**：原先只有一个库 `items.db`（`core/paths.py` 至今保留 `database_path()`，注释写着「旧单库文件路径（迁移后保持兼容）」）。2026-06-18 的 `8b9f6a0`「数据库拆分」一次性拆出 reference / market / user 三库，并新增 `services/database_manager.py`（139 行）与一次性迁移脚本 `scripts/migrate_split_db.py`（272 行）；2026-06-19 的 `9e41094` 补上 `blueprint.db` 成为四库。
- **决策**：四库独立文件，管理走 `services/database_manager.py`，跨库查询用 SQLite `ATTACH DATABASE` + 别名（`ref` / `mkt` / `bp` / `usr`）。
- **理由**：三类数据的**生命周期不同** —— reference / blueprint 随 SDE 重导、market 随行情刷新、user 是用户资产且不可重建。同库时，「重新导入 SDE」这件事必须动到装有用户数据的那个文件，于是每次导入都变成高风险操作，备份也只能整体做。拆开之后，重导与保用户数据互不影响，备份/迁移策略可以按库分级 —— ADR-003 里 `user.db` 的阻断式保护与 `ref/mkt/bp` 的「直接重导」正是建立在这条分离之上。代价（跨库查询要写别名、连接要 ATTACH）用 `services/database_manager.py` 一处收口。
- **后果**：架构节「4 库独立」（`CLAUDE.md` 第 87 行）；改 `market.db` / 导入器 / 字段读 [数据格式](/dev/data)（`CLAUDE.md` 第 170、172 行）；跨库查询、加列读 [架构说明](/dev/architecture) 的数据库管理节。
- **证据**：
  - `git show --stat 8b9f6a0`（2026-06-18）：新增 `services/database_manager.py` 139 行、`scripts/migrate_split_db.py` 272 行、`documents/database_split_plan.md` 220 行，`core/paths.py` 改 31 行，并生成 `database/{reference,market,user}.db`。
  - `git log -S"blueprint_db_path" -- core/paths.py` 只命中一个提交：`9e41094`（2026-06-19）。
  - `core/paths.py:57-84`（四个库路径函数）、`:62-64`（旧单库 `items.db` 路径「迁移后保持兼容」）、`:134-140`（`REF_DB_PATH` / `MKT_DB_PATH` / `USR_DB_PATH` / `BP_DB_PATH`）。
  - `docs/dev/architecture.md:199-217`（`ATTACH DATABASE` 机制、`alias: ref / mkt / bp / usr`、跨库 JOIN 示例）。

## ADR-011 QML 组件绑定 `Theme` 单例，不用 `add_theme_listener`

- **状态**：生效
- **背景**：Widgets 时代的主题切换是「注册回调 + 手动重绘」（`add_theme_listener` + `_on_theme_changed`）。迁到 QML 后如果沿用回调，就会出现一类反复出现的缺陷：**窗口已销毁、回调仍在跑**。
- **决策**：新 UI 组件用 QML 属性绑定 `Theme` 单例（QML 侧靠属性绑定自动重绘）；仍在 Widgets 里的组件才用 `add_theme_listener` + `_on_theme_changed`。
- **理由**：属性绑定把「何时重绘」交给 QML 引擎，不需要 Python 侧持有窗口引用来回调。回调式的问题不在于多写几行，而在于**回调注册的生命周期与被绑定对象的生命周期解耦**：谁负责在窗口析构时注销，是每个调用点各自要记得的事，而记不住不会有编译错误。这个缺陷在本仓反复出现过三次不同面目：`b669667`（2026-07-31，主题监听器改弱引用）、`2995d5e`（2026-08-17，多主题系统审计）、`0c58233`（2026-09-16，已销毁窗口的主题监听器自收敛）。监听器本体保留（并改成弱引用）不是遗留，而是因为 Widgets 残留件与测试仍在用。
- **后果**：架构节「新 UI 组件绑定 `Theme` 单例」（`CLAUDE.md` 第 89-90 行）；残留 Widgets 组件才用监听器。
- **证据**：
  - `ui_qml/theme/registry.py:4-5`（QML 的 `Theme` 单例与 `theme.XXX` 都读这里）、`:14`（QML 侧靠属性绑定重绘）、`:396`（`add_theme_listener` 仍在，供残留调用方）。
  - `tests/test_theme_listeners.py:50-58`（工业页已整页 QML：主题由 QML 绑定 `Theme` 单例跟随）、`:71-87`（绑定方法监听器必须是弱引用，否则泄漏）、`:118-140`（显式 remove 与 lambda 兼容）。
  - `tests/test_qml_theme_bridge.py:135`（`test_singleton_is_stable`）、`:194-221`（QML token 静态扫描）。
  - 提交 `b669667`、`2995d5e`、`0c58233`。

## ADR-012 测试分档互斥：`validate` 与 `ui-retest`，以及「假绿」这条踩坑

- **状态**：生效
- **背景**：UI 测试很慢（`ui` 段实测 221s~445s），分档是为了开发循环里只跑相关档。2026-07-31 的 `b6a10bf` 引入分档测试脚本，2026-08-18 的 `6337c9c`「测试分层与瘦身」收敛成 `fast` / `validate` / `ui-retest` 三档。但 `validate` 是 `-m "not ui"` —— 带 `pytestmark = pytest.mark.ui` 的文件**根本不会被收集**，改了它们再跑 `validate` 会得到假绿。
- **决策**：分档**事前决定、不许逐级升级**；`validate` 与 `ui-retest` 互斥、并集恒等于 `full`；改了带 `ui` 标记的测试文件（或任何 QML/UI 文件）走 `ui-retest`，或按例外直接点名跑那个文件；一次任务最多跑一次（跨层改动 `target` + `ui-retest` 各一次，合计仍算一次）；`full` 的时机由用户定。
- **理由**：「假绿」是这套规则里最贵的一种错 —— 它比红更糟，因为红会逼你去查，绿让你以为查过了；而这里绿的原因只是文件没被收集。两个实测现场支撑了整套防范：
  1. **CI 整档的代价**（2026-10-01，run 36824867391）：带 `-m ui` 的用例在无显示 runner 上大批 fixture ERROR，随后在 Qt 定时器回调里 `Fatal Python error: Segmentation fault` —— **整轮在 62% 崩掉、连汇总都打不出来（exit 139）**，后面 38% 根本没跑。所以 CI 只跑非 UI 档，且 `-s`（不捕获 stdout/stderr）**必需**：管道写满会让 QML 线程与主线程在 `QQuickView.setSource()` 的同步等待上互锁（实测 240s 不返回 vs 带 `-s` 21.6s）。
  2. **本机 offscreen 的代价**：Windows + `QT_QPA_PLATFORM=offscreen` 下 `PageHost.setSource()` 卡在 Qt 的 QML 线程永不返回（无 Python 栈）。2026-09-27 把整个 `ui-retest` 档拖成无摘要，2026-10-05 又踩一次（同一文件真平台 2.36s 通过 / offscreen 卡死）。**这条规矩原先只是 `docs/dev/testing.md` 里的散文，没人看**，于是做成启动即拒绝的硬门 —— 与其让人在「随机卡死、没有栈」上白烧半小时，不如启动就拒绝并说清原因。
- **后果**：`CLAUDE.md` 测试边界节（第 102-158 行）：选档表（第 110-116 行）、假绿警示（第 118-120 行）、跨层预算（第 124-125 行）、三条硬规则（第 143-147 行）。跑测统一走 `scripts/run_tests.sh`，见 [测试与规范](/dev/testing)。
- **证据**：
  - `docs/dev/testing.md:69-70`（`validate` 与 `ui-retest` 互斥、并集恒等于 `full`，「没有『两档都不跑』的漏网空间」）、`:90-101`、`:118-152`（质量工具与提交前检查清单）。
  - `CLAUDE.md:118-120`（假绿：文件根本没被收集）。
  - `.github/workflows/ci.yml:48-65`（为何只跑非 UI 档 + `-s` 必需 + 崩塌现场与 exit 139）、`:66-67`（`QT_QPA_PLATFORM: offscreen` 只给非 UI 档里少数碰 Qt 的用例）。
  - `tests/conftest.py:126-175`（offscreen 硬门：现场栈、`EVE_ALLOW_OFFSCREEN_TESTS=1` 逃生开关、「这条规矩原先只写在 `docs/dev/testing.md` 的散文里 —— 没人看，所以这里做成硬门」）、`:226-227`（`pytest_configure` 里调用守卫）。
  - `tests/test_test_env_guards.py:1-8`（判定表：只有 Windows + offscreen 才拒，Linux CI 与真平台放行）、`:17-30`（7 条参数化）。
  - 已批准计划的实操样本：`.claude/plans/2026-09-25-六项改动.md:108-119`（主档 `ui-retest` 一次 + 点名两个非-`ui` 文件，并写明点名文件「不被 `ui-retest` 收集」）。
  - 提交：`b6a10bf`（2026-07-31 分档测试脚本）、`6337c9c`（2026-08-18 三档）、`19393f1`（2026-10-01，11 个加载 Qt 的测试文件补 `ui` 标记）、`5d8667a`（2026-10-05，整档 `ui` 从「跑不完/末了崩」到干净退出）。

## ADR-013 `docs/api/**` 由脚本生成，不手改

- **状态**：生效
- **背景**：函数级 API 文档若手写，必然与签名漂移。2026-07-31 的 `b84f62c`（审计报告与待办入档、准备 v0.2.0 发布）引入 `scripts/gen_api_docs.py`；同日晚些的 `8052e29`（文档联动机制）把它挂进 pre-commit 与 CI。
- **决策**：`docs/api/**` 由 `scripts/gen_api_docs.py` 生成，不手改；CI（`docs.yml`）在构建文档站前重跑它，保证与代码同源；本地需要时手动跑；`--check` 只检查是否过期。
- **理由**：生成物的价值全部来自「必然与代码同步」这一条性质，一旦允许手改，这条性质与对它的信任同时消失（改生成页比改代码方便，于是下一个人就改了）。但把它做成 commit 时强制钩子又是另一种错误：它会改写上百页 `docs/api/*.md`，且每次改代码都会让无关页面因「定义行」漂移而变更 —— 清理审计专门记录了这个**系统性易腐生成器**，并因涉及克制条款 5 而**没有擅自改**，交给人决策。最终取舍是：**钩子去掉（ADR-005），「生成物不手改」留下**，更新方式变成「谁改代码谁手动重跑」。这条已被真实故障验证过必要性：审计修过一个生成器缺陷 —— docstring 里的 `{ "items": bool, ... }` 被 markdown-it-attrs 当成 HTML 属性，导致 `docs/api/services/init_check.md` 构建即崩，修法是生成器把 `{` 转义成 `&#123;`。
- **后果**：文档索引 `docs/api/**` 行标注「**生成**，不要手改」（`CLAUDE.md` 第 209 行）；任务导航多处把 `docs/api/…` 列为相关文档（`CLAUDE.md` 第 166 行等）。
- **证据**：
  - `scripts/gen_api_docs.py:1-22`（`ast` 遍历 → `docs/api/<模块路径>.md`；「CI（docs.yml）在构建文档站前运行本脚本重新生成 API 页，保证与代码同源」）、`:18-21`（生成/`--check` 用法）、`:38-44`（扫描目录与 `OUT_DIR`）。
  - `docs/dev/testing.md:149-152`（原先的 gen-api-docs 钩子已移除，「需要时手动跑 `python scripts/gen_api_docs.py`」）。
  - `docs/dev/audit-report.md:23`（花括号转义缺陷与重新生成 49 页）、`:37`（`gen_api_docs.py --check` ✅ 文档与代码同步）。
  - `.claude/audit/comment-cleanup.md:51-53`（重跑生成器的连带影响：保留 27 页、回退 12 页、删 1 页新页）、`:186`（「系统性的易腐定位生成器」：11 个无关页面仅因别人提交造成的行号漂移而变；涉及克制条款 5，未擅自改）。
  - 提交：`b84f62c`（2026-07-31，`git log --diff-filter=A -- scripts/gen_api_docs.py` 的唯一命中）、`8052e29`（同日挂钩子）、`4a192b2`（`chore(文档): 对齐 gen_api_docs 漏生成/漏更新的 6 页`）、`50c9b84`（`docs(api): 重新生成 docs/api —— 清掉长期漂移`）。

## ADR-014 `CHANGELOG.md` 是唯一更新日志源，由 python-semantic-release 维护

- **状态**：生效
- **背景**：版本号原本要靠手工同步多处（代码里的版本源、更新日志、tag）。2026-07-31 做过一轮「语义化版本管理 + 文档站」的专项工作与审计。
- **决策**：`CHANGELOG.md` 是**唯一**更新日志源；发版时由 python-semantic-release 自动在版本列表标记处插入新版本段，不手动维护；一致性由 `scripts/check_version.py` 在 CI 里校验：`core/version.py.__version__` == CHANGELOG 最新版本段 == `pyproject.toml [project].version` == git tag（发版态）。
- **理由**：同一个事实写在多处，就一定有某处先漂，而且漂了不会报错。这里有一次**具体的静默失效**：`version_toml` 曾写成 `pyproject.toml:version`，而 PSR 的 `TomlVersionDeclaration.replace()` 在 key 不存在时**直接返回原文**（其源码里标着 `# TODO: v11 raise KeyError`），于是静默跳过 —— `pyproject.toml` 与 `uv.lock` 长期停在 0.24.2，而 `core/version.py` 与 CHANGELOG 已到 0.25.0，期间没有任何检查发现。修法有两条、缺一不可：写对点号路径（`project.version`），**并把 `pyproject.toml` 纳入 `check_version.py` 的校验范围** —— 只修配置而不扩校验，下次换个字段又会静默漂移。`uv.lock` 则明确**不**纳入硬校验：它只是记录（`[tool.uv] package = false`），滞后不影响安装结果，为它增加发布步骤不值得。
- **后果**：文档索引 `docs/dev/versioning.md` 行（`CLAUDE.md` 第 204 行）；发版/CHANGELOG/semantic-release 一律以 [版本管理](/dev/versioning) 为准。
- **证据**：
  - `CHANGELOG.md:5-7`：「本文件是唯一更新日志源：发版时由 python-semantic-release 自动在版本列表标记处插入新版本段，无需手动维护。」及 `<!-- version list -->` 标记。
  - `pyproject.toml:137-144`（`[tool.semantic_release.changelog]`：`mode = "update"`、`insertion_flag = "<!-- version list -->"`、`changelog_file = "CHANGELOG.md"`）、`:109-112`（`version_toml` 必须写点号路径的实测教训与日期）、`:114-135`（commit parser 与 bump 规则）、`:118-119`（`version_variables` / `version_toml`）。
  - `docs/dev/versioning.md:36-49`（四源一致性与静默失效复盘）、`:51-66`（`check_version.py` 校验口径与 `uv.lock` 为何不纳入）、`:68-99`（发版流程与回退路径）。
  - `docs/dev/audit-report.md:11`（审计范围含 `pyproject.toml`（python-semantic-release 配置）与 `CHANGELOG.md`（重构为 Keep-a-Changelog））。
  - 提交：`8052e29`、`d57935e`（2026-09-26 `fix: 版本一致性静默失效 + 单实例探活会杀进程 + …`）、`c479ffc`（回退发版路径改用 CHANGELOG 抽出的说明当地 Release notes，因为 `action-gh-release` 无 body 时会把提交正文当说明 —— 2026-10-06 v0.26.0 实测）。

---

## 无法溯源的决策

以下条目只在本页做**如实登记**，不写成 ADR —— 因为拿不出可核对的因果链，写了就是编历史。每条的检索方式一并列出，供后来者接着查（不要重复我已经做过的那几次）。

### 1. 克制条款 6「防御上限」

- 现状条款：`CLAUDE.md:23-24`（不对同进程同仓库的模块做 ImportError 防御；不捕获不可能失败的操作；热路径不重复校验已在加载点校验过的配置；新增 `except Exception` 时说明它吞的是哪类异常）。
- 检索过：
  - `git log -S"防御上限" -- CLAUDE.md` → 只命中 `d0a8253`（2026-09-17，与其余五条一起写入）。
  - `git log -S"ImportError" -- CLAUDE.md AGENTS.md` → 同样只命中 `d0a8253`。
  - `git log --all -S"except Exception"` → 命中若干业务提交（如 `397cffb`、`ea4b943`），但没有一条是以「防御过度」为动机的重构。
  - `git log --all -i --grep="过度设计|不必要|防御"` → 命中 4 条（`d0a8253` 与 `d4fbf98`、`33269e7`、`2de1ec5`）；除 `d0a8253`（条款本身）外，后三条与防御式编程无关。
- 结论：**证据：仅见于 `CLAUDE.md`（第 23-24 行），历史出处待确认。** 该条款是在 `d0a8253` 一次性写入的，之前没有对应的删除/重构事件可引。
- 若要补上出处，建议方向：查 `d0a8253` 之前的会话记录或 `.claude/` 下的审计文件（`.claude/` 已在 `.gitignore`，不入仓库，检索不到）。

### 2. 架构节「UI 异步用 QThread + Signal」

- 现状条款：`CLAUDE.md:88`（以及 [架构说明](/dev/architecture) 的「异步架构」节）。
- 检索过：`git log --all -i --grep="QThread"` → 命中的都是测试/生命周期修复（`851c554` 退出期线程被连带析构、`5d8667a` 跑测环境收尾等），不是「为什么选 QThread 而不是 asyncio / 线程池」的选型提交；`git log -S"QThread" -- CLAUDE.md` 最早只能追到 `447675e`（2026-07-27 的文档重组），再往前是文档整理而非决策。
- 结论：**证据：仅见于 `CLAUDE.md`（第 88 行）与 `docs/dev/architecture.md:225-235`，历史出处待确认。** 代码里这条确实在生效（worker 层与测试都在跑），但「当初的取舍理由」没有可信出处，不猜。

### 3. 抽象层闸门里「至少 2 个现存调用方」这个阈值

- ADR-001 的证据能证明「少一层的抽象会被删掉」，但**证明不了为什么是 2**：阈值只出现在 `d0a8253` 写进 `CLAUDE.md` 的条款正文里。
- 检索过：`git log --all -S"2 个现存调用方"` → 只命中 `d0a8253`（条款写入）与 `d4e0025`（`untracked files on main` 的工作区快照提交），没有阈值推导记录；`git log --all -S"抽象层"` → 除上述两条外，其余全是 2026-06 末的文档整理/清理提交（`5b520ce`、`8e68598`、`2dcb29b`、`703a5be`、`270ddf8`、`d913575`），没有一条在讨论这个阈值。
- 结论：**证据：仅见于 `CLAUDE.md`（第 12 行），阈值推导过程待确认。** 实践中这条阈值可用（1 个调用方 = 转发），但不要在本页引用成「有先例支持 2 这个数」。

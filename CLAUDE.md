# EVE-Online-Industrial-Assistant

PySide6(QML) + SQLite 构建的 EVE Online 工业制造助手桌面应用。
Python 3.14+ / PySide6 6.11+ / ruff 格式化 + linting；依赖用 `~=` 固定版本，uv 管理（`uv sync --dev`）。
一个人维护，仓库公开（Apache 2.0）。

> **克制条款优先** —— 与下文任一条冲突时，以本节为准。优先级：**能跑 > 好改 > 优雅**。

## 克制条款

1. **抽象层闸门**：新建 `services/*.py` 模块 / repository / facade / Protocol / 事件总线 / 缓存层 / 重试框架前，
   必须给出**至少 2 个现存调用方的 `文件:行号`**；拿不出就内联在使用处。「以后可能会用」「为了解耦」
   「更符合分层」都不是理由。缺陷修复不受此限（就地改，不要顺手重构）。
2. **组合根冻结**：`bootstrap/container.py` 不再新增服务属性；`core/container.py` 的转发保留、不推进迁移。
   新依赖写构造函数默认值，不走容器。
3. **迁移节制**：只有 `user.db` 需要版本化迁移；`reference/market/blueprint` 是可重建缓存，表结构变了直接重导。
   加列只改 `DB_SCHEMA_VERSIONS` + `_MIGRATIONS` 两处，用 `_add_columns`，不从零手写 `sqlite3.connect` 三段式。
4. **测试预算**：单次任务新增测试 ≤ 被测代码行数 × 0.5；能 `parametrize` 的不写独立用例；
   **纯布局/几何/像素/样式断言不写测试**（用 `scripts/shell_snapshot.py` 截图核对）；
   修 bug 至少补 1 条最小回归，**不为没发生过的场景写预防性用例**。
   **写不写的触发条件见下方「测试判定表」—— 不是每次改动都要补测试。**
5. **流程冻结**：不新增 pre-commit 钩子 / CI job / `scripts/check_*.py`；要加必须先删一个同等成本的。
6. **防御上限**：不对同进程同仓库的模块做 ImportError 防御；不捕获不可能失败的操作；
   热路径不重复校验已在加载点校验过的配置。新增 `except Exception` 时说明它吞的是哪类异常。

### 测试判定表

克制条款第 4 条的触发条件。**总则：测试是给「会坏」的逻辑买的保险 —— 不含分支/数值的改动没有可坏的东西，不写。**

**必须写**

| 改动类型 | 要求 |
|---|---|
| 纯计算 / 公式（`domain/`、`core/`） | 写。有分支和数值，算错看不出来 |
| 修 bug | 写 **1 条复现该 bug 的最小回归**。写不出复现 → 说明没找到根因 |
| 数据解析 / 导入边界（脏数据、缺列、编码） | 写。真实数据不可预测，边界就是 bug 源 |
| schema 迁移（加列 / 回填） | 写。跑一半会毁用户数据且不可逆 |
| 跨线程异步编排（QThread + Signal） | 写 **1 条端到端**，不逐信号断言 |

**不写**

| 改动类型 | 替代做法 |
|---|---|
| 重构（行为不变） | 靠已有用例兜底。新用例只证明「重构后的代码还是我写的这样」 |
| 新服务 / 转发 / 委托层 | 没有可坏逻辑 |
| 改文档 / 注释 / 重命名 / 格式化 / 删死代码 | 无可坏逻辑 |
| 纯 UI 布局 / 样式 / 尺寸 / 配色 / 字体 | `scripts/shell_snapshot.py` 出图核对 |
| 新增 QML 对话框 | 往 `tests/test_qml_dialogs.py` 参数化列表加一行，**不建独立用例** |

**禁止写**

| 断言对象 | 理由 |
|---|---|
| 外观值（颜色 / 字号 / 字体族 / 对齐 / 几何） | 布局一改就红，与业务无关 |
| 标准库 / 框架行为（如 `isinstance(conn, sqlite3.Connection)`） | 测的不是自己的代码 |
| 「不为 None」「能调用不报错」 | 零信息 |
| mock 调用序列 | 分两种，别一刀切。**替身交互契约 → 允许**：mock 是 repo / service / QML 页的替身时，「传了什么参数」就是可观察契约（`repo.update.assert_called_once_with(7, notes="改后备注")` 断言的是备注真写进去了）；**实现细节代理 → 禁止**：断言 `signal.emit` 自身被调用、或内部私有方法被调用，而非下游效果。**负向断言另算**：`assert_not_called` 守的是「不该发生」，是业务规则，保留 |

**唯一例外 —— 断言「渲染存在性」允许**

「什么都没画出来」这类缺陷静态结构看不见。先例：`tests/test_qml_dialogs.py` 扫帧缓冲 `qAlpha == 0` 找透明空洞。
分界：**断言外观值 → 禁止；断言「有没有渲染」→ 允许**，且用例 docstring 须写明它捕获的缺陷。

体检：`scripts/test_audit.py`（手动跑，不挂钩子）报出上述禁止项，只报告不改动。

## 代码规则

- ❌ 裸 `except: pass`（必须 `log.exception(...)` 或重抛）｜SQL F-string 拼接｜硬编码颜色/常量/密钥
- ✅ 所有 SQL 参数化｜异步用 `async with`｜新代码加类型注解｜`yaml.safe_load()`、不硬编码密钥

## 架构

`bootstrap/`（组合根）→ `core/`（工具/常量）→ `domain/`（纯函数，无 DB/Qt/缓存）→
`services/`（业务/DB/repositories）→ `ui_qml/`（QML UI，**新代码写这里**）

- 4 库独立：`reference.db` / `market.db` / `user.db` / `blueprint.db`，管理走 `services/database_manager.py`
- UI 异步用 QThread + Signal
- 新 UI 组件：**QML 组件绑定 `Theme` 单例**（不要 `add_theme_listener` —— QML 侧靠属性绑定自动重绘）；
  仍在 Widgets 里的组件才用 `add_theme_listener` + `_on_theme_changed`
- ⚠️ `ui_pyside6/` 已在批次 7.5 整个删除；仅剩的 Widgets 业务控制器搬进了 `ui_qml/views/`。
  **不要在代码或文档里再引用 `ui_pyside6`**（历史审计文档已标注为快照）

## 铁律

- 🎨 **配色**：所有颜色从 `ui_qml.theme.registry` 导入（**QML 侧也读这一份**），禁止 hex/rgb/颜色名
- 📖 **术语**：EVE 术语（技能名/蓝图活动/UI 标签）通过 `services.terminology` 获取，
  技能 key 需在 `data/terminology.json` 注册
- 🗄️ **Schema**：表结构变更必须在 `services/schema_migrations.py` 注册（范围见克制条款第 3 条），
  不得在业务代码中写 ALTER TABLE

## 测试边界（硬性）

**先回答「要不要写」，再回答「跑哪一档」。** 要不要写看上文「测试判定表」；本节只管怎么跑。

**一次任务跑一次测试。** 测试是验证手段，不是进度展示 —— 进度用文字汇报，不要靠反复跑测试来体现"在工作"。

### 选档：事前决定，不许逐级升级

| 改了什么 | 跑什么 | 明确不跑 |
|---|---|---|
| 删死代码 / 改注释 / 改文档 / 格式化 | `target`（纯文档/配置变更会自动跳过，秒退） | 其余全部 |
| 单文件纯计算（`domain/`、`core/`） | `fast` | 其余全部 |
| services 业务 / DB 查询 / 导入器 | `target` | validate / full |
| QML / UI，**或任何带 `ui` 标记的测试文件** | `shell_snapshot.py` 出图 + `ui-retest` 一次 | validate / full |
| schema 迁移 | `validate` 一次 | full |

> ⚠️ **`ui` 标记的文件被 `validate` 跳过** —— `validate` 是 `-m "not ui"`。改了这类测试文件（`test_qml_*`、
> 表格模型等，文件头有 `pytestmark = pytest.mark.ui`）之后跑 `validate` 会得到**假绿**：文件根本没被收集。
> 要么走 `ui-retest`，要么按下面的例外直接跑那个文件。这一条是踩过的坑。

**选定的那一档跑绿即为通过。不要为了"更保险"往上加档。**

```bash
scripts/run_tests.sh target     # git 变更相关，开发循环默认
scripts/run_tests.sh fast       # 纯计算/轻服务白名单
scripts/run_tests.sh ui-retest  # 只跑 Qt 界面 + 真 QThread（实测 220s+），改 UI 时优先
scripts/run_tests.sh full       # 全量（实测 5~8 分钟，看机器负载），**时机由用户定**
```

> 档位耗时都是**实测值**，且负载敏感（ui 段实测 221s ~ 445s）。别按旧文档里
> 「~40s / ~1.5min」那类数字做计划 —— 那组数字长期未核对，已删。

`validate`（`-m "not ui"`，即 `scripts/run_tests.sh` 无参数）与 `ui-retest`（`-m ui`）互斥，
二者并集覆盖全部用例、恒等于 `full`。

### 三条硬规则

1. **改完再跑，不是每改一个文件就跑。** 一次任务里测试最多跑一次（红了重跑失败项不算）。
2. **红了只重跑失败项**：`pytest --lf`，或直接给 node id（`tests/test_x.py::test_y`）。**不重跑整档。**
3. **`full` 的时机由用户定**，不主动提议、不主动执行。

### 允许的例外

正在写的那一个测试文件可以反复跑（`pytest tests/test_xxx.py -q`，通常 <1s）——那是 TDD 迭代，
不算"跑测试"。但它必须是**本任务的产物**，不是既有测试。

### 不要做的

❌ target → fast → validate → full 逐级爬｜❌ 改完立刻跑、跑完又改、再跑一遍全量｜
❌ 为"确认一下没坏"重复跑已经绿过的档｜❌ 为了让进度播报"有东西可写"而去跑测试｜
❌ 为纯样式/布局改动补测试（判定表列在禁止档，写了也是负债）

## 任务导航（改代码前先读）

收到任务先定位所属链路，读对应文档与入口文件，不要通读全库。

| 任务类型 | 入口文件（改这） | 相关文档（先读这） |
|---|---|---|
| 改制造/贸易/精炼公式 | `domain/formulas.py`、`domain/scoring.py`（纯算法）、`core/eve_formulas.py` | `docs/dev/flows.md`；`docs/api/…` |
| 改评分编排/取价 | `services/scoring_facade.py`（编排）、`services/scoring_service.py`（薄委托入口） | `docs/dev/flows.md`（评分节） |
| 改统一定价/市场查询 | `services/pricing_service.py`、`services/repositories/market_repository.py` | `docs/dev/data.md`（market.db 表） |
| 改 BOM 展开 | `services/bom_expander.py`、`domain/bom.py` | `docs/dev/flows.md`（BOM 节） |
| 改生产计划 | `services/plan_service.py` + `services/repositories/plan_repository.py` + `plan_*.py` | `docs/dev/flows.md`（计划节） |
| 改数据库 Schema | `services/schema_migrations.py`（迁移函数注册） | `docs/dev/schema-migration.md`；`docs/dev/data.md` |
| 改数据导入（SDE/ESI） | `services/importers/get*.py`、`services/init_service.py` | `docs/dev/flows.md`（初始化节） |
| 改 UI 页面/异步任务 | QML 页面 `ui_qml/qml/pages/…` + 桥 `ui_qml/bridge/…`；模型/线程 `ui_qml/models/…`、`ui_qml/workers/…`；残留 Widgets 控制器 `ui_qml/views/…` | `docs/dev/architecture.md`；`docs/dev/api-reference.md` |
| 改外壳（标题栏/导航/状态栏） | `ui_qml/shell_window.py` + `ui_qml/qml/shell/…` | `docs/dev/ui-blueprint.md`（区域命名） |
| 看界面实际效果 | `scripts/shell_snapshot.py`（QML 外壳，`--real` 出真窗口图） | 见下「界面感知」 |
| 查/改 EVE 术语 | `data/terminology.json` + `services/terminology.py` | `docs/dev/glossary.md` |
| 改 UI 配色 | `ui_qml/theme/registry.py` | `docs/dev/architecture.md`（主题） |

## 界面感知（改 UI 前必读）

**区域命名以 `docs/dev/ui-blueprint.md` 为准**（窗口级 7 区 + 页面级 5 区，含标注图）。
与用户沟通界面时用该文档的区域名，禁止说「上面那个栏」「左边那块」。

只读代码理解不了界面。改 UI 前先跑一次快照，用截图确认现状，改完再跑一次对比：

```bash
python scripts/shell_snapshot.py                 # QML 外壳（离屏，验结构/配色）
python scripts/shell_snapshot.py --real          # QML 外壳（真窗口，验字形/毛玻璃；数据目录自动隔离）
python scripts/shell_snapshot.py --page industry # 切到某页再拍
```

**离屏下 `QFontDatabase` 是 0 个字体**（文字全成方框），字形必须用 `--real` 看。
产出 `<page>.png`（整窗截图）与 `<page>.tree.md`（控件树：类名/objectName/文本/几何/可见性），
可直接用 Read 工具查看。默认走 offscreen 平台——不弹窗、不抢焦点、可反复执行。

## 计划自检（ExitPlanMode 前）

四问：① 架构符合性（是否符合分层与铁律）② 可复用性（是否已搜过 `core/ domain/ services/ ui_qml/`
确认无现成实现）③ 隐患 ④ 有无更简替代。**第 ③④ 问允许直接写「无」**，不必为凑答案发明风险或备选方案。
小改动（≤2 文件、不碰架构）一句话带过。

`plan-auditor` 子代理**仅在涉及 schema 迁移 / 删改用户数据 / 依赖与构建配置变更时**调用，
传入计划文件路径与相关文档路径，并要求它同时回答「**计划是否可以更小**」。

## 常用命令

```bash
uv sync --dev                     # 安装依赖（首次 / 依赖变更后）
.venv/Scripts/python.exe dev.py   # 热重载开发
.venv/Scripts/python.exe Main.py  # 生产启动
uv run ruff check . --fix         # 自动修复风格
uv run mypy .                     # 类型检查

.venv/Scripts/python.exe scripts/test_audit.py      # 测试判定表体检（只报告，不改动）
.venv/Scripts/python.exe scripts/shell_snapshot.py  # 界面快照，详见「界面感知」
```

**别用裸 `python`** —— 本机 PATH 上的可能是不带依赖的系统解释器，失败还会被管道吞掉
（`scripts/run_tests.sh` 开头那十行就是在讲这件事）。

## EVE 术语来源（按优先级）

1. **SDE 数据库** `database/reference.db` → `item` 表（CCP 官方翻译）
   - `SELECT zh_name FROM item WHERE category_id=16 AND en_name='Reprocessing'`
2. **`data/terminology.json`** — 项目术语中心，`services/terminology.py` 统一查询
3. 公式中的技能 key → 先在 `terminology.json` 的 `skill_names` 注册

# 测试与规范

## 测试框架

| 工具 | 版本 | 用途 |
|------|------|------|
| pytest | ~9.0 | 测试运行器 |
| pytest-qt | ~4.5 | Qt UI 测试 |
| pytest-cov | ~5.0 | 覆盖率统计 |
| pytest-asyncio | ~1.3 | 异步测试支持 |

## 运行测试

**统一走 `scripts/run_tests.sh`**（默认 `validate`）。它自己解析 `.venv` 里的解释器，
不依赖你先把虚拟环境激活：

```bash
scripts/run_tests.sh            # validate：全部业务/DB/计算，跳过 Qt（~45s）
scripts/run_tests.sh fast       # 纯计算/轻服务白名单（~4s）
scripts/run_tests.sh ui-retest  # 只有 Qt 界面 + 真 QThread（~40s），改动涉及 UI 时优先
scripts/run_tests.sh target     # 只跑 git 变更文件相关（~5s）
scripts/run_tests.sh full       # validate + ui-retest 两阶段（~1.5min），仅提交前
```

开发循环用 `fast` / `target`，日常回归用 `validate`，`full` 只在提交前。

想直接调 pytest 也可以（**必须用虚拟环境里的解释器**，裸 `python` 可能是没装 pytest 的
系统解释器，失败会被管道吞掉）：

```bash
.venv/Scripts/python.exe -m pytest tests/ -q -m "not ui"
.venv/Scripts/python.exe -m pytest tests/test_scoring_service.py -v
.venv/Scripts/python.exe -m pytest tests/ -k "test_calc" -v
.venv/Scripts/python.exe -m pytest --lf          # 只重跑上次失败的
```

## 测试分档与标记

档位由 `pyproject.toml` 的 `markers` 驱动，**只有两个**：

| 标记 | 含义 | 归入哪一档 |
|------|------|-----------|
| `fast` | 纯计算 / 轻服务白名单 | `fast` 档 |
| `ui` | Qt 界面 + 真 QThread | `ui-retest` 档 |
| （无标记） | 其余全部 | `validate` 档 |

```python
pytestmark = pytest.mark.ui  # 整个文件是 Qt 用例时的常见写法
```

`validate`（`-m "not ui"`）与 `ui-retest`（`-m ui`）**互斥**，二者并集恰好覆盖全部用例、
恒等于 `full` —— 一个用例必须落进其中一档，没有「两档都不跑」的漏网空间。

## 测试文件组织

`tests/` 下 130+ 个文件，按被测对象命名。几个大类：

| 前缀 | 覆盖 |
|------|------|
| `test_qml_*` | QML 页面 / 对话框 / 桥 / 模型（占最大一块） |
| `test_plan_*` | 生产计划、拆解、执行 |
| `test_workers_*` | 后台 QThread |
| `test_industry_*` | 工业页控制器与对话框 |
| `test_theme_*` | 主题注册表与监听器 |
| `test_*_models` | 表格模型 |
| 其余 | 各自的 service / 领域模块 |

**不要在此处维护完整清单** —— 它必然过时。权威来源是 `tests/` 目录本身；
README 里的测试总数由 `scripts/check_readme.py` 与提交钩子强制同步（对不上会红）。

⚠️ 与 QML 相关的三条本仓特有约定（写在各自的 `test_qml_*.py` 里）：

- **每个新对话框都要过一遍「加载无 QML 告警」护栏**（`tests/test_qml_dialogs.py` 的
  `_assert_loads_and_quiet`）—— 缺 import / 绑错属性这类问题只在运行时吐一条，静态扫描看不见；
- **「只有真窗口才看得见」的东西必须真机核对**：字形（离屏下 `QFontDatabase` 是 0 个字体，
  文字全成方框）、DWM 毛玻璃、窗口拖动/缩放；
- **表格点击类用例要给点击点算绝对坐标**，且必须断言该行确实落在视口内 ——
  否则「点空了」会以「该选中第 N 行」的面目出现，把用例自身的问题伪装成产品故障。

## 测试 Fixtures

`conftest.py` 提供的关键 fixtures：`qapp` / `app`（含 `FluentWinUI3` 设置）、
`temp_db` / `db_manager`（四库临时数据库）、`mock_db`、`main_window`（QML 外壳）、
`industry_page`（工业页控制器）。

几条 `autouse` 的全局安全网，加测试时值得知道它们的存在：

- `no_auto_price_download` —— 阻断应用**自动发起**的网络（价格检查/下载、SDE/ESI 初始化）。
  它挂在「会自己发请求的那几个入口」上，不挂在某一层外壳的私有方法上（那样外壳一换就整片 setup 炸）；
- `isolate_user_settings` —— 把 `settings.json` 指向临时文件，测试绝不写用户真实数据；
- `_reset_qt_noise_state` —— 复位 `core.qt_noise` 的进程级退出标记（不复位会让后续用例的
  `notify()` 静默变空操作）。

## 代码质量工具

### ruff — Lint + Format

```bash
ruff check .                # 检查
ruff check . --fix          # 自动修复
ruff format .               # 格式化
ruff format --check .       # 检查格式
```

配置在 `pyproject.toml`：`line-length = 120`、`target-version = "py313"`，
启用 `E/W/F/B/I/M/C4/UP`（忽略 `E501`，交给格式化器）。

### mypy — 类型检查

```bash
mypy .
```

配置要点：`python_version = "3.14"`、`warn_unused_configs` / `warn_redundant_casts` 开启，
第三方库走 `ignore_missing_imports`。

## 提交前检查清单

```bash
ruff check . && mypy . && scripts/run_tests.sh full
```

外加 pre-commit 的文档联动钩子（README 动态数据、文档站内部链接、API 文档重生成）——
它们由 `.pre-commit-config.yaml` 在 `git commit` 时自动跑。

## CI 检查

`.github/workflows/ci.yml`，在 push `main`/`develop` 与 PR 到 `main` 时运行两个 job：

**`test`**（Python 3.14 + `uv sync --dev`，Linux runner）：

1. **ruff** — `ruff check .`
   （**不跑** `ruff format --check .`：仓库存在历史未格式化文件，跑则 CI 恒红，整改应单独立项）
2. **mypy** — `mypy . --ignore-missing-imports`
3. **pytest** — 全量 + 覆盖率，`QT_QPA_PLATFORM=offscreen`（无头 Qt；runner 需装 `libegl1`/`libgl1`）
4. **README 动态数据校验** — `scripts/check_readme.py`
5. **文档站内部链接校验** — `scripts/check_docs_links.py`
6. **Codecov** — 上传 `coverage.xml`

**`version-check`**（独立 job）：`scripts/check_version.py` 校验
`core/version.py` == CHANGELOG 最新版本段 == git tag（发版态），需 `fetch-depth: 0`。

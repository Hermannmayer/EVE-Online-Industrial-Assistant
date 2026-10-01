#!/usr/bin/env bash
# 测试分档脚本 — 开发循环用 fast/target，日常回归用 validate，提交前才用 full
# 用法: scripts/run_tests.sh [fast|validate|ui-retest|target|full]（默认 validate）
# fast      纯计算/轻服务（-m fast）        较快  改动 core/domain/轻服务时
# validate  全部业务/DB/计算（非 UI）       中等  日常默认回归
# ui-retest 全部 Qt 界面 + 真 QThread       较慢  改动 UI 或带 ui 标记的测试文件后
# target    只跑 git 变更相关测试文件       视变更量  开发循环默认；纯文档/配置变更直接跳过
# full      validate + ui-retest 两阶段     最慢  仅提交前，**时机由用户定**
#
# 不给固定秒数：耗时随机器负载波动极大（ui 段实测 221s ~ 445s）。权威说明见 CLAUDE.md「测试边界」。
set -euo pipefail
cd "$(dirname "$0")/.."

# 用项目虚拟环境里的解释器。**不要退回裸 `python`**：本机 PATH 上的 python 可能是
# 没装 pytest 的系统解释器，那样每条命令都以 `No module named pytest` 失败，
# 而调用方（人也好、脚本也好）若走管道看输出，很容易把失败当成通过。
# 显式指向 .venv，缺了就直接报错退出，不给「看起来跑了」的假象。
if [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"   # Windows
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"           # POSIX
else
  echo "找不到 .venv —— 先跑 \`uv sync --dev\`（项目约定：所有 Python 调用都走虚拟环境）" >&2
  exit 2
fi

MODE="${1:-validate}"

case "$MODE" in
  fast)
    "$PY" -m pytest tests/ -q -s -m fast --maxfail=1
    ;;
  validate)
    "$PY" -m pytest tests/ -q -s -m "not ui" --maxfail=5
    ;;
  ui-retest)
    # ⚠️ `-s`（--capture=no）**必须带**，不是图省事：pytest 默认捕获 stdout/stderr，
    # 而 Qt/QML 与 Python logging 都会往那里写；捕获管道被写满之后，QML 线程与主线程
    # 会在 `QQuickView.setSource()` 的同步等待上互锁 —— 整档挂到 faulthandler 的
    # 2 分钟超时，看着像「本机 QML 引擎坏了」。2026-09-28 实测：不带 `-s` 时
    # `tests/test_qml_shell.py` 240s 不返回；带上 `-s` 后同一份代码 **21.6s 跑完**。
    # 告警并没有丢：`test_qml_shell.py::test_shell_qml_loads_without_warnings` 自己
    # 临时装收集用的 message handler，那一条专门守「QML 加载无告警」。
    "$PY" -m pytest tests/ -q -s -m ui --maxfail=1
    ;;
  full)
    # 两阶段分离进程，杜绝 Qt 与 sqlite 混跑互扰
    "$PY" -m pytest tests/ -q -s -m "not ui" --maxfail=1 \
      && "$PY" -m pytest tests/ -q -s -m ui --maxfail=1
    ;;
  target)
    # 本次变更涉及的测试文件。
    # 非 .py 路径（文档/配置/锁文件/资源）不参与匹配：它们既会被 basename 子串误命中
    # （改 uv.lock → grep "uv"），又会在无命中时把整档拖回全量 validate。
    # .py 路径按「模块路径」反查，不用 basename 子串。
    changed="$(git diff --name-only HEAD) $(git ls-files --others --exclude-standard)"
    files=()
    lib_changed=0
    for f in $changed; do
      if [[ -z "$f" ]]; then continue; fi
      if [[ "$f" == tests/*.py ]]; then
        files+=("$f"); continue
      fi
      [[ "$f" == *.py ]] || continue
      # 只有这 5 个包是共享库代码；scripts/ 与入口脚本没匹配到测试也不必拖全量
      case "$f" in
        core/*|domain/*|services/*|ui_qml/*|bootstrap/*) lib_changed=1 ;;
      esac
      mod="${f%.py}"; mod="${mod//\//.}"   # services/importers/getprices.py → services.importers.getprices
      name="${mod##*.}"; parent="${mod%.*}"
      pats=(-e "from $mod import" -e "import $mod")
      # 也覆盖 `from services import pricing_service` 这种写法
      [[ "$parent" == "$mod" ]] || pats+=(-e "from $parent import $name")
      # shellcheck disable=SC2207
      files+=($(grep -rl "${pats[@]}" --include='*.py' tests/ 2>/dev/null || true))
    done
    if [[ ${#files[@]} -eq 0 ]]; then
      if [[ "$lib_changed" -eq 1 ]]; then
        echo "库代码有变更但未匹配到测试文件，跑 validate 全量" >&2
        "$PY" -m pytest tests/ -q -s -m "not ui" --maxfail=5
      else
        echo "仅文档/配置/工具变更，无需跑测试" >&2
        exit 0
      fi
    else
      # `test_qml_dialogs.py` 有一条**实测出来的前置依赖**：单独点名它会挂在第一条用例
      # （`[编辑生产计划]`）不动，而先跑一遍 `test_qml_all_items.py`（同样加载 QML）之后
      # 再跑它就是 **122 passed in 23.9s** 全绿。点名到它就把前置带上，省得每次都踩。
      # （`-m ui` 整档跑不受影响：字母序里 `test_qml_all_items.py` 本来就在它前面。）
      if printf '%s\n' "${files[@]}" | grep -q 'test_qml_dialogs\.py' \
         && ! printf '%s\n' "${files[@]}" | grep -q 'test_qml_all_items\.py'; then
        echo "点名到 test_qml_dialogs.py，自动补上前置 test_qml_all_items.py" >&2
        files+=(tests/test_qml_all_items.py)
      fi
      mapfile -t files < <(printf '%s\n' "${files[@]}" | sort -u)
      "$PY" -m pytest "${files[@]}" -q -s --maxfail=1
    fi
    ;;
  *)
    echo "用法: scripts/run_tests.sh [fast|validate|ui-retest|target|full]（默认 validate）" >&2
    exit 1
    ;;
esac

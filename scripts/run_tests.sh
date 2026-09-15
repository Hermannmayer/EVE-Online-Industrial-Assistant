#!/usr/bin/env bash
# 测试分档脚本 — 开发循环用 fast/target，日常回归用 validate，提交前才用 full
# 用法: scripts/run_tests.sh [fast|validate|ui-retest|target|full]（默认 validate）
# fast      纯计算/轻服务（-m fast）         <10s   改动 core/domain/轻服务时
# validate  全部业务/DB/计算（非 UI）        ~45s   日常默认回归
# ui-retest 全部 Qt 界面 + 真 QThread        ~40s   改动 UI 后补跑
# target    只跑 git 变更相关测试文件        <5s    改动涉及 UI 时优先
# full      validate + ui-retest 两阶段     ~80s   仅提交前
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
    "$PY" -m pytest tests/ -q -m fast --maxfail=1
    ;;
  validate)
    "$PY" -m pytest tests/ -q -m "not ui" --maxfail=5
    ;;
  ui-retest)
    "$PY" -m pytest tests/ -q -m ui --maxfail=1
    ;;
  full)
    # 两阶段分离进程，杜绝 Qt 与 sqlite 混跑互扰
    "$PY" -m pytest tests/ -q -m "not ui" --maxfail=1 \
      && "$PY" -m pytest tests/ -q -m ui --maxfail=1
    ;;
  target)
    # 收集本次变更涉及的文件；非 tests 路径按模块 basename 反查对应 test_*.py
    changed="$(git diff --name-only HEAD) $(git ls-files --others --exclude-standard)"
    files=()
    for f in $changed; do
      if [[ -z "$f" ]]; then continue; fi
      if [[ "$f" == tests/* ]]; then
        files+=("$f")
      else
        mod="$(basename "$f" .py)"
        # shellcheck disable=SC2207
        files+=($(grep -l "$mod" tests/test_*.py 2>/dev/null || true))
      fi
    done
    if [[ ${#files[@]} -eq 0 ]]; then
      echo "未检测到变更的测试文件，跑 validate 全量" >&2
      "$PY" -m pytest tests/ -q -m "not ui" --maxfail=5
    else
      "$PY" -m pytest "${files[@]}" -q --maxfail=1
    fi
    ;;
  *)
    echo "用法: scripts/run_tests.sh [fast|validate|ui-retest|target|full]（默认 validate）" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
# 测试分档脚本 — 开发循环用 quick/target，提交前才用 full
# 用法: scripts/run_tests.sh [quick|target|full]（默认 quick）
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-quick}"

case "$MODE" in
  quick)  # 日常快速回归：跳过 Qt 慢速测试（~23s）
    python -m pytest tests/ -q --quick --maxfail=1
    ;;
  target)  # 只跑主窗口相关文件（~4s），改动涉及 UI 时优先
    python -m pytest tests/test_ui_main_window.py tests/test_main_window.py -q
    ;;
  full)  # 全量回归：含 Qt（~1.5min），仅提交前
    python -m pytest tests/ -q --maxfail=1
    ;;
  *)
    echo "用法: scripts/run_tests.sh [quick|target|full]（默认 quick）" >&2
    exit 1
    ;;
esac

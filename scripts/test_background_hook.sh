#!/usr/bin/env bash
# PostToolUse hook：改动 core/services/tests 时在后台自动跑 quick 测试
# - 只监听 Edit/Write 工具，仅当目标文件在 core/ services/ tests/ 下触发
# - 用锁文件防重复（已有后台测试在跑则跳过）
# - 后台子 shell 写 .claude/test-last.log，立即返回不阻塞
set -u

HOOK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HOOK_DIR"

# 从 hook stdin 取被编辑文件路径
input="$(cat)"
file_path="$(printf '%s' "$input" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(''); sys.exit(0)
print(d.get('file_path') or d.get('tool_input', {}).get('file_path') or '')
" 2>/dev/null)"

case "$file_path" in
  services/*|core/*|tests/*)
    ;;
  *)
    exit 0
    ;;
esac

LOCK=".claude/.test-running"
[ -f "$LOCK" ] && exit 0   # 已有后台测试在跑
[ -d .claude ] || mkdir -p .claude
touch "$LOCK"

(
  uv run python -m pytest tests/ -q --quick > .claude/test-last.log 2>&1
  rm -f "$LOCK"
) &

echo "🔄 后台快速测试已启动（core/services/tests 变更）：结果见 .claude/test-last.log"

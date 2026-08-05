#!/usr/bin/env bash
# setup_worktree.sh — worktree 快速初始化（免重新下载 SDE）
#
# 用法：在新拆分的 worktree 目录下执行：  bash scripts/setup_worktree.sh
#
# 作用：
#   1. uv sync --dev                      # uv 全局缓存命中，约 3s
#   2. 把 data/、database/ 以 junction 链接到 main 工作树的同名目录
#      → 复用 universe_data.json、typeIDs.yaml、reference.db 等，
#        无需在每个 worktree 重新下载 SDE / 重新生成数据
#
# 安全设计：
#   - 仅当 worktree 内的 data/、database/ 只含 git 跟踪文件时才建立链接；
#     若含独立生成的未跟踪数据（旧 worktree 已初始化过）则跳过并保留原目录。
#   - junction 用 PowerShell `New-Item -ItemType Junction`，不需要管理员权限；重复运行幂等。
#   - 测试在 conftest 中已隔离为临时数据库，不会经由链接污染 main 的真实数据。
set -euo pipefail
cd "$(dirname "$0")/.."

CUR_ROOT="$(git rev-parse --show-toplevel)"
MAIN_ROOT="$(git worktree list | awk '$3 == "[main]" {print $1; exit}')"

if [ -z "$MAIN_ROOT" ]; then
    echo "错误: 找不到 main 工作树（git worktree list 中无 [main] 条目）" >&2
    exit 1
fi
if [ "$CUR_ROOT" = "$MAIN_ROOT" ]; then
    echo "这是 main 工作树本身，无需链接。请在新拆分的 worktree 中运行。" >&2
    exit 0
fi

# 转成 Windows 反斜杠路径给 PowerShell New-Item；非 Git Bash（无 cygpath）时原样使用
win() { cygpath -w "$1" 2>/dev/null || echo "$1"; }

link_dir_to_main() {
    local name="$1"
    local link="$CUR_ROOT/$name"
    local target="$MAIN_ROOT/$name"

    # 已是目录链接（junction / 符号链接）→ 幂等跳过
    if [ -L "$link" ]; then
        echo "  ✓ $name 已是链接，跳过"
        return 0
    fi

    if [ -e "$link" ]; then
        if [ ! -d "$link" ]; then
            echo "  ⚠ $name 已存在且不是目录，跳过"
            return 0
        fi
        # 检查目录里是否有 git 未跟踪的内容（独立生成的运行时数据）
        local extra
        extra="$(ls -A "$link" | while read -r f; do
            git ls-files --error-unmatch "$name/$f" >/dev/null 2>&1 || echo "$f"
        done)"
        if [ -n "$extra" ]; then
            echo "  ⚠ $name/ 含未跟踪数据（$(echo "$extra" | tr '\n' ' ')），保留独立目录，跳过链接"
            return 0
        fi
        rm -rf "$link"
    fi

    if [ ! -d "$target" ]; then
        echo "  ⚠ main 的 $name/ 不存在，跳过"
        return 0
    fi

    # Windows 10+ 自带 PowerShell；junction 无需管理员权限
    powershell -NoProfile -Command "New-Item -ItemType Junction -Path '$(win "$link")' -Target '$(win "$target")' | Out-Null"
    echo "  ✓ $name → $target"
}

echo "==> [1/2] 安装依赖: uv sync --dev"
uv sync --dev

echo "==> [2/2] 链接运行时数据到 main 工作树"
link_dir_to_main "data"
link_dir_to_main "database"

echo
echo "完成。worktree 已就绪，数据源: $MAIN_ROOT"

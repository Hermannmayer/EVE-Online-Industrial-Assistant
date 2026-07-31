"""
代码变更 → 文档更新提醒（pre-commit 用，不阻塞提交）

检查本次暂存(staged)的改动：若改了业务/UI 代码但未同步更新对应文档
（docs/user、docs/dev、README），打印提醒。

不阻塞（返回 0）——仅引导人工更新说明文档。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 兼容 Windows GBK 控制台：无法编码的字符（emoji 等）用 ? 替换
try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# 代码目录 → 应同步的文档目录
CODE_DIRS = ("core/", "services/", "ui_pyside6/")
DOC_PATTERNS = ("docs/user/", "docs/dev/", "README.md")

# 纯内部改动（测试/构建/文档本身）不提醒
CODE_PY_SUFFIXES = (".py",)


def staged_files() -> list[str]:
    """获取本次暂存的文件列表"""
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def main() -> int:
    files = staged_files()
    if not files:
        return 0

    code_changed = [f for f in files if f.startswith(CODE_DIRS) and f.endswith(CODE_PY_SUFFIXES)]
    docs_changed = [f for f in files if f.startswith(DOC_PATTERNS) or f.startswith("docs/guide/")]

    if not code_changed:
        return 0

    # 排除纯重构/测试辅助：只提醒业务逻辑变更
    business_code = [
        f for f in code_changed if not f.startswith(("core/logger.py", "core/paths.py", "core/constants.py"))
    ]

    if business_code and not docs_changed:
        print()
        print("ℹ️  ⚠️  检测到业务代码变更，但本次提交未同步更新说明文档:")
        print("    " + ", ".join(business_code[:8]))
        print("    建议同步更新: docs/user/（用户手册）、docs/dev/（开发文档）、README.md（若涉及功能/结构）")
        print("    仅提醒，不阻塞提交。\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

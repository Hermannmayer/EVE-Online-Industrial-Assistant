"""
版本一致性校验 — CI 阻断脚本。

校验规则（dev 态 / 发版态）：
  1. `core/version.py` 的 `__version__` 必须等于 `CHANGELOG.md` 中最新版本段
     （`<!-- version list -->` 之后的第一个 `## vX.Y.Z` 标题）。
  2. 发版态（HEAD 恰好指向一个 `vX.Y.Z` tag）额外要求 `__version__`
     与该 git tag 完全一致。

用法：
    python scripts/check_version.py
退出码：
    0 = 通过
    1 = 不一致（CI 会 fail，阻断合并）
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── 路径 ──
ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "core" / "version.py"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"

# 兼容 Windows GBK 控制台：无法编码的字符（emoji 等）用 ? 替换
# （TextIO.reconfigure 为 Python 3.7+ 运行时存在但 typeshed 未收录）
sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]

# CHANGELOG 最新版本段：`<!-- version list -->` 之后第一个 `## vX.Y.Z (date)` 标题
_VERSION_HEADING_RE = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\b", re.MULTILINE)
_VERSION_FILE_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def _read_version_file() -> str:
    """从 core/version.py 解析 __version__。"""
    if not VERSION_FILE.exists():
        sys.exit(f"❌ 缺少版本源文件: {VERSION_FILE}")
    m = _VERSION_FILE_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f'❌ {VERSION_FILE} 中未找到 __version__ = "X.Y.Z"')
    return m.group(1)


def _read_latest_changelog_version() -> str:
    """返回 CHANGELOG.md 中最新版本段（无则退出码 1）。"""
    if not CHANGELOG_FILE.exists():
        sys.exit(f"❌ 缺少 CHANGELOG.md: {CHANGELOG_FILE}")
    content = CHANGELOG_FILE.read_text(encoding="utf-8")

    # 只扫描 `<!-- version list -->` 之后的版本段；无该标记则扫描全文
    marker = "<!-- version list -->"
    body = content.split(marker, maxsplit=1)[-1] if marker in content else content
    m = _VERSION_HEADING_RE.search(body)
    if not m:
        sys.exit("❌ CHANGELOG.md 中未找到 `## vX.Y.Z` 最新版本段")
    return m.group(1)


def _head_exact_tag() -> str | None:
    """HEAD 恰好指向某个 vX.Y.Z tag 时返回该版本，否则 None。"""
    try:
        proc = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    m = _TAG_RE.match(proc.stdout.strip())
    return m.group(1) if m else None


def main() -> int:
    version = _read_version_file()
    changelog_version = _read_latest_changelog_version()

    errors: list[str] = []

    if version != changelog_version:
        errors.append(f"core/version.py = {version!r} ≠ CHANGELOG.md 最新版本段 = {changelog_version!r}")

    # 发版态：HEAD 指向 tag → 三源必须一致
    if (tag := _head_exact_tag()) is not None:
        if version != tag:
            errors.append(f"core/version.py = {version!r} ≠ git tag = {tag!r}")
    else:
        print("ℹ️  开发态（HEAD 无 vX.Y.Z tag），跳过 tag 一致性校验")

    if errors:
        print("❌ 版本一致性校验失败：")
        for e in errors:
            print(f"   - {e}")
        print("   请同步 core/version.py / CHANGELOG.md / git tag 三者版本。")
        return 1

    print(f"✅ 版本一致性校验通过：core/version.py = CHANGELOG = {version!r}" + (f" = git tag v{tag}" if tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

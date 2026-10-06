"""从 CHANGELOG.md 抽出某个版本段 → 写进文件（GitHub Release 说明用）。

**为什么需要它**：`release.yml` 有两条发版路径 ——
- PSR 正常发版：Release 由 PSR 创建，说明就是它刚写进 CHANGELOG 的那一段；
- 「手改版本号的小版本」（PSR 判定无需发版，回退用 `core/version.py` 的版本打包）：
  Release 由 `action-gh-release` 创建，而它**没有 body 时会拿提交信息当说明** ——
  2026-10-06 实测把整段提交正文（异动榜那份长文）贴上了 Release 页面。
所以回退那条路径要显式给它一段说明：本脚本从 CHANGELOG 抽出 `## v{version}` 那一段。

用法（CI：`uv run python scripts/release_notes.py "$VER" release_notes.md`）：
    python scripts/release_notes.py 0.26.1 release_notes.md

找不到该版本段 → 退出码 1（宁可让步骤红，也不要静默贴一段错说明）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def extract_section(version: str, text: str) -> str:
    """取出 `## v{version}` 到下一个 `## v` 之间的内容（含标题行）。"""
    match = re.search(rf"^## v{re.escape(version)}\b.*?(?=^## v|\Z)", text, re.M | re.S)
    return match.group(0).rstrip() + "\n" if match else ""


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    version, out_path = argv[1], Path(argv[2])
    section = extract_section(version, CHANGELOG.read_text(encoding="utf-8"))
    if not section:
        print(f"CHANGELOG.md 里找不到 v{version} 段", file=sys.stderr)
        return 1
    out_path.write_text(section, encoding="utf-8")
    print(f"v{version} 的说明已写入 {out_path}（{len(section)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

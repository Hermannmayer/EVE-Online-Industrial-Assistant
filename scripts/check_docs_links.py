"""
文档站内部链接检查 — 扫描 docs/**/*.md 所有内部链接，报告孤儿页面

覆盖:
  - Markdown 链接: [text](/dev/setup)、[text](../../CHANGELOG.md)
  - VitePress 导航 link: link: '/guide/intro'
  - 相对路径链接（.md 结尾）
排除:
  - 外部链接 (http/https/mailto)
  - 锚点 (#)、图片 (![])、内联 HTML

用法:
    python scripts/check_docs_links.py    # 有孤儿链接返回 1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

# 提取 markdown 链接 [text](target) 和 vitepress link: 'target'
_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_VP_LINK_RE = re.compile(r"link:\s*['\"]([^'\"]+)['\"]")
_ANGLE_RE = re.compile(r"<https?://[^>]+>")  # 尖括号包住的外部链接


def resolve_target(base_file: Path, target: str) -> Path | None:
    """把链接 target 解析为 docs 下的目标文件路径；外部/锚点返回 None"""
    target = target.strip()
    # 去掉锚点和查询
    target = re.split(r"[#?]", target)[0]
    if not target:
        return None
    # 外部链接
    if target.startswith(("http://", "https://", "mailto:", "ftp://")):
        return None
    # 相对链接（以 .md 结尾，非绝对路径）
    if target.endswith(".md") and not target.startswith("/"):
        resolved = (base_file.parent / target).resolve()
        # 只接受 docs/ 内的目标
        try:
            resolved.relative_to(DOCS.resolve())
        except ValueError:
            return None
        return resolved
    # 绝对 vitepress 路径 /xxx/yyy → docs/xxx/yyy.md（或 index.md）
    if target.startswith("/"):
        rel = target.lstrip("/")
        candidate = DOCS / f"{rel}.md"
        if not candidate.exists():
            candidate = DOCS / rel / "index.md"
        return candidate if candidate.exists() else candidate  # 返回（即使不存在，由调用方报错）
    return None


def check_file(path: Path) -> list[str]:
    """检查单个 md 文件的所有内部链接，返回孤儿列表"""
    text = path.read_text(encoding="utf-8")
    # 过滤掉尖括号外部链接避免误报
    text = _ANGLE_RE.sub("", text)
    orphans = []
    for m in _MD_LINK_RE.finditer(text):
        target = resolve_target(path, m.group(1))
        if target is not None and not target.exists():
            orphans.append(f"  {path.relative_to(ROOT)} → {m.group(1)}")
    for m in _VP_LINK_RE.finditer(text):
        target = resolve_target(path, m.group(1))
        if target is not None and not target.exists():
            orphans.append(f"  {path.relative_to(ROOT)} → link: {m.group(1)}")
    return orphans


def main() -> int:
    all_orphans: list[str] = []
    for f in sorted(DOCS.rglob("*.md")):
        if ".vitepress" in f.parts:
            continue
        all_orphans.extend(check_file(f))

    if all_orphans:
        print(f"❌ 发现 {len(all_orphans)} 个孤儿链接:")
        print("\n".join(all_orphans))
        return 1

    print("✅ 文档站内部链接全部有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())

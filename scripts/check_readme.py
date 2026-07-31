"""
README 动态数据校验/更新 — 测试总数、测试文件清单与实际一致

校验点:
  1. 测试总数: README `| 📊 **测试总数** | N 个 |` == 实际 `def test_` 计数
  2. 测试文件清单: README 测试表格中的文件是否都存在（新增文件缺失 → 警告）

用法:
    python scripts/check_readme.py            # 检查（不一致返回 1）
    python scripts/check_readme.py --update   # 自动更新 README 测试总数
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
TESTS_DIR = ROOT / "tests"

# 兼容 Windows GBK 控制台
try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

_TOTAL_RE = re.compile(r"(\|\s*📊 \*\*测试总数\*\*\s*\|\s*)(\d+)(\s*个\s*\|)")


def count_tests() -> int:
    """统计实际测试用例数（def test_ 出现次数）"""
    total = 0
    for f in TESTS_DIR.glob("test_*.py"):
        total += sum(1 for _ in re.finditer(r"\bdef test_", f.read_text(encoding="utf-8")))
    return total


def readme_test_files() -> list[str]:
    """README 测试表格中列出的文件"""
    text = README.read_text(encoding="utf-8")
    # 测试文件表格在「### 测试文件」之后，到下一个 `## ` 之前
    m = re.search(r"### 测试文件\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r"\|\s*`(test_[^`]+\.py)`", m.group(1))


def update_readme(total: int) -> bool:
    """更新 README 测试总数，返回是否修改"""
    text = README.read_text(encoding="utf-8")
    new_text = _TOTAL_RE.sub(lambda m: f"{m.group(1)}{total}{m.group(3)}", text, count=1)
    if new_text == text:
        return False
    README.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    update = "--update" in sys.argv
    actual = count_tests()

    text = README.read_text(encoding="utf-8")
    m = _TOTAL_RE.search(text)
    if not m:
        print("❌ README 未找到「测试总数」行")
        return 1

    readme_total = int(m.group(2))
    errors = []

    if readme_total != actual:
        if update:
            if update_readme(actual):
                print(f"✅ README 测试总数已更新: {readme_total} → {actual}")
            return 0
        errors.append(f"❌ README 测试总数 {readme_total} ≠ 实际 {actual}（跑 --update 自动修正）")

    # 测试文件清单：README 列的每个具体文件都应存在（跳过 glob 通配符如 test_workers_*.py）
    missing = [f for f in readme_test_files() if "*" not in f and not (TESTS_DIR / f).exists()]
    if missing:
        errors.append(f"❌ README 列出的测试文件不存在: {', '.join(missing)}")

    if errors:
        print("\n".join(errors))
        return 1

    print(f"✅ README 动态数据一致（测试总数 {actual}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

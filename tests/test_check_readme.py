"""README 动态数据守卫（`scripts/check_readme.py`）的自身测试。

**为什么值得单测这个脚本**：它是 pre-commit 钩子，是「README 里的测试清单是否
说真话」的唯一防线。而它原先的正则要求反引号紧跟行首的 `|`，于是**一行写多个
文件时只校验第一个** —— `test_scoring_cache.py`、`test_contract_ui.py` 两个早已
不存在的文件就这么在 README 里躺了很久，钩子每次还都通过。
守卫撤防比没有守卫更危险，所以这里把它的判据钉住。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("check_readme", _ROOT / "scripts" / "check_readme.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_readme"] = module
    spec.loader.exec_module(module)
    return module


cr = _load()

#: 一行写多个文件是 README 里的常见写法，第一格之外的那些同样要被校验
_MULTI_PER_ROW = """### 测试文件

| 文件 | 说明 |
|------|------|
| `test_a.py` / `test_b.py` | 两个都要校验 |
| `test_c.py` | 单文件 |
| `test_workers_*.py` | 通配符应被跳过 |

## 下一节
"""


@pytest.mark.fast
def test_readme_test_files_takes_every_file_on_a_row(monkeypatch, tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(_MULTI_PER_ROW, encoding="utf-8")
    monkeypatch.setattr(cr, "README", readme)

    assert cr.readme_test_files() == ["test_a.py", "test_b.py", "test_c.py", "test_workers_*.py"]


@pytest.mark.fast
def test_readme_test_files_stops_at_the_next_section(monkeypatch, tmp_path):
    """只取「### 测试文件」到下一个 `## ` 之间 —— 别把别的章节里的文件名也算进来。"""
    readme = tmp_path / "README.md"
    readme.write_text(_MULTI_PER_ROW + "\n| `test_outside.py` | 不该被算进来 |\n", encoding="utf-8")
    monkeypatch.setattr(cr, "README", readme)

    assert "test_outside.py" not in cr.readme_test_files()


@pytest.mark.fast
def test_readme_lists_only_existing_test_files():
    """仓库当下的 README 不许列不存在的测试文件（钩子里那条判据的回归）。"""
    missing = [f for f in cr.readme_test_files() if "*" not in f and not (cr.TESTS_DIR / f).exists()]
    assert missing == [], f"README 列的测试文件不存在: {missing}"


@pytest.mark.fast
def test_readme_test_total_matches_reality():
    """README 的「测试总数」必须等于实际 `def test_` 计数。"""
    text = cr.README.read_text(encoding="utf-8")
    match = cr._TOTAL_RE.search(text)
    assert match is not None, "README 里找不到「测试总数」行"
    assert int(match.group(2)) == cr.count_tests()

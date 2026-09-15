"""QML 侧不得反向依赖 Widgets 侧 —— 批次 6.0 的护栏。

`ui_qml` 是新的 UI 层，`ui_pyside6` 是待删的旧层。一旦 `ui_qml` 又 import 回去，
「删掉 ui_pyside6」就永远做不成；而这类依赖是**悄悄长出来**的：每迁一个对话框、
每接一个 worker 都可能多一条，代码评审很难逐条盯住。

所以把允许清单**钉死**：既挡新增依赖，也挡清单变陈旧（允许项一旦不再被用到，
测试同样会红，逼着在 6.2 把它划掉）。
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_QML_DIR = _REPO / "ui_qml"

#: 允许清单：相对 `ui_qml/` 的路径 → 允许它 import 的 `ui_pyside6` 子模块。
#:
#: 现在只剩一条：工业页的 **Widgets 控制器**（`IndustryPage`）—— 注册表页工厂要它
#: 提供 QML 宿主，而它自己也还兼着「QML 加载失败时的回退页」。删它必须等批次 6.2
#: 外壳替换，所以是**已知的、有期限的**例外，不是漏网之鱼。
_ALLOWED: dict[str, set[str]] = {
    "industry_page.py": {"ui_pyside6.views.industry_view"},
}


def _imports_of(path: Path) -> set[str]:
    """该文件里出现的、以 `ui_pyside6` 开头的 import 目标。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # 只认绝对导入；相对导入（`from .x import y`）到不了 ui_pyside6
            if node.module and node.level == 0:
                found.add(node.module)
    return {name for name in found if name == "ui_pyside6" or name.startswith("ui_pyside6.")}


def _scan() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in sorted(_QML_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        hits = _imports_of(path)
        if hits:
            out[path.relative_to(_QML_DIR).as_posix()] = hits
    return out


def test_ui_qml_does_not_import_ui_pyside6_beyond_the_allowlist():
    found = _scan()
    unexpected = {
        rel: sorted(mods - _ALLOWED.get(rel, set())) for rel, mods in found.items() if mods - _ALLOWED.get(rel, set())
    }
    assert not unexpected, (
        "ui_qml 里出现了新的 ui_pyside6 依赖（批次 6.0 的目标是把它清干净）：\n"
        + "\n".join(f"  {rel} → {mods}" for rel, mods in sorted(unexpected.items()))
        + "\n要么把它搬到 ui_qml/ 或 core/（共享件），要么——若确属必须——"
        "在 tests/test_qml_import_boundary.py 的 _ALLOWED 里写明理由与期限。"
    )


def test_the_allowlist_is_not_stale():
    """允许清单里每一项都必须**仍在使用**。

    6.2 删掉工业页控制器后，这条会先红 —— 提醒把这唯一一条例外一起划掉，
    否则清单会变成「看着还有例外、其实早就不需要」的假账。
    """
    found = _scan()
    for rel, allowed in _ALLOWED.items():
        assert rel in found, f"{rel} 已经不再 import ui_pyside6，请把它从 _ALLOWED 里删掉"
        assert found[rel] & allowed, f"{rel} 不再 import {sorted(allowed)}，请更新 _ALLOWED"

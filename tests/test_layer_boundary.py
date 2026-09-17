"""分层边界护栏：低层不得反向依赖高层。

**为什么需要**（原 `test_qml_import_boundary.py` 的 docstring 说得很准，保留其判断）：
「这类依赖是**悄悄长出来**的：每迁一个对话框、每接一个 worker 都可能多一条，
代码评审很难逐条盯住。」

那个文件原本守的是 `ui_qml` 不得 import 待删的 `ui_pyside6`。批次 7.5 删掉
`ui_pyside6/` 之后，被守的目标消失了，该文件随之删除 —— 但它自述「文件本身保留：
继续挡『未来又长出反向依赖』」的意图仍然成立，只是**被守的边界换了一条**：

    domain/  ← 纯函数，不得 import 任何上层
    core/    ← 工具，同上
    services/ ← 业务，不得 import ui_*

现在的守卫目标是**第二条**：`services/` `core/` `domain/` 不得 import `ui_qml`
（QML 迁移期间最容易长出来的就是这个方向：桥里顺手写个服务函数、再用 UI 类型标注）。

`ui_qml → ui_pyside6` 那条已无意义（包不存在，真写了会当场 ImportError），
但顺着原文件「挡未来反向依赖」的本意，把检查做成**按层声明**的形式。
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

#: 层 → 该层禁止 import 的包前缀。
#: 只列真实会踩的方向；「向上依赖」在分层里是错的，「向下依赖」是正常的。
#:
#: 关于 `domain` ↔ `core`：CLAUDE.md 把 `core/` 定义为「工具/常量」，
#: 而 `domain/scoring.py` 与 `domain/market_depth.py` 确实 import 了
#: `core.eve_formulas` / `core.constants` 里的**常量**（税率系数、价格深度阈值）。
#: 常量不是行为、也不引入 DB/Qt/缓存 依赖，所以 `domain → core` 是**合法**的向下依赖，
#: 不列入禁止项 —— 护栏要挡的是「低层依赖高层的行为」，不是「禁止一切跨层 import」。
_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "domain": ("ui_qml", "services"),
    "core": ("ui_qml", "services"),
    "services": ("ui_qml",),
}


def _imported_top_levels(path: Path) -> set[str]:
    """该文件 import 的顶层包名（绝对导入；相对导入出不了本包）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_layers_do_not_depend_upward():
    """domain/core/services 都不得 import 比它高的层。"""
    violations: list[str] = []
    for layer, forbidden in _FORBIDDEN.items():
        root = _REPO / layer
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            hits = _imported_top_levels(path) & set(forbidden)
            if hits:
                rel = path.relative_to(_REPO).as_posix()
                violations.append(f"  {rel} → {', '.join(sorted(hits))}")

    assert not violations, (
        f"{len(violations)} 处向上依赖（分层 {list(_FORBIDDEN)} 只允许向下）：\n"
        + "\n".join(violations)
        + "\n把共享件下沉到 core/ 或 domain/，不要从低层 import 高层。"
    )

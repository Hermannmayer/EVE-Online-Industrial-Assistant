"""测试判定表体检 —— 手动开发工具，只报告不改动，永远退出 0。

扫 `tests/` 下的用例，报出 CLAUDE.md「测试判定表」里列为**禁止**的断言：
    外观值 / 标准库或内建类型行为 / 零信息（整个用例只有非 None 断言）/ mock 调用序列

判据是启发式的（按属性名与调用名匹配），会有误报 —— 这是给人看的清单，不是门禁。
不接入 pre-commit、不接入 CI：保持手动运行，与 `shell_snapshot.py` / `gen_api_docs.py` 同类。

用法：
    python scripts/test_audit.py                 # 扫 tests/ 全部
    python scripts/test_audit.py tests/test_x.py # 只扫指定文件（自查新增用例）
    python scripts/test_audit.py --stat          # 只出分类计数
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 输出固定 UTF-8：Windows 控制台本来就是 UTF-8，但**重定向到文件/管道时会退回区域编码（GBK）**，
# 那样导出的报告是乱码、也无法被其它工具读取。errors="replace" 兜住无法编码的字符。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# ── 启发式词表 ──
APPEARANCE_ATTRS = {
    "family",
    "pointsize",
    "pointsizef",
    "weight",
    "alignment",
    "align",
    "color",
    "colour",
    "background",
    "foreground",
    "stylesheet",
    "bold",
    "italic",
}
GEOMETRY_ATTRS = {
    "width",
    "height",
    "x",
    "y",
    "size",
    "pos",
    "geometry",
    "minimumwidth",
    "maximumwidth",
    "minimumheight",
    "maximumheight",
}
# 按**变量名**匹配的（比按属性名匹配更容易误伤）。刻意不收 x / y / size：
# 它们在领域代码里是循环变量与船体级别（`for x in ...`、`size in ("M","L","XL")`）。
# 几何判定只认属性访问（`pt.x()`、`widget.width()`），那样才真是在量像素。
APPEARANCE_NAMES = {
    "family",
    "font",
    "color",
    "colour",
    "background",
    "foreground",
    "stylesheet",
    "alignment",
    "align",
    "bg",
    "fg",
}

STDLIB_ROOTS = {"sqlite3", "logging", "collections", "pathlib", "types", "os", "sys", "json", "re"}
BUILTIN_TYPES = {"list", "dict", "str", "int", "float", "bool", "tuple", "set", "bytes", "None"}

MOCK_CALLS = {
    "assert_called",
    "assert_called_once",
    "assert_called_with",
    "assert_called_once_with",
    "assert_any_call",
    "assert_not_called",
    "call_count",
    "call_args",
    "call_args_list",
}

CATEGORIES = ("外观/几何断言", "标准库或内建类型断言", "零信息（仅非 None）", "mock 调用序列")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    category: str
    snippet: str


def _attr_names(node: ast.AST) -> set[str]:
    return {n.attr.lower() for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _name_ids(node: ast.AST) -> set[str]:
    return {n.id.lower() for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.id, str)}


def _is_appearance(node: ast.AST) -> bool:
    if _attr_names(node) & (APPEARANCE_ATTRS | GEOMETRY_ATTRS):
        return True
    return bool(_name_ids(node) & APPEARANCE_NAMES)


def _is_stdlib_isinstance(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance"):
            continue
        if len(n.args) < 2:
            continue
        target = n.args[1]
        if isinstance(target, ast.Name) and target.id in BUILTIN_TYPES:
            return True
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in STDLIB_ROOTS:
            return True
    return False


def _is_mock_call(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MOCK_CALLS:
            return True
        if isinstance(n, ast.Attribute) and n.attr in MOCK_CALLS:
            return True
        if isinstance(n, ast.Name) and n.id in MOCK_CALLS:
            return True
    return False


def _is_not_none(node: ast.Compare) -> bool:
    """`X is not None` —— 必须是字面 None 比较。

    `X is not Y`（身份断言）是有信息量的，不能算「零信息」。
    """
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.IsNot):
        return False
    comparator = node.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value is None


def _snippet(source_lines: list[str], node: ast.AST) -> str:
    line = getattr(node, "lineno", 1)
    return source_lines[line - 1].strip() if 0 < line <= len(source_lines) else ""


# 顺序即优先级：一个 assert 只归入第一个命中的类别
_ASSERT_RULES: tuple[tuple[str, object], ...] = (
    ("mock 调用序列", _is_mock_call),
    ("外观/几何断言", _is_appearance),
    ("标准库或内建类型断言", _is_stdlib_isinstance),
)


def _scan_scope(func: ast.FunctionDef) -> tuple[list[ast.Assert], list[ast.Expr]]:
    """收集函数内的断言与表达式语句，**含 with/try/if 等嵌套块**，但不进入嵌套函数/类。

    只看 `func.body` 顶层是不够的：真实用例把断言写在 `with temp_db.connect() as conn:` 里，
    那样会整批漏掉。
    """
    asserts: list[ast.Assert] = []
    exprs: list[ast.Expr] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assert):
            asserts.append(node)
        elif isinstance(node, ast.Expr):
            exprs.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return asserts, exprs


def scan_source(source: str, filename: str = "<string>") -> list[Finding]:
    """扫一段测试源码，返回命中判定表禁止项的条目。供测试直接喂字符串。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding(filename, exc.lineno or 1, "解析失败", str(exc))]

    lines = source.splitlines()
    findings: list[Finding] = []

    for func in ast.walk(tree):
        if not (isinstance(func, ast.FunctionDef) and func.name.startswith("test_")):
            continue
        asserts, exprs = _scan_scope(func)
        for assert_stmt in asserts:
            for category, rule in _ASSERT_RULES:
                if rule(assert_stmt.test):  # type: ignore[operator]
                    findings.append(Finding(filename, assert_stmt.lineno, category, _snippet(lines, assert_stmt)))
                    break
        # pytest-mock 的常见写法是裸表达式：`mock.assert_called_once_with(...)`
        for expr_stmt in exprs:
            if _is_mock_call(expr_stmt.value):
                findings.append(Finding(filename, expr_stmt.lineno, "mock 调用序列", _snippet(lines, expr_stmt)))
        if asserts and all(isinstance(s.test, ast.Compare) and _is_not_none(s.test) for s in asserts):
            findings.append(Finding(filename, asserts[0].lineno, "零信息（仅非 None）", _snippet(lines, asserts[0])))
    return findings


def scan_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            findings.extend(scan_source(path.read_text(encoding="utf-8"), str(path)))
        except OSError as exc:
            print(f"跳过 {path}: {exc}", file=sys.stderr)
    return findings


def _relative(name: str) -> str:
    try:
        return str(Path(name).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return name


def main() -> int:
    parser = argparse.ArgumentParser(description="测试判定表体检（只报告，不改动）")
    parser.add_argument("paths", nargs="*", help="要扫的测试文件，默认 tests/ 全部")
    parser.add_argument("--stat", action="store_true", help="只出分类计数")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] or sorted((ROOT / "tests").glob("test_*.py"))
    findings = scan_paths(targets)

    if args.stat:
        for category in CATEGORIES:
            print(f"{category}: {sum(1 for f in findings if f.category == category)}")
        print(f"合计: {len(findings)}（扫了 {len(targets)} 个文件）")
        return 0

    print(f"测试判定表体检 —— {len(targets)} 个文件，命中 {len(findings)} 条（只报告，不改动）\n")
    for category in CATEGORIES:
        hits = [f for f in findings if f.category == category]
        if not hits:
            continue
        print(f"## {category}（{len(hits)}）")
        for hit in hits:
            print(f"  {_relative(hit.file)}:{hit.line}  {hit.snippet[:100]}")
        print()
    print("判据是启发式的，会有误报；逐条按 CLAUDE.md「测试判定表」判断，不要机械全删。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

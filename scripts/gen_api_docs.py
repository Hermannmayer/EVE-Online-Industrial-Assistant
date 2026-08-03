"""
gen_api_docs.py — 函数级 API 文档自动生成。

用 Python `ast` 遍历指定目录下的模块，提取每个 class / def / async def 的
「签名 + docstring + 所在行号」，输出 markdown 到 `docs/api/<模块路径>.md`。
无 docstring 的函数标注 ⚠️ 待补 docstring（倒逼补文档）。

覆盖范围（分级）：
  - 一级（全函数）：`core/`、`services/`
  - 二级（模块级概览 + 全函数）：`ui_pyside6/models/`、`ui_pyside6/workers/`
  - `ui_pyside6/views/` 不逐文件生成，在 dev/api-reference.md 手动列模块概览

用法：
    python scripts/gen_api_docs.py            # 生成/更新
    python scripts/gen_api_docs.py --check    # 只检查文档是否过期（docs.yml 用）

CI（docs.yml）在构建文档站前运行本脚本，保证 API 页与代码同步。
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# ── 路径 ──
ROOT = Path(__file__).resolve().parent.parent

# 兼容 Windows GBK 控制台：无法编码的字符（emoji 等）用 ? 替换
# （TextIO.reconfigure 为 Python 3.7+ 运行时存在但 typeshed 未收录）
sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
SRC_DIRS: tuple[Path, ...] = (
    ROOT / "core",
    ROOT / "services",
    ROOT / "ui_pyside6" / "models",
    ROOT / "ui_pyside6" / "workers",
)
OUT_DIR = ROOT / "docs" / "api"

# 跳过这些内部/生成文件
SKIP_FILES = {"__pycache__"}


@dataclass(frozen=True)
class Func:
    name: str
    kind: str  # 'def' | 'async def' | 'method'
    args: str  # 参数列表（不含 def 名）
    returns: str | None
    doc: str | None
    lineno: int


@dataclass(frozen=True)
class Class:
    name: str
    bases: str
    doc: str | None
    lineno: int
    methods: tuple[Func, ...]


@dataclass(frozen=True)
class Module:
    rel_path: Path  # 相对项目根，如 core/eve_formulas.py
    doc: str | None
    funcs: tuple[Func, ...]
    classes: tuple[Class, ...]


def _parse_func(node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> Func:
    args = ast.unparse(node.args)
    returns = ast.unparse(node.returns) if node.returns else None
    return Func(
        name=node.name,
        kind="async def" if kind == "async def" else "def",
        args=args,
        returns=returns,
        doc=ast.get_docstring(node),
        lineno=node.lineno,
    )


def _parse_class(node: ast.ClassDef) -> Class:
    bases = ", ".join(ast.unparse(b) for b in node.bases) if node.bases else ""
    methods: list[Func] = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
            methods.append(_parse_func(item, kind))
    return Class(
        name=node.name,
        bases=bases,
        doc=ast.get_docstring(node),
        lineno=node.lineno,
        methods=tuple(methods),
    )


def _parse_module(path: Path, rel: Path) -> Module:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs: list[Func] = []
    classes: list[Class] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            funcs.append(_parse_func(node, kind))
        elif isinstance(node, ast.ClassDef):
            classes.append(_parse_class(node))
    return Module(rel_path=rel, doc=ast.get_docstring(tree), funcs=tuple(funcs), classes=tuple(classes))


def _doc_first_paragraph(doc: str | None) -> str:
    """取 docstring 第一段（到第一个空行），并转义 markdown 特殊字符。"""
    if not doc:
        return ""
    text = doc.strip().split("\n\n")[0].strip()
    # 转义花括号：VitePress 的 markdown-it-attrs 会把 {..} 解析为 HTML 属性
    # （如 { "items": bool } 会导致 Vue 编译报 Duplicate attribute）
    return text.replace("{", "&#123;").replace("}", "&#125;")


def _render_func(f: Func) -> str:
    sig = f"{f.kind} {f.name}({f.args})"
    if f.returns:
        sig += f" -> {f.returns}"
    parts = [f"### `{f.name}`", "", "```python", sig, "```"]
    if f.doc:
        parts += ["", _doc_first_paragraph(f.doc)]
    else:
        parts += ["", "::: warning ⚠️ 待补 docstring", "此函数暂无 docstring，欢迎补充。", ":::"]
    parts += ["", f"定义行：`{f.lineno}`"]
    return "\n".join(parts)


def _render_class(c: Class) -> str:
    head = f"### `class {c.name}`"
    if c.bases:
        head += f"（继承 `{c.bases}`）"
    parts = [head]
    if c.doc:
        parts += ["", _doc_first_paragraph(c.doc)]
    else:
        parts += ["", "::: warning ⚠️ 待补 docstring", "此类暂无 docstring，欢迎补充。", ":::"]
    parts += ["", f"定义行：`{c.lineno}`"]
    if c.methods:
        parts += ["", "#### 方法", ""]
        for m in c.methods:
            parts.append(_render_func(m).replace("### ", "##### "))
    return "\n".join(parts)


def _render_module(m: Module) -> str:
    dotted = ".".join(m.rel_path.with_suffix("").parts)
    parts = [
        f"# {dotted}",
        "",
        f"> 源文件 `{m.rel_path.as_posix()}` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改",
        "",
    ]
    if m.doc:
        parts += ["> 模块说明：", "", _doc_first_paragraph(m.doc), ""]

    if m.funcs:
        parts += ["## 函数", ""]
        for f in m.funcs:
            parts.append(_render_func(f))
            parts.append("")
    if m.classes:
        parts += ["## 类", ""]
        for c in m.classes:
            parts.append(_render_class(c))
            parts.append("")
    if not m.funcs and not m.classes:
        parts += ["_（此模块无可公开的类或函数）_", ""]
    return "\n".join(parts).rstrip() + "\n"


def _iter_py_files(src_dir: Path) -> Iterable[Path]:
    for path in sorted(src_dir.rglob("*.py")):
        if any(part in SKIP_FILES for part in path.parts):
            continue
        yield path


def main() -> int:
    check_only = "--check" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for src_dir in SRC_DIRS:
        if not src_dir.exists():
            continue
        for path in _iter_py_files(src_dir):
            rel = path.relative_to(ROOT)
            out_path = OUT_DIR / rel.with_suffix(".md")
            module = _parse_module(path, rel)
            rendered = _render_module(module)

            if check_only:
                if not out_path.exists() or out_path.read_text(encoding="utf-8") != rendered:
                    print(f"⚠️ 文档过期: {out_path.as_posix()}")
                    return 1
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding="utf-8")
            generated.append(out_path)

    if not check_only:
        # 清理已删除模块的过期文档
        keep = {p.resolve() for p in OUT_DIR.rglob("*.md") if p.name != "_index.md"}
        fresh = {p.resolve() for p in generated}
        for stale in keep - fresh:
            stale.unlink()
        print(f"✅ 已生成 {len(generated)} 个 API 文档页 → {OUT_DIR.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

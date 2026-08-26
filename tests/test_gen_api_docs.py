"""scripts/gen_api_docs.py 渲染行为 smoke 测试

专注新渲染规则：模块/类 docstring 全文渲染、__init__.py 豁免缺 docstring 警告、
花括号转义，函数 docstring 保持第一段。
"""

from pathlib import Path

import pytest

from scripts.gen_api_docs import (
    Class,
    Func,
    Module,
    _doc_first_paragraph,
    _escape_markdown,
    _render_class,
    _render_module,
)

pytestmark = pytest.mark.fast


def _module(rel: str = "core/foo.py", doc: str | None = None) -> Module:
    return Module(rel_path=Path(rel), doc=doc, funcs=(), classes=())


def _func(doc: str | None = None) -> Func:
    return Func(name="f", kind="def", args="x: int", returns=None, doc=doc, lineno=1)


def _class(doc: str | None = None) -> Class:
    return Class(name="Foo", bases="", doc=doc, lineno=1, methods=())


def test_escape_markdown_braces():
    """花括号被转义为 HTML 实体（防 Vue Duplicate attribute）；其余字符不动。"""
    assert _escape_markdown('{"items": bool}') == '&#123;"items": bool&#125;'
    assert _escape_markdown("name = {0}") == "name = &#123;0&#125;"
    assert _escape_markdown("plain text") == "plain text"


def test_module_docstring_rendered_full():
    """模块 docstring 全文渲染，不只第一段。"""
    out = _render_module(_module(doc="第一段说明\n\n第二段流程说明"))
    assert "第一段说明" in out
    assert "第二段流程说明" in out


def test_first_paragraph_helper_truncates():
    assert _doc_first_paragraph("第一段\n\n第二段") == "第一段"
    assert "第二段" not in _doc_first_paragraph("第一段\n\n第二段")


def test_module_missing_doc_warns_non_init():
    out = _render_module(_module(doc=None))
    assert "待补模块 docstring" in out


def test_module_missing_doc_skips_init():
    out = _render_module(_module(rel="services/__init__.py", doc=None))
    assert "待补模块 docstring" not in out


def test_class_docstring_rendered_full():
    out = _render_class(_class(doc="类说明\n\n类细节"))
    assert "类说明" in out
    assert "类细节" in out


def test_func_docstring_keeps_first_paragraph():
    """函数级仍只取第一段（页面精简）。"""
    out = _render_module(Module(rel_path=Path("core/foo.py"), doc=None, funcs=(_func("首句\n\n次句"),), classes=()))
    assert "首句" in out
    assert "次句" not in out


def test_module_missing_doc_warns_with_guidance():
    out = _render_module(_module(doc=None))
    assert "描述模块功能全貌" in out

"""QML 页面注册表 / 回退机制契约测试。

这是迁移期的安全网：**任何一页 QML 出问题都必须静默回退到原有 Widgets 页面**，
绝不能让整个应用起不来。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui_qml.host import PageHost
from ui_qml.registry import QML_PAGES, build_page

pytestmark = pytest.mark.ui


def _fallback() -> QWidget:
    w = QWidget()
    w.setObjectName("widgets_fallback")
    w.setProperty("via", "widgets")
    return w


@pytest.fixture(autouse=True)
def _restore_registry():
    """每个用例前后还原注册表，避免相互污染。"""
    original = dict(QML_PAGES)
    yield
    QML_PAGES.clear()
    QML_PAGES.update(original)


def test_unregistered_key_uses_fallback(qapp):
    QML_PAGES.clear()
    page = build_page("estimate", _fallback)
    assert isinstance(page, QWidget)
    assert not isinstance(page, PageHost)
    assert page.property("via") == "widgets"


def test_registered_valid_qml_returns_host(qapp):
    QML_PAGES.clear()
    QML_PAGES["estimate"] = "pages/DemoPage.qml"
    page = build_page("estimate", _fallback)
    assert isinstance(page, PageHost)
    assert page.ok(), page.errors()


def test_broken_qml_falls_back_to_widgets(qapp):
    """QML 文件不存在时必须回退，且不抛异常。"""
    QML_PAGES.clear()
    QML_PAGES["estimate"] = "pages/DoesNotExist.qml"
    page = build_page("estimate", _fallback)
    assert not isinstance(page, PageHost)
    assert page.property("via") == "widgets"


def test_syntax_error_qml_falls_back_to_widgets(qapp, tmp_path):
    """QML 语法/组件错误同样回退。"""
    bad = tmp_path / "Bad.qml"
    bad.write_text(
        "import QtQuick\nItem { Rectangle { ThisComponentDoesNotExist {} } }\n",
        encoding="utf-8",
    )
    QML_PAGES.clear()
    QML_PAGES["estimate"] = str(bad)
    page = build_page("estimate", _fallback)
    assert not isinstance(page, PageHost)
    assert page.property("via") == "widgets"


def test_host_injects_theme_context(qapp):
    """QML 页面必须能直接拿到 Theme 单例（context property 名固定为 Theme）。"""
    QML_PAGES.clear()
    QML_PAGES["estimate"] = "pages/DemoPage.qml"
    page = build_page("estimate", _fallback)
    assert isinstance(page, PageHost)
    ctx = page.rootContext().contextProperty("Theme")
    assert ctx is not None, "Theme 未注入，所有 QML 页面的 Theme.* 都会静默失效"
    assert ctx.radius > 0


def test_fallback_returns_usable_widget(qapp):
    """回退路径返回的控件可正常使用。"""
    QML_PAGES.clear()
    page = build_page("unknown", _fallback)
    assert isinstance(page, QWidget)
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("ok"))
    assert page.findChild(QLabel) is not None


class _FakeShell:
    """满足 ShellHost 协议的最小替身。"""

    def __init__(self) -> None:
        self.status = ""

    def set_status(self, text: str) -> None:
        self.status = text

    def show_progress(self, text: str = "", maximum: int = 0) -> None: ...
    def update_progress(self, value: int, text: str = "") -> None: ...
    def hide_progress(self, text: str = "就绪") -> None: ...


def test_shell_bridge_injected_and_stays_alive(qapp):
    """`shell` 必须注入**且**由宿主持有强引用。

    QML 的 context 不接管所有权：只传临时对象的话会被 GC 回收，
    表现为 `contextProperty("shell")` 查不到（静默失效，页面调用全无反应）。
    """
    QML_PAGES.clear()
    QML_PAGES["estimate"] = "pages/DemoPage.qml"
    shell = _FakeShell()
    page = build_page("estimate", _fallback, shell=shell)
    assert isinstance(page, PageHost)

    bridge = page.rootContext().contextProperty("shell")
    assert bridge is not None, "shell 未注入 QML 上下文"
    bridge.setStatus("hello")
    assert shell.status == "hello", "桥已失效（多半被 GC 回收）"

"""QML 页面注册表契约测试。

批次 7.4 退役了「QML 失败就静默回退 Widgets 页」的脚手架：`build_page` 与它的
`fallback_factory` 一起删了（6.2 换了 QML 外壳后没有生产调用方）。外壳只走
`build_page_spec` + `build_qml_page`：**未登记或加载失败的页就是本页暂缺**（外壳记一条
告警），不再有第二套 Widgets 实现可回。

这里守注册表剩下这几条不变量：未登记返回 None、登记了就能给出规格、桥/外壳按约定注入、
`build_qml_page` 在缺页时返回 None 而不抛。
"""

from __future__ import annotations

import pytest
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickItem

from ui_qml.bridge import CONTEXT_NAME, theme_singleton
from ui_qml.registry import QML_BRIDGES, QML_PAGES, build_page_spec, build_qml_page

pytestmark = pytest.mark.ui


class _FakeShell:
    """满足 ShellHost 协议的最小替身。"""

    def __init__(self) -> None:
        self.status = ""

    def set_status(self, text: str) -> None:
        self.status = text

    def show_progress(self, text: str = "", maximum: int = 0) -> None: ...
    def update_progress(self, value: int, text: str = "") -> None: ...
    def hide_progress(self, text: str = "就绪") -> None: ...


@pytest.fixture(autouse=True)
def _restore_registry():
    """每个用例前后还原注册表，避免相互污染。"""
    original_pages = dict(QML_PAGES)
    original_bridges = dict(QML_BRIDGES)
    yield
    QML_PAGES.clear()
    QML_PAGES.update(original_pages)
    QML_BRIDGES.clear()
    QML_BRIDGES.update(original_bridges)


def _register_demo() -> None:
    QML_PAGES.clear()
    QML_BRIDGES.clear()
    QML_PAGES["estimate"] = "pages/DemoPage.qml"


def _engine_with_theme() -> QQmlEngine:
    """照外壳的做法给根 context 挂 Theme 单例（QML 页面靠它取色/字号）。"""
    engine = QQmlEngine()
    engine.rootContext().setContextProperty(CONTEXT_NAME, theme_singleton())
    return engine


# ── 1. build_page_spec（不碰宿主）──────────────────────────


def test_unregistered_key_returns_none(qapp):
    QML_PAGES.clear()
    QML_BRIDGES.clear()
    assert build_page_spec("estimate", None) is None


def test_registered_key_returns_spec(qapp):
    _register_demo()
    spec = build_page_spec("estimate", None)
    assert spec is not None
    assert spec.qml_file == "pages/DemoPage.qml"
    assert spec.hooks is None, "没有 bridge 的纯展示页不该塞一个空钩子"


def test_shell_bridge_is_injected_and_stays_alive(qapp):
    """`shell` 必须注入**且**由规格的 context 持有强引用。

    QML 的 context 不接管所有权：只传临时对象的话会被 GC 回收，
    表现为 `contextProperty("shell")` 查不到（静默失效，页面调用全无反应）。
    """
    _register_demo()
    shell = _FakeShell()
    spec = build_page_spec("estimate", shell)
    assert spec is not None
    bridge = spec.context.get("shell")
    assert bridge is not None, "shell 未注入规格上下文"
    bridge.setStatus("hello")
    assert shell.status == "hello", "桥已失效（多半被 GC 回收）"


def test_factory_exception_returns_none(qapp, monkeypatch):
    """页工厂抛异常不该把整个应用带崩 —— 外壳按 None 处理（本页暂缺）。"""
    from ui_qml.registry import QML_PAGE_FACTORIES

    def _boom(shell):
        raise RuntimeError("工厂炸了")

    monkeypatch.setitem(QML_PAGE_FACTORIES, "estimate", _boom)
    assert build_page_spec("estimate", None) is None


# ── 2. build_qml_page（外壳的真实入口）─────────────────────


def test_build_qml_page_returns_none_for_unregistered_key(qapp):
    QML_PAGES.clear()
    QML_BRIDGES.clear()
    assert build_qml_page("estimate", None, _engine_with_theme(), QQuickItem()) is None


def test_build_qml_page_returns_none_for_a_missing_file(qapp):
    """QML 文件不存在时返回 None（不抛）—— 外壳据此把本页记为暂缺。"""
    _register_demo()
    QML_PAGES["estimate"] = "pages/DoesNotExist.qml"
    assert build_qml_page("estimate", None, _engine_with_theme(), QQuickItem()) is None


def test_build_qml_page_instantiates_and_parents_the_item(qapp):
    _register_demo()
    root = QQuickItem()
    page = build_qml_page("estimate", None, _engine_with_theme(), root)
    assert page is not None, "登记的整页 QML 应当能实例化"
    assert isinstance(page.item, QQuickItem)
    assert page.item.parentItem() is root, "页面 Item 没挂进外壳的场景"

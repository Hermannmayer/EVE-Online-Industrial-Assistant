"""工业页整页 QML 外壳（阶段 5 / 批次 5）契约测试。

工业页从「Widgets 外壳 + 内嵌 PageHost」变成「整页 QML」：`content_stack` 里的子控件
本身就是 QML 宿主，业务仍只有 `IndustryPage` 一份实现。本文件守三件事：

1. **注册表能构造出 industry 页** —— `build_page` 走页工厂返回整页 QML 宿主；工厂失效时
   仍回退到 Widgets 版（迁移期的安全网）。
2. **宿主挂得住控制器与两个桥** —— context property `bridge` / `planTableBridge` 都在，
   且就是控制器的那两个对象（少一个，页面就是点不动的死图）。
3. **宿主透传外壳的鸭子类型钩子** —— `save_state` / `restore_state` / `refresh_display` /
   `update_status_bar` / `showEvent`。透传漏一个，「切页刷新状态栏」「退出保存滚动位置」
   就会在注册表路径上静默失效（`main_window` 只按方法名 `hasattr` 探测）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from ui_qml.host import PageHost
from ui_qml.industry_page import IndustryQmlHost, build_industry_page
from ui_qml.registry import QML_PAGE_FACTORIES, build_page, register_migrated_pages

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _registered():
    """确保页工厂已登记（`main_window_nav` 在真实启动时也会调它）。"""
    register_migrated_pages()


def _fallback() -> QWidget:
    w = QWidget()
    w.setObjectName("widgets_fallback")
    w.setProperty("via", "widgets")
    return w


# ── 1. 注册表 ─────────────────────────────────────────────


def test_registry_builds_full_qml_host(main_window):
    """注册表为 industry 交出的是**裸 QML 宿主**（不再是 Widgets 包装层）。"""
    page = build_page("industry", _fallback, shell=main_window)
    try:
        assert isinstance(page, PageHost), "industry 没有走 QML 页工厂"
        assert page.ok(), "; ".join(str(e) for e in page.errors())
        assert page.objectName() == "industry_page_qml"
        # 外壳的鸭子类型钩子必须还在，否则主窗口的切页/退出逻辑会静默失效
        for hook in ("save_state", "restore_state", "refresh_display", "update_status_bar"):
            assert hasattr(page, hook), f"宿主缺钩子 {hook}"
    finally:
        page.deleteLater()


def test_registry_factory_empty_falls_back(main_window, monkeypatch):
    """页工厂返回空（QML 加载失败）时必须静默回退 Widgets 版。"""
    monkeypatch.setitem(QML_PAGE_FACTORIES, "industry", lambda shell, parent=None: None)
    page = build_page("industry", _fallback, shell=main_window)
    try:
        assert not isinstance(page, PageHost)
        assert page.property("via") == "widgets"
    finally:
        page.deleteLater()


def test_registry_factory_exception_falls_back(main_window, monkeypatch):
    """页工厂抛异常同样回退，不把整个应用带崩。"""

    def _boom(shell, parent=None):
        raise RuntimeError("工厂炸了")

    monkeypatch.setitem(QML_PAGE_FACTORIES, "industry", _boom)
    page = build_page("industry", _fallback, shell=main_window)
    try:
        assert not isinstance(page, PageHost)
        assert page.property("via") == "widgets"
    finally:
        page.deleteLater()


def test_shell_holds_the_industry_page_as_a_qml_item(main_window):
    """真实启动路径拿到的工业页是**外壳里的一个 QML Item**（批次 6.1 起的外壳形态）。

    外壳换成 `QQuickWindow` 之后页面不再可能是 `QQuickWidget`（装不进去），
    所以这里断言的是 `QmlPage` + `QQuickItem`；`PageHost` 那条路只剩对话框在用。
    """
    from PySide6.QtQuick import QQuickItem

    from ui_qml.registry import QmlPage

    page = main_window._pages["industry"]
    assert isinstance(page, QmlPage), f"导航页是 {type(page).__name__}，不是 QmlPage"
    assert isinstance(page.item, QQuickItem), "工业页不是 QML Item"
    assert callable(getattr(page.hooks, "load_plans", None)), "钩子没接到控制器上"


# ── 2. 宿主 / 桥 ───────────────────────────────────────────


def test_factory_returns_controller_owned_host(main_window):
    """工厂造的宿主持有控制器，且**只有这一个宿主**（控制器以 headless 构造）。

    批次 6.1 起控制器不再自建宿主：宿主由外壳类型决定
    （Widgets → `IndustryQmlHost`，QML → `Item`），所以 `controller.host` 是 None。
    """
    host = build_industry_page(main_window)
    assert host is not None
    try:
        assert host._controller.host is None, "控制器不该再自建宿主（否则又变成两个）"
        assert host.parent() is host._controller, "宿主挂在控制器上，生命周期跟着它"
    finally:
        host.deleteLater()


def test_host_injects_both_context_properties(main_window):
    """两个 context property 都要在，且就是控制器的那两个桥。

    只注入 `bridge` 的形态（`QML_BRIDGES`）覆盖不了工业页：`PlanTablePane.qml`
    靠 `planTableBridge` 取数，缺它整张计划表静默空白。
    """
    host = build_industry_page(main_window)
    assert host is not None
    try:
        controller = host._controller
        ctx = host.rootContext()
        assert ctx.contextProperty("bridge") is controller.bridge
        # 计划表桥必须来自 headless 控制器（不是另建的）
        assert ctx.contextProperty("planTableBridge") is controller.plan_table.bridge
        assert ctx.contextProperty("planTableBridge") is controller.plan_table_bridge
    finally:
        host.deleteLater()


def test_page_keeps_its_own_host(main_window):
    """`IndustryPage(main_window)` 仍是完整页面（注册表失败时的 Widgets 回退走这条）。"""
    from ui_pyside6.views.industry_view import IndustryPage

    page = IndustryPage(main_window)
    try:
        assert isinstance(page._host, IndustryQmlHost)
        assert page._host.ok(), "IndustryPage.qml 加载失败"
        assert page.bridge is page._bridge
        assert page.plan_table_bridge is page._plan_table_widget.bridge
    finally:
        page.deleteLater()


# ── 3. 钩子透传 ────────────────────────────────────────────


def test_host_forwards_state_hooks(main_window):
    """`save_state` / `restore_state` / 两个刷新钩子必须落到控制器上。"""
    host = build_industry_page(main_window)
    assert host is not None
    try:
        controller = host._controller
        with (
            patch.object(controller, "save_state", return_value={"v_scroll": 0.0}) as p_save,
            patch.object(controller, "restore_state") as p_restore,
            patch.object(controller, "refresh_display") as p_refresh,
            patch.object(controller, "update_status_bar") as p_status,
        ):
            assert host.save_state() == {"v_scroll": 0.0}
            host.refresh_display()
            host.update_status_bar()
            host.restore_state({"v_scroll": 42.0})

        p_save.assert_called_once_with()
        p_restore.assert_called_once_with({"v_scroll": 42.0})
        p_refresh.assert_called_once_with()
        p_status.assert_called_once_with()
    finally:
        host.deleteLater()


def test_host_show_event_syncs_price_settings(main_window):
    """宿主被切到前台 → 控制器的「重新可见」同步必须走一遍。

    注册表路径下控制器不在 `content_stack` 里，Qt 不会调它的 `showEvent`；
    少这条转发，从仓库页改完材料倍率回到工业页，工具栏旋钮会停在旧值。
    """
    host = build_industry_page(main_window)
    assert host is not None
    try:
        controller = host._controller
        with patch.object(controller, "on_shown") as p_shown:
            host.showEvent(QShowEvent())
        p_shown.assert_called_once_with()
    finally:
        host.deleteLater()

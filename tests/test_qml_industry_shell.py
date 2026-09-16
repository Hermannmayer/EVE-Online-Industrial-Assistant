"""工业页整页 QML 契约测试（阶段 5 / 批次 5；批次 7.4 退役了 Widgets 回退宿主）。

工业页是「整页 QML，但业务留在控制器 `IndustryPage` 里」的那一页。本文件守：

1. **页工厂给出组装规格** —— `build_industry_spec` 造控制器、返回 `PageSpec`（不碰宿主）。
2. **规格挂得住控制器与两个桥** —— context property `bridge` / `planTableBridge` 都在，
   且就是控制器的那两个对象（少一个，页面就是点不动的死图）。
3. **外壳里的工业页是 QML `Item`，钩子接到控制器上**（外壳按方法名 `getattr` 探测）。

批次 7.4 删掉了 Widgets 回退脚手架的整条宿主路径：`build_page`（注册表回退入口）、
`build_industry_page`（Widgets 外壳页工厂）、`IndustryQmlHost` / `make_qml_host`
（把控制器包成 QWidget 的宿主）—— 控制器基类已改成 `QObject`，不再自建宿主，
对应用例一并删除。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QWidget

from ui_qml.industry_page import INDUSTRY_QML, build_industry_spec
from ui_qml.registry import QML_PAGE_FACTORIES, QmlPage, register_migrated_pages

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _registered():
    """确保页工厂已登记（外壳在真实启动时也会调它）。"""
    register_migrated_pages()


# ── 1. 页工厂 / 组装规格 ───────────────────────────────────


def test_factory_is_registered_for_the_shell():
    """QML 外壳按 key 取页工厂 —— 登记丢了整页就静默暂缺。"""
    assert QML_PAGE_FACTORIES.get("industry") is build_industry_spec


def test_spec_carries_both_context_properties(main_window):
    """两个 context property 都要在，且就是控制器的那两个桥。

    只注入 `bridge` 的形态（`QML_BRIDGES`）覆盖不了工业页：`PlanTablePane.qml`
    靠 `planTableBridge` 取数，缺它整张计划表静默空白。
    """
    spec = build_industry_spec(main_window)
    assert spec.qml_file == INDUSTRY_QML
    assert spec.object_name == "industry_page_qml"
    assert set(spec.context) == {"bridge", "planTableBridge"}
    assert spec.context["bridge"] is spec.hooks.bridge
    assert spec.context["planTableBridge"] is spec.hooks.plan_table_bridge


def test_controller_is_a_plain_qobject(main_window):
    """批次 7.4 起控制器基类是 `QObject`（不再是 QWidget）—— QML 外壳只要桥与钩子。"""
    spec = build_industry_spec(main_window)
    assert isinstance(spec.hooks, QObject)
    assert not isinstance(spec.hooks, QWidget), "控制器还是 QWidget，7.4 没去干净"


# ── 2. 外壳里的工业页（真实启动路径）───────────────────────


def test_shell_holds_the_industry_page_as_a_qml_item(main_window):
    """真实启动路径拿到的工业页是**外壳里的一个 QML Item**（批次 6.1 起的外壳形态）。

    外壳换成 `QQuickWindow` 之后页面不再可能是 `QQuickWidget`（装不进去），
    所以这里断言的是 `QmlPage` + `QQuickItem`。
    """
    page = main_window._pages["industry"]
    assert isinstance(page, QmlPage), f"导航页是 {type(page).__name__}，不是 QmlPage"
    assert isinstance(page.item, QQuickItem), "工业页不是 QML Item"
    assert callable(getattr(page.hooks, "load_plans", None)), "钩子没接到控制器上"


def test_controller_exposes_the_shell_hooks(main_window):
    """外壳按方法名 `getattr` 探测页面能力 —— 少一个就是**静默失效**。"""
    hooks = main_window._pages["industry"].hooks
    for name in ("save_state", "restore_state", "refresh_display", "update_status_bar", "on_shown"):
        assert callable(getattr(hooks, name, None)), f"控制器缺钩子 {name}"

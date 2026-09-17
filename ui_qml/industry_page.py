"""工业页的 QML 组装规格（阶段 5 / 批次 5；批次 7.4 退役了 Widgets 回退宿主）。

工业页是唯一「整页 QML，但业务留在控制器 `IndustryPage` 里」的页面，所以它需要一个
页工厂而不是 `QML_BRIDGES` 的单 bridge 形态：控制器 + **两个** context property
（`bridge` = 页面骨架桥，`planTableBridge` = 计划表桥），业务在控制器里，桥只做转发
（与 `PlanTable` / `ProductionLauncher` 阶段 2/2c 定下的终态一致）。

- `industry_spec(controller)` —— 组装规格：两个 context property + 控制器作为钩子实现者。
- `build_industry_spec(shell)` —— `ui_qml.registry.QML_PAGE_FACTORIES` 的页工厂：
  造控制器，返回规格 —— **不碰宿主**。

批次 7.4 删掉了「把控制器包成 QWidget 的 `SpecPageHost`」那条路
（`IndustryQmlHost` / `make_qml_host` / `build_industry_page`）：控制器基类已改成
`QObject`（见 `ui_pyside6/views/industry_view.py`），不再有任何自建 QML 宿主的路径 ——
宿主形态完全由外壳决定（`ui_qml.registry.build_qml_page` 把规格实例化成 `Item`）。

外壳按鸭子类型调用的钩子（`save_state` / `restore_state` / `refresh_display` /
`update_status_bar` / `on_shown`）由控制器**自己实现**，外壳按名 `getattr` 探测
（见 `ui_qml/shell_window.py`）。少一个，「切页刷新状态栏」「退出保存滚动位置」
「切回工业页同步价格设置」就会静默失效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ui_qml.registry import PageSpec

if TYPE_CHECKING:
    from ui_qml.views.industry_view import IndustryPage

__all__ = [
    "INDUSTRY_QML",
    "build_industry_spec",
    "industry_spec",
]

#: QML 页面路径（相对 ui_qml/qml/）
INDUSTRY_QML = "pages/IndustryPage.qml"


def industry_spec(controller: IndustryPage) -> PageSpec:
    """工业页的组装规格：两个 context property + 控制器作为钩子实现者。"""
    return PageSpec(
        INDUSTRY_QML,
        {"bridge": controller.bridge, "planTableBridge": controller.plan_table_bridge},
        object_name="industry_page_qml",
        hooks=controller,
    )


def build_industry_spec(shell: Any) -> PageSpec:
    """注册表页工厂：造控制器，返回组装规格 —— **不碰宿主**。

    QML 外壳把规格实例化成 `Item`（`build_qml_page`），控制器只提供两个桥与钩子实现。
    """
    from ui_qml.views.industry_view import IndustryPage

    return industry_spec(IndustryPage(shell))

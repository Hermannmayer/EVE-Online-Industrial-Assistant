"""工业页整页 QML 宿主（阶段 5 / 批次 5）。

工业页此前是「Widgets 外壳 + 内嵌 PageHost」：`IndustryPage`（Widgets 页）在自己的
布局里放一个 `PageHost` 载 `IndustryPage.qml`。本模块把这段 **QML 组装** 从 Widgets 层
挪到 QML 层，并对外给出注册表要的页工厂：

- `make_qml_host(controller)` —— 造一个挂了**两个** context property 的宿主
  （`bridge` = 页面骨架桥，`planTableBridge` = 计划表桥）。控制器构造时调用它，
  因此 `IndustryPage(main_window)` 仍是**完整可用**的 Widgets 回退页。
- `build_industry_page(shell)` —— `ui_qml.registry` 的页工厂：造控制器，返回**裸宿主**。
  于是 `content_stack` 的子控件就是 QML 表面本身，不再是 Widgets 包装层。

**为什么 industry 需要页工厂而不是 `QML_BRIDGES`**：`build_page` 的单 bridge 形态
只能注入一个 `bridge`，而工业页是「控制器 + 两个桥」——业务在控制器里，桥只是转发
（与 `PlanTable` / `ProductionLauncher` 阶段 2/2c 定下的终态一致）。

外壳按鸭子类型调用的页面钩子（`save_state` / `restore_state` / `refresh_display` /
`update_status_bar` / `showEvent`）由宿主**转发**给控制器 —— 业务实现始终只有控制器一份，
缺一个钩子，「切页刷新状态栏」「退出保存滚动位置」就会在注册表路径上静默失效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from core.logger import log
from ui_qml.host import PageHost

if TYPE_CHECKING:
    from ui_pyside6.views.industry_view import IndustryPage

__all__ = ["INDUSTRY_QML", "IndustryQmlHost", "make_qml_host", "build_industry_page"]

#: QML 页面路径（相对 ui_qml/qml/）
INDUSTRY_QML = "pages/IndustryPage.qml"


class IndustryQmlHost(PageHost):
    """工业页整页 QML 宿主。

    **必须**用 Python 强引用持有控制器：注册表路径返回的是这个宿主，控制器不再是
    `content_stack` 的子控件，没有这层引用就会被 GC 回收 —— 桥、模型、后台 worker
    一起没掉，页面变成一张点不动的死图（且不报错）。
    """

    def __init__(self, controller: IndustryPage) -> None:
        # 先落控制器：super().__init__ 里就要拿它取两个桥
        self._controller = controller
        super().__init__(
            INDUSTRY_QML,
            context={
                "bridge": controller.bridge,
                "planTableBridge": controller.plan_table_bridge,
            },
            parent=controller,
        )
        self.setObjectName("industry_page_qml")

    # ── 外壳鸭子类型钩子 → 控制器 ─────────────────────────────
    # `main_window` / `main_window_nav` 只按方法名 `hasattr` 探测页面能力，
    # 宿主不透传，这些行为就静默失效。

    def save_state(self) -> dict:
        return self._controller.save_state()

    def restore_state(self, data: dict) -> None:
        self._controller.restore_state(data)

    def refresh_display(self) -> None:
        self._controller.refresh_display()

    def update_status_bar(self) -> None:
        self._controller.update_status_bar()

    def showEvent(self, event: QShowEvent) -> None:
        """宿主被切到前台 → 让控制器做一次「重新可见」同步（价格设置）。"""
        super().showEvent(event)
        self._controller.on_shown()


def make_qml_host(controller: IndustryPage) -> IndustryQmlHost:
    """给工业页控制器造整页 QML 宿主（工业页唯一的渲染入口）。"""
    return IndustryQmlHost(controller)


def build_industry_page(shell: Any, parent: QWidget | None = None) -> QWidget | None:
    """注册表页工厂：返回工业页的**裸 QML 宿主**；QML 加载失败返回 None。

    返回 None 是契约的一部分：`registry.build_page` 据此回退 Widgets 版
    （`IndustryPage(shell)` 那条路径）。
    """
    from ui_pyside6.views.industry_view import IndustryPage

    controller = IndustryPage(shell)
    host = controller.host
    if not host.ok():
        log.warning("工业页 QML(%s) 加载失败，回退 Widgets 版", INDUSTRY_QML)
        controller.deleteLater()
        return None
    if parent is not None:
        # 交给调用方的父子关系（`content_stack.addWidget` 还会再接管一次）
        host.setParent(parent)
    return host

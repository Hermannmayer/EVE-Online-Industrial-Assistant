"""QML 页面注册表 —— 页面组装规格的登记处。

`QML_PAGES` 把导航 key 映射到 `ui_qml/qml/` 下的 QML 文件，
`QML_BRIDGES` 可选地给该页配一个 bridge 工厂（注入为 QML 的 context property `bridge`）。
`QML_PAGE_FACTORIES` 是给「整页 QML，但业务在 Widgets 控制器里」的页面用的：
工厂自己造控制器与**任意多个** context property，返回 `PageSpec`（见 `build_page_spec`）。

外壳只走 `build_qml_page`：**未登记或加载失败的页就是本页暂缺**（外壳记一条告警），
不再有第二套 Widgets 实现可回 —— 批次 7.4 退役了那条「QML 失败就回退 Widgets 页」
的脚手架（`build_page` + `fallback_factory`）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

from core.logger import log
from ui_qml.bridge import ShellBridge
from ui_qml.host import QML_ROOT

__all__ = [
    "QML_PAGES",
    "QML_BRIDGES",
    "QML_PAGE_FACTORIES",
    "PageSpec",
    "QmlPage",
    "build_page_spec",
    "build_qml_page",
    "register_migrated_pages",
]


@dataclass(frozen=True)
class PageSpec:
    """一个整页 QML 的**组装规格**：QML 文件 + 注入的 context + 钩子实现者。

    外壳 `build_qml_page` 把它实例化成 `Item`（挂进 QML 外壳的场景）。原先
    Widgets 外壳还会把它包成 `PageHost`（QWidget），那条路随 7.4 一起退役了
    —— `QQuickWidget` 装不进 `QQuickWindow`，本来就是硬约束。
    """

    qml_file: str
    context: dict[str, QObject] = field(default_factory=dict)
    #: 页面根 Item 的 objectName（测试/工具按它找页面；空则不设）。原先由
    #: `SpecPageHost` 设在 QWidget 宿主上，7.4 起由 `build_qml_page` 设在 Item 上。
    object_name: str = ""
    #: 鸭子类型钩子（`save_state` / `restore_state` / `refresh_display` / `update_status_bar`）
    #: 的实现者：常规页是桥本身，工业页是它的 Widgets 控制器。
    hooks: Any = None


@dataclass
class QmlPage:
    """QML 外壳里的一页：`Item` + 钩子实现者（页面本身没有 Python 实体）。"""

    key: str
    item: QQuickItem
    hooks: Any = None
    #: 造出这个 Item 的组件。**必须持有**：丢了它，Python 包装析构会连带删掉 C++
    #: 的 `QQmlComponent`，页面上的绑定与连接可能随之失效（现象是「渲染出来了但点不动」）。
    component: QQmlComponent | None = None


# nav key → QML 文件（相对 ui_qml/qml/）。迁移期逐页加入。
QML_PAGES: dict[str, str] = {}

# nav key → 工厂(shell) -> QObject，作为 context property `bridge` 注入。
# 无 bridge 的纯展示页可以不登记。
QML_BRIDGES: dict[str, Callable[[object], QObject]] = {}

# nav key → 页工厂(shell) -> PageSpec | None。
#
# 给「整页 QML 但业务留在 Widgets 控制器里」的页面用（当前只有工业页）。单 bridge
# 的 `QML_BRIDGES` 覆盖不了这种页：工业页需要一个控制器 + 两个 context property
# （`bridge` / `planTableBridge`）。工厂只产出**组装规格**，不碰宿主 ——
# 实例化成 Item 由 `build_qml_page` 做。
QML_PAGE_FACTORIES: dict[str, Callable[[object], PageSpec | None]] = {}


def register_migrated_pages() -> None:
    """登记已迁移到 QML 的页面（每个页面一行，懒导入）。

    懒导入是必要的：`estimate_bridge` 会拉进 workers 与 services，
    在模块级导入会拖慢启动，也会让不碰 UI 的测试被迫加载整条业务链。
    """
    # 每页各自判重：函数整体可重复调用（`main_window_nav` 与测试都会调它）
    if "estimate" not in QML_PAGES:
        from ui_qml.bridge.estimate_bridge import EstimateBridge

        QML_PAGES["estimate"] = "pages/EstimatePage.qml"
        QML_BRIDGES["estimate"] = EstimateBridge  # type: ignore[assignment]

    if "query" not in QML_PAGES:
        from ui_qml.bridge.query_bridge import QueryBridge

        QML_PAGES["query"] = "pages/QueryPage.qml"
        QML_BRIDGES["query"] = QueryBridge  # type: ignore[assignment]

    if "trade" not in QML_PAGES:
        from ui_qml.bridge.trade_bridge import TradeBridge

        QML_PAGES["trade"] = "pages/TradePage.qml"
        QML_BRIDGES["trade"] = TradeBridge  # type: ignore[assignment]

    if "watchlist" not in QML_PAGES:
        from ui_qml.bridge.watchlist_bridge import WatchlistBridge

        QML_PAGES["watchlist"] = "pages/WatchlistPage.qml"
        QML_BRIDGES["watchlist"] = WatchlistBridge  # type: ignore[assignment]

    if "contract" not in QML_PAGES:
        from ui_qml.bridge.contract_bridge import ContractBridge

        QML_PAGES["contract"] = "pages/ContractPage.qml"
        QML_BRIDGES["contract"] = ContractBridge  # type: ignore[assignment]

    if "storage" not in QML_PAGES:
        from ui_qml.bridge.inventory_bridge import InventoryBridge

        QML_PAGES["storage"] = "pages/StoragePage.qml"
        QML_BRIDGES["storage"] = InventoryBridge  # type: ignore[assignment]

    # 工业页：整页 QML，但业务留在 `IndustryPage`（Widgets 控制器）里，
    # 页工厂自己组装控制器 + 两个 context property（`bridge` / `planTableBridge`）。
    if "industry" not in QML_PAGE_FACTORIES:
        from ui_qml.industry_page import build_industry_spec

        QML_PAGE_FACTORIES["industry"] = build_industry_spec


def _spec_for(qml_file: str, key: str, shell: object | None) -> PageSpec:
    """常规 QML 页（单 context）的规格：`bridge` + 可选的 `shell`。"""
    context: dict[str, QObject] = {}
    if shell is not None:
        context["shell"] = ShellBridge(shell)  # type: ignore[arg-type]

    bridge_factory = QML_BRIDGES.get(key)
    if bridge_factory is None:
        return PageSpec(qml_file, context)
    bridge = bridge_factory(shell)
    context["bridge"] = bridge
    return PageSpec(qml_file, context, hooks=bridge)


def build_qml_page(
    key: str,
    shell: object,
    engine: QQmlEngine,
    parent_item: QQuickItem,
) -> QmlPage | None:
    """造 QML 外壳里的页面（`Item`）。找不到登记或加载失败返回 None。

    直接把 `PageSpec` 里的 QML 实例化成一个 `Item` 挂进外壳的场景 ——
    不经 `QQuickWidget`（它是 QWidget，装不进 `QQuickWindow`，这是硬约束）。

    context 走**每页独立的 `QQmlContext`**（挂在外壳的 rootContext 下），
    这样各页的 `bridge` 互不覆盖 —— `PageHost` 靠「一个宿主一个引擎」达到同样效果，
    这里一个引擎多页，必须靠子 context。
    """
    spec = build_page_spec(key, shell)
    if spec is None:
        return None

    from PySide6.QtQml import QQmlContext

    ctx = QQmlContext(engine.rootContext())
    for name, obj in spec.context.items():
        ctx.setContextProperty(name, obj)

    component = QQmlComponent(engine)
    try:
        component.setData(_read_qml(spec.qml_file), QUrl.fromLocalFile(str(QML_ROOT / spec.qml_file)))
    except OSError:
        # 文件缺失/读不出来也要收敛成 None：外壳据此把本页记为暂缺，而不是启动即崩
        # （批次 7.4 删了 Widgets 回退时，旧的 `build_page` 靠 `PageHost` 兜过这条）。
        log.exception("页面 %s 的 QML(%s) 读不出来", key, spec.qml_file)
        return None
    if component.isError():
        log.error(
            "页面 %s 的 QML(%s) 加载失败：%s",
            key,
            spec.qml_file,
            "; ".join(err.toString() for err in component.errors()),
        )
        return None
    item = component.create(ctx)
    if item is None or not isinstance(item, QQuickItem):
        log.error("页面 %s 的 QML(%s) 根元素不是 Item（%r）", key, spec.qml_file, item)
        return None
    if spec.object_name:
        item.setObjectName(spec.object_name)
    item.setParentItem(parent_item)
    return QmlPage(key=key, item=item, hooks=spec.hooks, component=component)


def build_page_spec(key: str, shell: object) -> PageSpec | None:
    """造页面规格，**不碰任何宿主**。未登记返回 None。"""
    factory = QML_PAGE_FACTORIES.get(key)
    if factory is not None:
        try:
            return factory(shell)
        except Exception:
            log.exception("页面 %s 的 QML 页工厂失败", key)
            return None
    qml_file = QML_PAGES.get(key)
    if qml_file is None:
        return None
    try:
        return _spec_for(qml_file, key, shell)
    except Exception:
        log.exception("页面 %s 的 bridge 构造失败", key)
        return None


def _read_qml(qml_file: str) -> bytes:
    return (QML_ROOT / qml_file).read_bytes()

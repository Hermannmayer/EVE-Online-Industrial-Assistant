"""QML 页面注册表 —— 迁移期的逐页开关。

`QML_PAGES` 把导航 key 映射到 `ui_qml/qml/` 下的 QML 文件，
`QML_BRIDGES` 可选地给该页配一个 bridge 工厂（注入为 QML 的 context property `bridge`）。

**未注册的 key 一律走原有 Widgets 页面**，因此迁移可以一页一页来，
任何一页出问题都能通过把这里的登记删掉立即回退。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from core.logger import log
from ui_qml.bridge import ShellBridge
from ui_qml.host import PageHost

__all__ = ["QML_PAGES", "QML_BRIDGES", "build_page", "register_migrated_pages"]

# nav key → QML 文件（相对 ui_qml/qml/）。迁移期逐页加入。
QML_PAGES: dict[str, str] = {}

# nav key → 工厂(shell) -> QObject，作为 context property `bridge` 注入。
# 无 bridge 的纯展示页可以不登记。
QML_BRIDGES: dict[str, Callable[[object], QObject]] = {}


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


def build_page(
    key: str,
    fallback_factory: Callable[[], QWidget],
    shell: object | None = None,
    parent: QWidget | None = None,
) -> QWidget:
    """构建指定导航页：已注册且加载成功则返回 QML 宿主，否则回退 Widgets 版。

    回退是**静默且安全**的——QML 文件写错、缺组件、语法错误、bridge 构造抛异常，
    都只会退回原页面，不会让整个应用起不来。
    """
    qml_file = QML_PAGES.get(key)
    if qml_file is None:
        return fallback_factory()

    context: dict[str, QObject] = {}
    if shell is not None:
        context["shell"] = ShellBridge(shell)  # type: ignore[arg-type]

    bridge_factory = QML_BRIDGES.get(key)
    if bridge_factory is not None:
        try:
            context["bridge"] = bridge_factory(shell)
        except Exception:
            log.exception("页面 %s 的 bridge 构造失败，回退 Widgets 版", key)
            return fallback_factory()

    host = PageHost(qml_file, context=context, parent=parent)
    if host.ok():
        log.debug("页面 %s 使用 QML：%s", key, qml_file)
        return host

    log.warning("页面 %s 的 QML(%s) 加载失败，回退 Widgets 版", key, qml_file)
    host.deleteLater()
    return fallback_factory()

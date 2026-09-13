"""QML 页面注册表 —— 迁移期的逐页开关。

`QML_PAGES` 把导航 key 映射到 `ui_qml/qml/` 下的 QML 文件。
**未注册的 key 一律走原有 Widgets 页面**，因此迁移可以一页一页来，
任何一页出问题都能通过从这里删掉一行立即回退。

阶段 0 时该表为空；阶段 1 起逐个加入（如 `"estimate": "pages/EstimatePage.qml"`）。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from core.logger import log
from ui_qml.bridge import ShellBridge
from ui_qml.host import PageHost

__all__ = ["QML_PAGES", "build_page"]

# nav key → QML 文件（相对 ui_qml/qml/）。迁移期逐页加入。
QML_PAGES: dict[str, str] = {}


def build_page(
    key: str,
    fallback_factory: Callable[[], QWidget],
    shell: object | None = None,
    parent: QWidget | None = None,
) -> QWidget:
    """构建指定导航页：已注册且加载成功则返回 QML 宿主，否则回退 Widgets 版。

    回退是**静默且安全**的——QML 文件写错、缺组件、语法错误都只会退回原页面，
    不会让整个应用起不来。
    """
    qml_file = QML_PAGES.get(key)
    if qml_file is None:
        return fallback_factory()

    context: dict[str, QObject] = {}
    if shell is not None:
        context["shell"] = ShellBridge(shell)  # type: ignore[arg-type]

    host = PageHost(qml_file, context=context, parent=parent)
    if host.ok():
        log.debug("页面 %s 使用 QML：%s", key, qml_file)
        return host

    log.warning("页面 %s 的 QML(%s) 加载失败，回退 Widgets 版", key, qml_file)
    host.deleteLater()
    return fallback_factory()

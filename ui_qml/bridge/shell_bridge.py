"""外壳桥 —— QML 页面访问 QML 外壳的通道（状态栏 / 导航）。

QML 页只需要两种外壳能力：往状态栏写一行字、按 key 切页。进度条三个槽
（`showProgress` / `updateProgress` / `hideProgress`）原先服务 Widgets 版进度条，
QML 迁移后**没有任何 QML 调用方**，已随死槽清理删除。

DWM 毛玻璃由外壳自己的 `_apply_window_backdrop()` 负责，QML 页无需关心——
同一个 HWND，窗口级 Mica/Acrylic 天生生效。
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, Slot

__all__ = ["ShellBridge", "ShellHost"]


class ShellHost(Protocol):
    """外壳需要提供的最小接口（由 `ui_qml.shell_window.ShellWindow` 满足）。"""

    def set_status(self, text: str) -> None: ...
    def show_progress(self, text: str = "", maximum: int = 0) -> None: ...
    def update_progress(self, value: int, text: str = "") -> None: ...
    def hide_progress(self, text: str = "就绪") -> None: ...
    def navigate_to(self, key: str) -> bool: ...


class ShellBridge(QObject):
    """把外壳的状态栏/导航暴露给 QML。"""

    def __init__(self, shell: ShellHost, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

    @Slot(str)
    def setStatus(self, text: str) -> None:
        self._shell.set_status(text)

    @Slot(str)
    def navigate(self, key: str) -> bool:
        """切到某个导航页（找不到返回 false）。"""
        return bool(self._shell.navigate_to(key))

"""外壳桥 —— QML 页面访问 Widgets 外壳的通道（状态栏 / 进度条 / DWM 重放）。

迁移期（阶段 0–4）外壳仍是 Widgets，QML 页面需要一种受控方式去更新状态栏与进度条。
本桥只暴露外壳的公开 API，不直接引用私有控件。

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
    """把外壳的状态栏/进度条/导航暴露给 QML。"""

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

    @Slot(str, int)
    def showProgress(self, text: str = "", maximum: int = 0) -> None:
        self._shell.show_progress(text, maximum)

    @Slot(int, str)
    def updateProgress(self, value: int, text: str = "") -> None:
        self._shell.update_progress(value, text)

    @Slot(str)
    def hideProgress(self, text: str = "就绪") -> None:
        self._shell.hide_progress(text)

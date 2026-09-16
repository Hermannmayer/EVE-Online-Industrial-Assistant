"""窗口置顶工具 — Windows SetWindowPos + WindowStaysOnTopHint 回退。

供主窗口、QML 外壳与产线启动小助手等工具窗共用（抽出自 main_window._apply_pin）。

两种窗口都要吃：Widgets 的 `QWidget` 与 QML 外壳的 `QWindow`。Windows 路径
（SetWindowPos）对二者完全一样；非 Windows 的回退分支要分开 —— `QWidget` 是
`setWindowFlags`，`QWindow` 是 `setFlags`。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget

# 防重入标记（setWindowFlags→show→showEvent 递归）；按窗口 id 记
_PINNING: dict[int, bool] = {}


def reassert_pin(window: QWidget | QWindow | None, pinned: bool) -> None:
    """窗口显示 / 前置时**重申**置顶（幂等；`pinned` 为假或窗口还没建时什么都不做）。

    为什么不能只在构造与勾选时各设一次：

    - `apply_window_pin` 在**构造时**就先跑过一次，那一刻窗口还没显示；SetWindowPos
      作用在一个随后会被 Qt 重新定位、显示的平台窗口上。
    - `QWindow.raise_()` 在 Windows 上是 `SetWindowPos(HWND_TOP)` —— 一个**不带**
      `HWND_TOPMOST` 的插入位置，对已置顶的窗口属于「换了个插入位置去摆它」。

    这两处都可能让置顶在用户真正看到窗口之前丢掉，表现就是「勾着置顶却没置顶，
    再点一次才好」。重申一次只是一次 Win32 调用，代价可忽略，换来的是
    「只要窗口可见，置顶状态一定与勾选一致」。
    """
    if pinned and window is not None:
        apply_window_pin(window, True)


def apply_window_pin(window: QWidget | QWindow, checked: bool) -> None:
    """把窗口置顶/取消置顶。

    Windows 走 SetWindowPos(HWND_TOPMOST/HWND_NOTOPMOST)，不重建窗口不闪烁；
    失败回退 WindowStaysOnTopHint（设置 flag 后需重新 show()）。
    """
    if _PINNING.get(id(window)):
        return  # 防重入
    _PINNING[id(window)] = True
    try:
        if os.name == "nt":
            try:
                import ctypes
                import ctypes.wintypes

                hwnd = int(window.winId())
                SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
                HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
                swp = ctypes.windll.user32.SetWindowPos
                swp.argtypes = [
                    ctypes.wintypes.HWND,
                    ctypes.wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_uint,
                ]
                swp(hwnd, HWND_TOPMOST if checked else HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                return
            except Exception:
                from core.logger import log

                log.exception("SetWindowPos 置顶失败，回退 WindowStaysOnTopHint")
        hint = Qt.WindowType.WindowStaysOnTopHint
        if isinstance(window, QWidget):
            flags = window.windowFlags()
            window.setWindowFlags(flags | hint if checked else flags & ~hint)
        else:
            flags = window.flags()
            window.setFlags(flags | hint if checked else flags & ~hint)
        window.show()
    finally:
        _PINNING.pop(id(window), None)

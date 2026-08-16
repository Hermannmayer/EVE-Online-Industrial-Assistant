"""窗口置顶工具 — Windows SetWindowPos + WindowStaysOnTopHint 回退。

供主窗口与产线启动小助手等工具窗共用（抽出自 main_window._apply_pin）。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

# 防重入标记（setWindowFlags→show→showEvent 递归）；按窗口 id 记
_PINNING: dict[int, bool] = {}


def apply_window_pin(widget: QWidget, checked: bool) -> None:
    """把窗口置顶/取消置顶。

    Windows 走 SetWindowPos(HWND_TOPMOST/HWND_NOTOPMOST)，不重建窗口不闪烁；
    失败回退 WindowStaysOnTopHint（设置 flag 后需重新 show()）。
    """
    if _PINNING.get(id(widget)):
        return  # 防重入
    _PINNING[id(widget)] = True
    try:
        if os.name == "nt":
            try:
                import ctypes
                import ctypes.wintypes

                hwnd = int(widget.winId())
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
        flags = widget.windowFlags()
        if checked:
            widget.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            widget.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        widget.show()
    finally:
        _PINNING.pop(id(widget), None)

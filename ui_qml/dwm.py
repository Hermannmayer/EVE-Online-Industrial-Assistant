"""Windows DWM 毛玻璃 / 暗色模式 — 纯函数，非 win32 或失败时静默降级 solid。"""

import ctypes
import ctypes.wintypes
import sys

from core.logger import log

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_WINDOW_CORNER_PREFERENCE = 33

_DWMSBT_NONE = 1
_DWMSBT_MAINWINDOW = 2  # Mica
_DWMSBT_TRANSIENTWINDOW = 3  # Acrylic

_DWMWCP_ROUND = 2

_GWL_STYLE = -16
_WS_THICKFRAME = 0x00040000
_WS_CAPTION = 0x00C00000  # WS_BORDER | WS_DLGFRAME
#: 实测（2026-10-01 用真窗口探针读 GWL_STYLE）：无边框外壳上 `WS_THICKFRAME` /
#: `WS_CAPTION` 事后**是在的**，但这两位**恒为 False** —— 而 Aero Snap（拖到屏幕边缘
#: 吸附、拖到顶部最大化）要求窗口**可最大化**，缺 `WS_MAXIMIZEBOX` 时拖到边缘毫无反应。
#: 这正是用户报的「不吸附、也不能改变窗口大小」。
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_FRAME_BITS = _WS_THICKFRAME | _WS_CAPTION | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX

#: `SetWindowPos` 的 `SWP_FRAMECHANGED`：改完样式**必须**重算一次非客户区，
#: 否则 `SetWindowLongPtr` 只是改了记录、系统的命中测试仍按旧样式走。
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOZORDER, _SWP_NOACTIVATE, _SWP_FRAMECHANGED = (
    0x0001,
    0x0002,
    0x0004,
    0x0010,
    0x0020,
)

_WIN11_22000 = (10, 0, 22000)
_WIN11_22621 = (10, 0, 22621)

_LONG_PTR = ctypes.c_ssize_t  # win64 LONG_PTR（否则 HWND/样式被 ctypes 默认 c_int 截断）


def _get_window_style(hwnd: int) -> int:
    user32 = ctypes.windll.user32
    func = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    func.restype = _LONG_PTR
    func.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    return int(func(hwnd, _GWL_STYLE))


def _set_window_style(hwnd: int, style: int) -> None:
    user32 = ctypes.windll.user32
    func = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    func.restype = _LONG_PTR
    func.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, _LONG_PTR]
    func(hwnd, _GWL_STYLE, style)


def _refresh_window_frame(hwnd: int) -> None:
    """让系统重新计算本窗口的非客户区 / 命中测试（样式改完必须调用一次）。"""
    ctypes.windll.user32.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
    )


def enable_native_resize(hwnd: int) -> bool:
    """给无边框窗口补回原生边框样式，恢复边缘缩放、Aero Snap 与最小化/最大化。

    Qt 的 `FramelessWindowHint` 会把这些样式位一起清掉；没有它们时，
    `WM_NCHITTEST` 返回边缘命中码系统也不执行缩放，拖到屏幕边缘也不吸附。

    实测（2026-10-01，真窗口探针）：`WS_THICKFRAME`/`WS_CAPTION` 事后**已经在**，
    但 `WS_MAXIMIZEBOX`/`WS_MINIMIZEBOX` **一直是 False** —— 所以必须把它们也补上，
    否则「不吸附」那条永远好不了。

    样式真的变了才动窗口，并在改完后 `SWP_FRAMECHANGED` 重算一次 frame。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        style = _get_window_style(hwnd)
        new_style = style | _WS_FRAME_BITS
        if new_style != style:
            _set_window_style(hwnd, new_style)
            _refresh_window_frame(hwnd)
        return True
    except Exception:
        # 失败是**静默降级**（无边框外观照旧，只是拖边缘/吸附不可用），所以必须留日志
        log.warning("恢复原生窗口样式失败（边缘缩放与 Aero Snap 会不可用）: hwnd=%s", hwnd, exc_info=True)
        return False


def _win_version() -> tuple[int, int, int] | None:
    try:
        ver = sys.getwindowsversion()  # type: ignore[attr-defined]
        return (ver.major, ver.minor, ver.build)
    except Exception:
        return None


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        dwm.DwmSetWindowAttribute.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        ok = dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
        return bool(ok == 0)
    except Exception:
        return False


def apply_dwm_backdrop(hwnd: int, material: str, dark: bool) -> bool:
    """按主题材质应用 DWM 系统背景（acrylic/mica）与暗色模式。

    - Win11 22621+：acrylic / mica / solid 全支持
    - Win11 22000-22621：仅 mica / solid
    - Win10：仅暗色模式（无系统背景，solid）
    - 非 win32 或调用失败：返回 False（调用方保持 Qt 不透明渲染）
    """
    if sys.platform != "win32" or not hwnd:
        return False
    version = _win_version()
    if version is None:
        return False

    ok = True
    ok &= _set_attr(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)

    if version >= _WIN11_22621:
        backdrop = {
            "acrylic": _DWMSBT_TRANSIENTWINDOW,
            "mica": _DWMSBT_MAINWINDOW,
            "solid": _DWMSBT_NONE,
        }.get(material, _DWMSBT_NONE)
    elif version >= _WIN11_22000:
        backdrop = _DWMSBT_MAINWINDOW if material == "mica" else _DWMSBT_NONE
    else:
        backdrop = _DWMSBT_NONE

    ok &= _set_attr(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, backdrop)
    if version >= _WIN11_22000:
        ok &= _set_attr(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
    return ok

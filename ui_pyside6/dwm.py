"""Windows DWM 毛玻璃 / 暗色模式 — 纯函数，非 win32 或失败时静默降级 solid。"""

import ctypes
import ctypes.wintypes
import sys

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


def enable_native_resize(hwnd: int) -> bool:
    """给无边框窗口重新加上 WS_THICKFRAME，让 Windows 恢复原生边缘缩放与 Aero Snap 贴边吸附。

    Qt 的 FramelessWindowHint 会移除原生边框样式；没有 WS_THICKFRAME 时，
    WM_NCHITTEST 返回边缘命中码系统也不执行缩放/吸附。必须在窗口创建后恢复该样式。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        style = _get_window_style(hwnd)
        style |= _WS_THICKFRAME | _WS_CAPTION
        _set_window_style(hwnd, style)
        return True
    except Exception:
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

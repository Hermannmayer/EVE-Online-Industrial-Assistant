"""Windows 任务栏身份 —— 让窗口与任务栏图标归到本应用自己名下。

Windows 按 **AppUserModelID** 归并任务栏按钮并决定取哪个图标。不显式设置时，
源码运行（python.exe 宿主）的任务栏按钮会显示 Python 的图标、并和其它 Python
程序并成一组；显式设置后与打包后的 exe 表现一致。

⚠️ 这个 id **一旦发布就不能改**：它是任务栏固定（pin）、快捷方式与跳转列表的
关联键，改了会让用户已固定的按钮失效。与 `Main.py` 的 setOrganizationName /
setApplicationName 是同一套语义。

仅 Windows 生效，失败静默 —— 纯外观层的事，不该影响启动。
"""

from __future__ import annotations

import sys

from core.logger import log

APP_USER_MODEL_ID = "EVEAssistant.IndustrialAssistant"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """设置当前进程的 AppUserModelID，返回是否设置成功（非 Windows 恒 False）。

    必须在**创建任何窗口之前**调用（含任务栏分组依赖的 splash 与单实例提示框）。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        return bool(shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0)  # S_OK
    except Exception:
        log.debug("设置 AppUserModelID 失败（仅影响任务栏分组/图标）", exc_info=True)
        return False

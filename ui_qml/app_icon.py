"""程序图标（窗口 / 任务栏）—— 打包在 `ui_qml/assets/app.ico` 的静态资源。

和 `ui_qml/icons.py` 里那套 Phosphor 系统图标不是一回事：那一套随主题染色、
按语义键取 SVG；这个不染色，是 `scripts/make_app_icon.py` 从设计稿
`assets/icon-source.png` 生成的多尺寸 `.ico`，供窗口与任务栏用。

单独成模块是因为 `ui_qml/icons.py` 刻意保持无 Qt 依赖（只有 `ICON_MAP` /
`svg_path` / `load_svg`，QML 侧也要能取），而这里要返回 `QIcon`。
"""

from __future__ import annotations

import os

from PySide6.QtGui import QIcon

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
APP_ICON_PATH = os.path.join(ASSETS_DIR, "app.ico")


def app_icon() -> QIcon:
    """窗口 / 任务栏程序图标。

    资源缺失时返回空 `QIcon` —— 源码运行但尚未生成图标、或资源未随包分发，
    都不该让启动失败（打包后 exe 自带图标，走的是 PyInstaller 的 `--icon`）。
    """
    return QIcon(APP_ICON_PATH) if os.path.exists(APP_ICON_PATH) else QIcon()

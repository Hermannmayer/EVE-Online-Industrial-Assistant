"""Python ↔ QML 桥接层（QObject + Signal/Slot）。"""

from ui_qml.bridge.shell_bridge import ShellBridge
from ui_qml.bridge.theme_bridge import CONTEXT_NAME, ThemeBridge, theme_singleton

__all__ = ["CONTEXT_NAME", "ShellBridge", "ThemeBridge", "theme_singleton"]

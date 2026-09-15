"""QML 侧要用的原生文件对话框。

**为什么这里用 `QFileDialog` 而不是 QML 的 `FileDialog`**：`QFileDialog` 在
Windows 上默认走**系统原生保存框**（资源管理器那个），这不是「QML 页里冒出
一个 Widgets 窗口」——那种违和感指的是 Qt 自绘的对话框。原生保存框是平台惯例，
且它保持**同步**语义（选完就返回路径），三个导出流程一行都不用改成异步。

QML 的 `FileDialog` 同样会用原生后端，但要改成 `accepted` 信号驱动 ——
收益为零、改动面不小，故不采用。哪天真要统一成 QML 组件，这里是唯一入口。
"""

from typing import Any

__all__ = ["get_save_filename"]


def get_save_filename(parent: Any, default_name: str, file_filter: str) -> str:
    """弹出保存文件对话框，返回路径（空字符串表示取消）"""
    from PySide6.QtWidgets import QFileDialog

    path, _ = QFileDialog.getSaveFileName(parent, "导出", default_name, file_filter)
    return path

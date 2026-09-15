"""导出工具的**旧路径转发器** —— 实现已按依赖拆到两处：

- `export_to_csv` / `export_to_excel` → `core/export_helper.py`（纯 Python，零 Qt）
- `get_save_filename` → `ui_qml/file_dialogs.py`（要弹 QFileDialog）

本模块只转发、不复制实现，未迁移完的 Widgets 对话框照旧 `from
ui_pyside6.views.export_helper import ...` 即可。新代码请直接 import 新位置。
"""

from typing import Any

from core import export_helper as _core_export
from ui_qml import file_dialogs as _file_dialogs


def __getattr__(name: str) -> Any:
    """未在本模块定义的名字转发到上面两个新家。"""
    if hasattr(_file_dialogs, name):
        return getattr(_file_dialogs, name)
    return getattr(_core_export, name)

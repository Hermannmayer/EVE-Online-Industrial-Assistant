"""
批量对比模式 — 兼容导入转发

保留此文件以使 ``from ui_pyside6.views.compare_dialog import CompareDialog`` 继续有效。
实际实现在 ``ui_pyside6.views.compare`` 子包中。
"""

from ui_pyside6.views.compare import (
    COMPARE_COLS_MFG,
    COMPARE_COLS_REACTION,
    COMPARE_COLS_TRADE,
    CompareDialog,
    CompareTableModel,
    CompareWorker,
    _fmt_tag,
    _format_isk,
    item_name,
    open_compare_dialog,
    search_items,
)

__all__ = [
    "COMPARE_COLS_MFG",
    "COMPARE_COLS_REACTION",
    "COMPARE_COLS_TRADE",
    "CompareDialog",
    "CompareTableModel",
    "CompareWorker",
    "_fmt_tag",
    "_format_isk",
    "item_name",
    "open_compare_dialog",
    "search_items",
]

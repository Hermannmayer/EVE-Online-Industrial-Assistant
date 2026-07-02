"""对比视图包 — 拆分自 compare_dialog.py"""

from ui_pyside6.views.compare.compare_chart import CompareWorker, item_name, search_items
from ui_pyside6.views.compare.compare_dialog import CompareDialog, open_compare_dialog
from ui_pyside6.views.compare.compare_models import (
    COMPARE_COLS_MFG,
    COMPARE_COLS_REACTION,
    COMPARE_COLS_TRADE,
    CompareTableModel,
    _fmt_tag,
    _format_isk,
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

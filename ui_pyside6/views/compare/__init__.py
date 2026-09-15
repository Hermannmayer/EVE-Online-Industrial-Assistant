"""对比视图包 — 拆分自 compare_dialog.py"""

from core.formatting import fmt_tag as _fmt_tag
from ui_pyside6.views.compare.compare_dialog import CompareDialog, open_compare_dialog
from ui_qml.models.compare_models import (
    COMPARE_COLS_MFG,
    COMPARE_COLS_REACTION,
    COMPARE_COLS_TRADE,
    CompareTableModel,
    _format_isk,
)
from ui_qml.workers.compare_chart import CompareWorker, item_name, search_items

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

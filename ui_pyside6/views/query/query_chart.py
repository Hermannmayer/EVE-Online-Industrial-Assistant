"""
价格走势图 — 委托给 price_chart 模块
"""

from PySide6.QtWidgets import QWidget


def show_price_chart(parent: QWidget, type_id: int, name: str) -> None:
    """打开价格走势图对话框"""
    from ui_pyside6.views.price_chart import PriceChartDialog

    dlg = PriceChartDialog(type_id, name, parent)
    dlg.exec()

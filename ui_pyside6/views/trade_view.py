"""
贸易页面 — 价格监控 & 运输分析
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QTableView, QHeaderView, QLineEdit, QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
from ui_pyside6.theme import BG_DARK, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY


class TradePage(QWidget):
    """市场贸易页"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("trade_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 子标签
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
        """)

        tabs.addTab(self._build_monitor_tab(), "价格监控")
        tabs.addTab(self._build_transport_tab(), "运输分析")

        layout.addWidget(tabs)

    def _build_monitor_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 占位
        placeholder = QLabel("价格监控 — 开发中\n\n关注物品的价格变化，设置提醒阈值。")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 16px;")
        layout.addWidget(placeholder)

        return w

    def _build_transport_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        placeholder = QLabel("运输分析 — 开发中\n\n分析空间站间的价差与运输利润。")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 16px;")
        layout.addWidget(placeholder)

        return w

    def refresh_display(self):
        pass

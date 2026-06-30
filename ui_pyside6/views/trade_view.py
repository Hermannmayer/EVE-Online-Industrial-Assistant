"""
贸易页面 — 价格监控 & 运输分析
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme


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
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
        """)

        self._tabs.addTab(self._build_monitor_tab(), "价格监控")
        self._tabs.addTab(self._build_transport_tab(), "运输分析")

        layout.addWidget(self._tabs)

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
        """)
        self._monitor_placeholder.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 16px;")
        self._transport_placeholder.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 16px;")

    def _build_monitor_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 占位
        self._monitor_placeholder = QLabel("价格监控 — 开发中\n\n关注物品的价格变化，设置提醒阈值。")
        self._monitor_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._monitor_placeholder.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 16px;")
        layout.addWidget(self._monitor_placeholder)

        return w

    def _build_transport_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._transport_placeholder = QLabel("运输分析 — 开发中\n\n分析空间站间的价差与运输利润。")
        self._transport_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._transport_placeholder.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 16px;")
        layout.addWidget(self._transport_placeholder)

        return w

    def refresh_display(self):
        pass

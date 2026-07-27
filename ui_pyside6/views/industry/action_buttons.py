"""Action buttons for the industry plan view — quick-access toolbar actions."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui_pyside6.theme import (
    BORDER,
    PRIMARY,
    TEXT_PRIMARY,
    add_theme_listener,
)


class ActionButtons(QWidget):
    """底部操作按钮组"""

    refresh_procurement_requested = Signal()
    blueprint_list_requested = Signal()
    materials_summary_requested = Signal()
    output_summary_requested = Signal()
    char_usage_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        add_theme_listener(self._on_theme_changed)

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(10)

        self._btn_refresh_procurement = QPushButton("采购小助手")
        root.addWidget(self._btn_refresh_procurement)

        self._btn_blueprint_list = QPushButton("所需蓝图表")
        root.addWidget(self._btn_blueprint_list)

        self._btn_materials = QPushButton("填料总表")
        root.addWidget(self._btn_materials)

        self._btn_output = QPushButton("产出总表")
        root.addWidget(self._btn_output)

        self._btn_char_usage = QPushButton("人物占用")
        root.addWidget(self._btn_char_usage)

        root.addStretch(1)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_refresh_procurement.clicked.connect(self.refresh_procurement_requested)
        self._btn_blueprint_list.clicked.connect(self.blueprint_list_requested)
        self._btn_materials.clicked.connect(self.materials_summary_requested)
        self._btn_output.clicked.connect(self.output_summary_requested)
        self._btn_char_usage.clicked.connect(self.char_usage_requested)

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(
            f"ActionButtons {{ background: transparent; }}"
            f"QPushButton {{ padding: 5px 14px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()

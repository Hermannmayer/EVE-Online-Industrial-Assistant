"""Status bar for the industry plan view — statistics and procurement summary."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui_pyside6.theme import (
    BORDER,
    PRIMARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    add_theme_listener,
)


class StatusBar(QWidget):
    """底部状态栏：左侧统计 | 右侧采购汇总"""

    save_price_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        add_theme_listener(self._on_theme_changed)

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(12)

        # 左侧：统计
        self._stats_label = QLabel("计划总数: 0 | 运行中: 0 | 待排: 0")
        root.addWidget(self._stats_label)

        root.addStretch(1)

        # 右侧：采购汇总
        self._material_label = QLabel("采购总额: 0.00 ISK | 体积: 0 m3")
        root.addWidget(self._material_label)

        self._btn_save_price = QPushButton("保存价格")
        root.addWidget(self._btn_save_price)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_save_price.clicked.connect(self.save_price_requested)

    # ── 公共方法 ──────────────────────────────────────────────

    def update_stats(self, plans: list[dict]):
        """从 plans 计算统计信息并刷新标签"""
        total = len(plans)
        running = sum(1 for p in plans if p.get("status") == "running")
        pending = sum(1 for p in plans if p.get("status") == "pending")
        self._stats_label.setText(
            f"计划总数: {total} | 运行中: {running} | 待排: {pending}"
        )

    def update_material(self, total_cost: float, volume: float):
        """更新采购总额与体积"""
        self._material_label.setText(
            f"采购总额: {total_cost:,.2f} ISK | 体积: {volume:,.1f} m3"
        )

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(
            f"StatusBar {{ background: transparent; }}"
            f"QLabel {{ color: {TEXT_SECONDARY}; background: transparent; font-size: 12px; }}"
            f"QPushButton {{ padding: 3px 8px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()

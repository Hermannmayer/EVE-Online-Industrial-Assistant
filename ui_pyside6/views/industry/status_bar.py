"""Status bar for the industry plan view — statistics and procurement summary."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui_pyside6.theme import (
    ACCENT_ORANGE,
    BORDER,
    PRIMARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    add_theme_listener,
)


class StatusBar(QWidget):
    """底部状态栏：左侧统计 + 全部下线 | 右侧采购汇总"""

    save_price_requested = Signal()
    complete_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_plans: list[dict] = []
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
        self._stats_label = QLabel("计划总数: 0 | 运行中: 0 | 待排: 0 | 产线(备料): 0")
        root.addWidget(self._stats_label)

        # 全部下线（有待下线计划时显示）
        self._btn_complete_all = QPushButton("全部下线")
        self._btn_complete_all.setObjectName("complete_all_btn")
        self._btn_complete_all.setVisible(False)
        root.addWidget(self._btn_complete_all)

        root.addStretch(1)

        # 右侧：采购汇总
        self._material_label = QLabel("备料中采购: 0 ISK | 体积: 0.0 m3")
        root.addWidget(self._material_label)

        self._btn_save_price = QPushButton("保存价格")
        root.addWidget(self._btn_save_price)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_save_price.clicked.connect(self.save_price_requested)
        self._btn_complete_all.clicked.connect(self.complete_all_requested)

    # ── 公共方法 ──────────────────────────────────────────────

    def update_stats(self, plans: list[dict]):
        """从 plans 计算统计信息并刷新标签；有待下线计划时显示「全部下线」按钮"""
        self._last_plans = plans
        total = len(plans)
        running = sum(1 for p in plans if p.get("status") in ("in_progress", "running"))
        pending = sum(1 for p in plans if p.get("status") == "pending")
        ready = sum(1 for p in plans if p.get("status") == "ready")
        mats_lines = sum(int(p.get("parallels") or 0) for p in plans if p.get("materials_ready", 0))
        self._stats_label.setText(f"计划总数: {total} | 运行中: {running} | 待排: {pending} | 产线(备料): {mats_lines}")
        if ready:
            self._btn_complete_all.setText(f"全部下线 ({ready})")
            self._btn_complete_all.setVisible(True)
        else:
            self._btn_complete_all.setVisible(False)

    def update_material(self, total_cost: float, volume: float):
        """更新备料中采购总额与体积"""
        self._material_label.setText(f"备料中采购: {total_cost:,.0f} ISK | 体积: {volume:,.1f} m3")

    def show_message(self, text: str, timeout: int = 0):
        """显示临时消息（可选自动清除，恢复最近统计与按钮状态）"""
        self._stats_label.setText(text)
        if timeout > 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(timeout, lambda: self.update_stats(self._last_plans))

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(
            f"StatusBar {{ background: transparent; }}"
            f"QLabel {{ color: {TEXT_SECONDARY}; background: transparent; font-size: 12px; }}"
            f"QPushButton {{ padding: 3px 8px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}"
            f"QPushButton#complete_all_btn {{ border-color: {ACCENT_ORANGE}; color: {ACCENT_ORANGE}; }}"
            f"QPushButton#complete_all_btn:hover {{ background: {ACCENT_ORANGE}; color: #ffffff; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()

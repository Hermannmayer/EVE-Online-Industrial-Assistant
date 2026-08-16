"""主题选择器 — 卡片网格，色卡预览 + 即时切换（防闪烁）"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme

_SWATCH_KEYS = ("BG_SURFACE", "PRIMARY", "TEXT_PRIMARY")
_CARD_W = 148
_CARD_H = 88


class _ThemeCard(QPushButton):
    """单张主题卡片：色块预览 + 中文名 + 暗/亮角标 + 材质小字"""

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self._spec = spec
        self.setObjectName("theme_card")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(_CARD_W, _CARD_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # 顶部行：3 个色块 + 暗/亮角标
        top = QHBoxLayout()
        top.setSpacing(4)
        colors = spec["colors"]
        for key in _SWATCH_KEYS:
            swatch = QLabel()
            swatch.setFixedSize(32, 20)
            swatch.setStyleSheet(
                f"background-color: {colors[key]}; border: 1px solid {colors['BORDER']}; border-radius: 2px;"
            )
            top.addWidget(swatch)
        top.addStretch(1)
        self._badge = QLabel("暗" if spec["mode"] == "dark" else "亮")
        self._badge.setStyleSheet(self._badge_style())
        top.addWidget(self._badge)
        layout.addLayout(top)

        self._name_label = QLabel(spec["name_zh"])
        self._name_label.setStyleSheet(self._name_style())
        layout.addWidget(self._name_label)

        self._material_label = QLabel(spec["material"])
        self._material_label.setStyleSheet(self._material_style())
        layout.addWidget(self._material_label)
        layout.addStretch(1)

    # ── 动态样式（随当前主题重刷） ──

    def _badge_style(self) -> str:
        return (
            f"color: {theme.TEXT_SECONDARY}; font-size: 10px; padding: 0 4px;"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px;"
        )

    def _name_style(self) -> str:
        return f"color: {theme.TEXT_PRIMARY}; font-size: 12px; border: none;"

    def _material_style(self) -> str:
        return f"color: {theme.TEXT_SECONDARY}; font-size: 10px; border: none;"

    def refresh(self):
        """主题切换后刷新依赖当前主题 token 的样式"""
        self._badge.setStyleSheet(self._badge_style())
        self._name_label.setStyleSheet(self._name_style())
        self._material_label.setStyleSheet(self._material_style())


class ThemeSelector(QWidget):
    """主题卡片网格选择器 — 点击即时切换并持久化（持久化由 apply_theme 内部完成）"""

    theme_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_id: str = theme.current_theme()
        self._cards: dict[str, _ThemeCard] = {}

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(260)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setSpacing(8)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for col, spec in enumerate(theme.THEME_REGISTRY.values()):
            card = _ThemeCard(spec)
            card.setFixedWidth(_CARD_W)
            self._cards[spec["id"]] = card
            group.addButton(card)
            card.clicked.connect(lambda _=False, tid=spec["id"]: self._on_card_clicked(tid))
            grid.addWidget(card, col // 3, col % 3)

        scroll.setWidget(grid_host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._apply_current()
        theme.add_theme_listener(self._on_theme_changed)

    # ── 对外接口 ──

    def current_theme_id(self) -> str:
        return self._current_id

    def set_current(self, theme_id: str):
        """同步选中态与卡片样式（不触发切换/持久化）"""
        self._current_id = theme_id
        self._apply_current()

    # ── 内部 ──

    def _on_theme_changed(self):
        self.set_current(theme.current_theme())

    def _on_card_clicked(self, theme_id: str):
        if theme_id == self._current_id:
            return
        # 防闪烁：冻结重绘 → 应用 → 恢复
        self.setUpdatesEnabled(False)
        theme.apply_theme(theme_id)  # 会同步通知监听器 → _on_theme_changed → set_current
        QApplication.processEvents()
        self.setUpdatesEnabled(True)
        self.update()
        self.theme_selected.emit(theme_id)

    def _apply_current(self):
        for tid, card in self._cards.items():
            card.setChecked(tid == self._current_id)
            card.refresh()


def minimum_size() -> QSize:
    return QSize(_CARD_W * 3 + 24, 320)

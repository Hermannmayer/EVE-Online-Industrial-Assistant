"""双行价格来源设置 — 材料/成品各自独立配置 Hub、价格类型、倍率"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUBS
from services.terminology import term

# ── 内部：价格类型名称映射 ──
_PRICE_TYPES: list[tuple[str, str]] = [
    ("sell", term.label("sell_price")),  # "卖价"
    ("buy", term.label("buy_price")),  # "买价"
]


class PriceSourceRow(QWidget):
    """单行价格来源设置。

    包含 Hub 下拉 + 卖价/买价下拉 + 倍率 SpinBox，水平排列。
    标签由外部传入（"材料" / "成品"）。
    """

    hub_changed = Signal(str)  # 传递 Hub 英文名
    price_type_changed = Signal(str)  # "sell" / "buy"
    mult_changed = Signal(float)

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._label_text = label
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        theme.add_theme_listener(self._apply_style)

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # 行标签
        self._label = QLabel(self._label_text)
        self._label.setFixedWidth(28)
        layout.addWidget(self._label)

        # Hub 下拉
        self._hub_combo = QComboBox()
        self._hub_combo.addItems(TRADE_HUBS)
        self._hub_combo.setFixedWidth(76)
        layout.addWidget(self._hub_combo)

        # 价格类型下拉
        self._price_type_combo = QComboBox()
        for _val, display in _PRICE_TYPES:
            self._price_type_combo.addItem(display)
        self._price_type_combo.setFixedWidth(56)
        layout.addWidget(self._price_type_combo)

        # 倍率
        self._mult_spin = QDoubleSpinBox()
        self._mult_spin.setRange(0.1, 10.0)
        self._mult_spin.setSingleStep(0.05)
        self._mult_spin.setValue(1.00)
        self._mult_spin.setDecimals(2)
        self._mult_spin.setFixedWidth(68)
        layout.addWidget(self._mult_spin)

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._hub_combo.currentTextChanged.connect(self._on_hub_changed)
        self._price_type_combo.currentIndexChanged.connect(self._on_price_type_changed)
        self._mult_spin.valueChanged.connect(self.mult_changed)

    def _on_hub_changed(self, text: str) -> None:
        self.hub_changed.emit(text)

    def _on_price_type_changed(self, idx: int) -> None:
        self.price_type_changed.emit(_PRICE_TYPES[idx][0])

    # ── 公共方法 ──────────────────────────────────────────

    def get_hub(self) -> str:
        return self._hub_combo.currentText()

    def get_price_type(self) -> str:
        return _PRICE_TYPES[self._price_type_combo.currentIndex()][0]

    def get_mult(self) -> float:
        return self._mult_spin.value()

    def set_hub(self, hub: str) -> None:
        idx = self._hub_combo.findText(hub)
        if idx >= 0:
            self._hub_combo.setCurrentIndex(idx)

    def set_price_type(self, price_type: str) -> None:
        for i, (val, _) in enumerate(_PRICE_TYPES):
            if val == price_type:
                self._price_type_combo.setCurrentIndex(i)
                return

    def set_mult(self, mult: float) -> None:
        self._mult_spin.setValue(mult)

    # ── 样式 ──────────────────────────────────────────────

    def _apply_style(self) -> None:
        self._label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; font-weight: bold;"
        )


class DualPriceSourceWidget(QWidget):
    """价格来源设置 — 材料/成品水平排列在一行。

    ┌─ 材料 [Jita▼] [卖价▼] [×1.00] ── 成品 [Jita▼] [卖价▼] [×1.00] ─┐
    """

    # 材料行信号
    mat_hub_changed = Signal(str)
    mat_price_type_changed = Signal(str)
    mat_mult_changed = Signal(float)

    # 成品行信号
    prod_hub_changed = Signal(str)
    prod_price_type_changed = Signal(str)
    prod_mult_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 材料行
        self._mat_row = PriceSourceRow("材料")
        layout.addWidget(self._mat_row)

        # 分隔
        sep = QLabel("|")
        sep.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; background: transparent; font-size: 12px;")
        layout.addWidget(sep)

        # 成品行
        self._prod_row = PriceSourceRow(term.label("product"))
        layout.addWidget(self._prod_row)

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        # 材料行 → 委托信号
        self._mat_row.hub_changed.connect(self.mat_hub_changed.emit)
        self._mat_row.price_type_changed.connect(self.mat_price_type_changed.emit)
        self._mat_row.mult_changed.connect(self.mat_mult_changed.emit)

        # 成品行 → 委托信号
        self._prod_row.hub_changed.connect(self.prod_hub_changed.emit)
        self._prod_row.price_type_changed.connect(self.prod_price_type_changed.emit)
        self._prod_row.mult_changed.connect(self.prod_mult_changed.emit)

    # ── 公共方法 ──────────────────────────────────────────

    def get_settings(self) -> dict[str, str | float]:
        """返回所有价格设置的字典。"""
        return {
            "mat_hub": self._mat_row.get_hub(),
            "mat_price_type": self._mat_row.get_price_type(),
            "mat_mult": self._mat_row.get_mult(),
            "prod_hub": self._prod_row.get_hub(),
            "prod_price_type": self._prod_row.get_price_type(),
            "prod_mult": self._prod_row.get_mult(),
        }

    def set_settings(self, settings: dict[str, str | float]) -> None:
        """从字典恢复设置。"""
        if "mat_hub" in settings:
            self._mat_row.set_hub(str(settings["mat_hub"]))
        if "mat_price_type" in settings:
            self._mat_row.set_price_type(str(settings["mat_price_type"]))
        if "mat_mult" in settings:
            self._mat_row.set_mult(float(settings["mat_mult"]))
        if "prod_hub" in settings:
            self._prod_row.set_hub(str(settings["prod_hub"]))
        if "prod_price_type" in settings:
            self._prod_row.set_price_type(str(settings["prod_price_type"]))
        if "prod_mult" in settings:
            self._prod_row.set_mult(float(settings["prod_mult"]))

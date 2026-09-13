"""产线启动小助手 — 部分启动对话框（选择本次启动几条产线）。

其余产线会留在主界面「未启动」那一行里，材料只按本次启动的条数扣减。
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

import ui_pyside6.theme as theme


class PartialStartDialog(QDialog):
    """选择本次启动的产线条数（1 .. total_lines-1）。"""

    def __init__(self, product_name: str, total_lines: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("部分启动")
        self.setMinimumWidth(340)
        self._total = max(int(total_lines), 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._tip = QLabel(f"「{product_name}」共 {self._total} 条并行产线，本次启动几条？")
        self._tip.setWordWrap(True)
        layout.addWidget(self._tip)

        form = QFormLayout()
        self._spin = QSpinBox()
        self._spin.setRange(1, self._total - 1)
        self._spin.setValue(self._total - 1)
        self._spin.setSuffix(" 条")
        self._spin.valueChanged.connect(self._on_value_changed)
        form.addRow("启动条数:", self._spin)
        layout.addLayout(form)

        self._summary = QLabel("")
        layout.addWidget(self._summary)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("启动")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._on_value_changed(self._spin.value())
        theme.add_theme_listener(self._on_theme_changed)

    def lines(self) -> int:
        """本次启动的产线条数。"""
        return int(self._spin.value())

    def _on_value_changed(self, value: int) -> None:
        rest = self._total - int(value)
        self._summary.setText(f"启动 {value} 条，剩余 {rest} 条留在「待生产」行里；材料只按本次启动的 {value} 条扣减")

    def _on_theme_changed(self):
        self._summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")

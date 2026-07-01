"""预默认/单行配置对话框 — ME/TE/设施/输出/技能等级"""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

import ui_pyside6.theme as theme

SKILL_LEVELS = [
    ("技能全5", 5),
    ("技能全4", 4),
    ("技能全3", 3),
    ("自定义", 0),
]


class PreDefaultDialog(QDialog):
    """预默认配置对话框"""

    def __init__(self, parent=None, plan_data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("预默认配置（阶段一占位，功能开发中）")
        self.setMinimumWidth(380)
        self._plan_data = plan_data or {}
        self._build_ui()
        self._load_data()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        form = QFormLayout()
        form.setLabelAlignment(
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignRight
        )

        # ME
        self._me_spin = QSpinBox()
        self._me_spin.setRange(0, 20)
        self._me_spin.setValue(0)
        form.addRow("ME 等级", self._me_spin)

        # TE
        self._te_spin = QSpinBox()
        self._te_spin.setRange(0, 20)
        self._te_spin.setValue(0)
        form.addRow("TE 等级", self._te_spin)

        # 设施
        self._facility_edit = QLineEdit()
        self._facility_edit.setPlaceholderText("例：Jita - Calle")
        form.addRow("设施位置", self._facility_edit)

        # 输出
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("例：Jita - Perimeter")
        form.addRow("输出位置", self._output_edit)

        # 技能等级
        self._skill_combo = QComboBox()
        for label, _value in SKILL_LEVELS:
            self._skill_combo.addItem(label)
        form.addRow("技能等级", self._skill_combo)

        root.addLayout(form)

        # 提示标签
        hint = QLabel("注：此对话框为阶段一占位，部分功能尚未实现。")
        hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._hint_label = hint
        root.addWidget(hint)

        # 按钮
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    # ── 数据 ──────────────────────────────────────────────────

    def _load_data(self):
        """用 plan_data 预填充"""
        d = self._plan_data
        if "me" in d:
            self._me_spin.setValue(d["me"])
        if "te" in d:
            self._te_spin.setValue(d["te"])
        if "facility" in d:
            self._facility_edit.setText(d["facility"])
        if "output" in d:
            self._output_edit.setText(d["output"])
        if "skill_level" in d:
            val = d["skill_level"]
            for idx, (_, level) in enumerate(SKILL_LEVELS):
                if level == val:
                    self._skill_combo.setCurrentIndex(idx)
                    break

    def get_config(self) -> dict:
        """返回配置字典"""
        _, skill_value = SKILL_LEVELS[self._skill_combo.currentIndex()]
        return {
            "me": self._me_spin.value(),
            "te": self._te_spin.value(),
            "facility": self._facility_edit.text().strip(),
            "output": self._output_edit.text().strip(),
            "skill_level": skill_value,
        }

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self):
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"
            f"QLabel {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QSpinBox, QComboBox, QLineEdit {{"
            f"  padding: 4px 8px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY}; font-size: 12px;"
            f"}}"
            f"QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{"
            f"  border-color: {theme.PRIMARY};"
            f"}}"
            f"QPushButton {{"
            f"  padding: 4px 16px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px;"
            f"}}"
            f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.PRIMARY}; }}"
            f"QPushButton:pressed {{ background: {theme.BG_SURFACE_LIGHT}; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f"  selection-background-color: {theme.BG_SURFACE_LIGHT};"
            f"}}"
        )

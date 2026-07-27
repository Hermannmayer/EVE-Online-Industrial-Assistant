"""计划编辑对话框 — 右键"编辑生产计划"时弹出"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

import ui_pyside6.theme as theme

CHAR_OPTIONS = ["main(技能全5)", "alt(技能全4)", "自定义"]
HUB_OPTIONS = ["Jita", "Amarr", "Dodixie", "Rens", "Hek"]


class PlanEditDialog(QDialog):
    """右键"编辑生产计划"时弹出的编辑对话框"""

    def __init__(self, parent=None, plan_data: dict | None = None):
        super().__init__(parent)
        self._plan_data = plan_data or {}
        product_name = self._plan_data.get("product_name", "未知产品")
        self.setWindowTitle(f"编辑生产计划 - {product_name}")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_data()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 产品名称（只读）
        self._product_label = QLabel("—")
        self._product_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("产品名称", self._product_label)

        # 流程数
        self._runs_spin = QSpinBox()
        self._runs_spin.setRange(1, 99999)
        self._runs_spin.setValue(1)
        form.addRow("流程数", self._runs_spin)

        # 并行数
        self._parallel_spin = QSpinBox()
        self._parallel_spin.setRange(1, 100)
        self._parallel_spin.setValue(1)
        form.addRow("并行数", self._parallel_spin)

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

        # 人物
        self._char_combo = QComboBox()
        self._char_combo.addItems(CHAR_OPTIONS)
        form.addRow("人物", self._char_combo)

        # 设施（兼材料来源地）
        self._facility_edit = QLineEdit()
        self._facility_edit.setPlaceholderText("设施/星系名称")
        form.addRow("设施/材料源", self._facility_edit)

        # 输出位置（从机库选择）
        self._output_combo = QComboBox()
        self._output_combo.setEditable(True)
        self._output_combo.setPlaceholderText("选择或输入输出位置…")
        self._output_combo.addItems(HUB_OPTIONS)
        form.addRow("输出位置", self._output_combo)

        # 备注
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("备注信息…")
        self._notes_edit.setFixedHeight(60)
        form.addRow("备注", self._notes_edit)

        root.addLayout(form)

        # 按钮
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    # ── 数据 ──────────────────────────────────────────────────

    def _load_data(self):
        d = self._plan_data
        self._product_label.setText(str(d.get("product_name", "—")))

        if "runs" in d:
            self._runs_spin.setValue(d["runs"])
        if "parallels" in d:
            self._parallel_spin.setValue(d["parallels"])
        if "me_level" in d:
            self._me_spin.setValue(d["me_level"])
        elif "me" in d:
            self._me_spin.setValue(d["me"])
        if "te_level" in d:
            self._te_spin.setValue(d["te_level"])
        elif "te" in d:
            self._te_spin.setValue(d["te"])

        char = d.get("char_name", d.get("character", ""))
        if char:
            idx = self._char_combo.findText(char)
            if idx >= 0:
                self._char_combo.setCurrentIndex(idx)

        facility = d.get("facility", d.get("mat_hub", ""))
        if facility:
            # 优先设施名，其次材料 Hub
            self._facility_edit.setText(facility)

        output = d.get("output", d.get("output_location", ""))
        if output:
            idx = self._output_combo.findText(output)
            if idx >= 0:
                self._output_combo.setCurrentIndex(idx)
            else:
                self._output_combo.setEditText(output)

        raw_notes = d.get("notes", "")
        if raw_notes:
            self._notes_edit.setPlainText(raw_notes)

    def get_updated_data(self) -> dict:
        """返回更新后的字段字典"""
        output_text = self._output_combo.currentText().strip()
        return {
            "product_name": self._product_label.text(),
            "runs": self._runs_spin.value(),
            "parallels": self._parallel_spin.value(),
            "me_level": self._me_spin.value(),
            "te_level": self._te_spin.value(),
            "char_name": self._char_combo.currentText(),
            "facility": self._facility_edit.text().strip(),
            "output": output_text,
            "material_hub": self._facility_edit.text().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
        }

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self):
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"
            f"QLabel {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QSpinBox, QComboBox, QLineEdit, QTextEdit {{"
            f"  padding: 4px 8px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY}; font-size: 12px;"
            f"}}"
            f"QSpinBox:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus {{"
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
            f"  selection-background-color: {theme.PRIMARY};"
            f"}}"
            f"QTextEdit {{"
            f"  background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"}}"
        )

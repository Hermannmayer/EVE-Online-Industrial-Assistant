"""计划编辑对话框 — 右键"编辑生产计划"时弹出"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from services import inventory_manager
from ui_pyside6.views.char_settings_view import get_character_list

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

        # 材料效率(ME)
        self._me_spin = QSpinBox()
        self._me_spin.setRange(0, 20)
        self._me_spin.setValue(0)
        self._me_spin.setToolTip("材料效率等级（0-10 有效，最高 20）")
        form.addRow("材料效率(ME):", self._me_spin)

        # 时间效率(TE)
        self._te_spin = QSpinBox()
        self._te_spin.setRange(0, 20)
        self._te_spin.setValue(0)
        self._te_spin.setToolTip("时间效率等级（0-20）")
        form.addRow("时间效率(TE):", self._te_spin)

        # 人物（可编辑下拉，从真实角色列表加载）
        self._char_combo = QComboBox()
        self._char_combo.setEditable(True)
        chars = get_character_list()
        if chars:
            self._char_combo.addItems(chars)
        else:
            self._char_combo.addItem("main")
        form.addRow("人物", self._char_combo)

        # 设施（可编辑下拉，带机库候选）
        self._facility_combo = QComboBox()
        self._facility_combo.setEditable(True)
        self._facility_combo.setPlaceholderText("选择或输入设施/星系名称")
        try:
            hangars = inventory_manager.get_hangars()
            for h in hangars:
                self._facility_combo.addItem(h.get("name", ""))
        except Exception:
            pass
        form.addRow("设施/材料源", self._facility_combo)

        # 输出位置
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
        self._buttons.accepted.connect(self._validate_and_accept)
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
            else:
                self._char_combo.setEditText(char)

        facility = d.get("facility", d.get("mat_hub", ""))
        if facility:
            idx = self._facility_combo.findText(facility)
            if idx >= 0:
                self._facility_combo.setCurrentIndex(idx)
            else:
                self._facility_combo.setEditText(facility)

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

    def _validate_and_accept(self):
        """校验输入后保存"""
        char_name = self._char_combo.currentText().strip()
        if not char_name:
            QMessageBox.warning(self, "校验", "请输入角色名")
            self._char_combo.setFocus()
            return
        facility = self._facility_combo.currentText().strip()
        if not facility:
            ret = QMessageBox.question(
                self,
                "校验",
                "设施/材料源为空，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                self._facility_combo.setFocus()
                return
        self.accept()

    def get_updated_data(self) -> dict:
        """返回更新后的字段字典"""
        facility_text = self._facility_combo.currentText().strip()
        output_text = self._output_combo.currentText().strip()
        return {
            "product_name": self._product_label.text(),
            "runs": self._runs_spin.value(),
            "parallels": self._parallel_spin.value(),
            "me_level": self._me_spin.value(),
            "te_level": self._te_spin.value(),
            "char_name": self._char_combo.currentText().strip(),
            "facility": facility_text,
            "output": output_text,
            # material_hub 沿用设施字段（后续可由 PriceSourceWidget 的材料行设置覆盖）
            "material_hub": facility_text,
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

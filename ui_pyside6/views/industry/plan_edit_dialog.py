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


class PlanEditDialog(QDialog):
    """编辑/批量编辑生产计划对话框（不含 ME/TE，由"设置蓝图等级"单独设置）"""

    def __init__(self, parent=None, plan_data: dict | None = None, *, batch_mode: bool = False, row_count: int = 0):
        super().__init__(parent)
        self._plan_data = plan_data or {}
        self._batch_mode = batch_mode
        product_name = self._plan_data.get("product_name", "未知产品")
        if batch_mode:
            self.setWindowTitle(f"批量编辑生产计划 ({row_count} 行)")
        else:
            self.setWindowTitle(f"编辑生产计划 - {product_name}")
        self.setMinimumWidth(480)
        self.setMinimumHeight(400)
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

        # 人物（纯下拉，从真实角色列表加载）
        self._char_combo = QComboBox()
        self._char_combo.setEditable(False)
        chars = get_character_list()
        if chars:
            self._char_combo.addItems(chars)
        else:
            self._char_combo.addItem("main")
        form.addRow("人物", self._char_combo)

        # 设施（纯下拉，从机库列表加载）
        self._facility_combo = QComboBox()
        self._facility_combo.setEditable(False)
        self._facility_combo.setPlaceholderText("选择设施/星系名称")
        form.addRow("设施/材料源", self._facility_combo)

        # 输出位置（纯下拉，共用机库列表）
        self._output_combo = QComboBox()
        self._output_combo.setEditable(False)
        self._output_combo.setPlaceholderText("选择输出位置…")
        form.addRow("输出位置", self._output_combo)

        # 从机库列表填充设施和输出位置
        try:
            hangars = inventory_manager.get_hangars()
            names = [h.get("name", "") for h in hangars if h.get("name")]
            self._facility_combo.addItems(names)
            self._output_combo.addItems(names)
        except Exception:
            pass

        # 备注
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("备注信息…")
        self._notes_edit.setFixedHeight(60)
        form.addRow("备注", self._notes_edit)

        root.addLayout(form)
        root.addStretch()

        # 按钮
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._validate_and_accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    # ── 数据 ──────────────────────────────────────────────────

    def _load_data(self):
        d = self._plan_data
        if self._batch_mode:
            self._product_label.setText(f"已选中 {len(d.get('_selected_rows', []))} 行")
            self._runs_spin.setValue(1)
            self._parallel_spin.setValue(1)
        else:
            self._product_label.setText(str(d.get("product_name", "—")))
            if "runs" in d:
                self._runs_spin.setValue(d["runs"])
            if "parallels" in d:
                self._parallel_spin.setValue(d["parallels"])

        char = d.get("char_name", d.get("character", ""))
        if char:
            idx = self._char_combo.findText(char)
            if idx >= 0:
                self._char_combo.setCurrentIndex(idx)
            else:
                self._char_combo.insertItem(0, char)
                self._char_combo.setCurrentIndex(0)

        facility = d.get("facility", d.get("mat_hub", ""))
        if facility:
            idx = self._facility_combo.findText(facility)
            if idx >= 0:
                self._facility_combo.setCurrentIndex(idx)
            else:
                self._facility_combo.insertItem(0, facility)
                self._facility_combo.setCurrentIndex(0)

        output = d.get("output", d.get("output_location", ""))
        if output:
            idx = self._output_combo.findText(output)
            if idx >= 0:
                self._output_combo.setCurrentIndex(idx)
            else:
                self._output_combo.insertItem(0, output)
                self._output_combo.setCurrentIndex(0)

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
        result = {
            "runs": self._runs_spin.value(),
            "parallels": self._parallel_spin.value(),
            "char_name": self._char_combo.currentText().strip(),
            "facility": facility_text,
            "output": output_text,
            "material_hub": facility_text,
            "notes": self._notes_edit.toPlainText().strip(),
        }
        if not self._batch_mode:
            result["product_name"] = self._product_label.text()
        return result

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
            f"QSlider::groove:horizontal {{"
            f"  height: 6px; border-radius: 3px; background: {theme.BORDER};"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  width: 14px; height: 14px; margin: -4px 0; border-radius: 7px;"
            f"  background: {theme.PRIMARY};"
            f"}}"
            f"QSlider::sub-page:horizontal {{"
            f"  background: {theme.PRIMARY}; border-radius: 3px;"
            f"}}"
            f"QSlider::tick-mark:horizontal {{"
            f"  color: {theme.TEXT_SECONDARY};"
            f"}}"
        )

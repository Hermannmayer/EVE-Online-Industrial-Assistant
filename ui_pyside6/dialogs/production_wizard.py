"""产线启动小助手 — 单对话框启动多条生产计划"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from ui_pyside6.views.char_settings_view import get_character_list


class ProductionWizard(QDialog):
    """产线启动小助手 — 检查备料/角色/设施 → 一键启动多条产线"""

    def __init__(self, plans: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("产线启动小助手")
        self.setMinimumSize(600, 500)
        self.setObjectName("production_wizard")

        self._plans = plans

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 说明
        header = QLabel(f"将启动 <b>{len(plans)}</b> 条生产计划")
        header.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px;")
        layout.addWidget(header)

        # 计划列表（可多选）
        list_group = QGroupBox("选择要启动的计划")
        lg = QVBoxLayout(list_group)
        self._plan_checks: list[tuple[QCheckBox, dict]] = []
        for p in plans:
            name = p.get("product_name", p.get("blueprint_name", f"ID:{p.get('product_type_id', '')}"))
            status = p.get("status", "")
            cb = QCheckBox(f"{name}  [{status}]")
            cb.setChecked(True)
            self._plan_checks.append((cb, p))
            lg.addWidget(cb)
        layout.addWidget(list_group)

        # 角色和设施
        config_group = QGroupBox("配置")
        cg = QHBoxLayout(config_group)
        cg.addWidget(QLabel("人物:"))
        self._char_combo = QComboBox()
        chars = get_character_list()
        self._char_combo.addItems(chars if chars else ["main"])
        cg.addWidget(self._char_combo)
        cg.addWidget(QLabel("设施:"))
        self._facility_combo = QComboBox()
        self._facility_combo.addItems(["Jita", "Amarr", "Dodixie", "Rens", "Hek"])
        cg.addWidget(self._facility_combo)
        cg.addStretch()
        layout.addWidget(config_group)

        # 启动按钮
        btn_bar = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_bar.button(QDialogButtonBox.StandardButton.Ok).setText("启动产线")
        btn_bar.accepted.connect(self._on_start)
        btn_bar.rejected.connect(self.reject)
        layout.addWidget(btn_bar)

    def _on_start(self):
        """启动选中的产线"""
        selected = [(cb, p) for cb, p in self._plan_checks if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一条产线")
            return

        char = self._char_combo.currentText()
        facility = self._facility_combo.currentText()

        updated = 0
        conn = get_container().db.direct_connect("user")
        try:
            for _cb, plan in selected:
                pid = plan.get("id")
                if pid:
                    conn.execute(
                        "UPDATE production_plans SET status='in_progress', char_name=?, facility=? WHERE id=?",
                        (char, facility, pid),
                    )
                    updated += 1
            conn.commit()
        finally:
            conn.close()

        QMessageBox.information(
            self, "启动完成", f"已启动 {updated}/{len(selected)} 条产线\n人物: {char}\n设施: {facility}"
        )
        self.accept()

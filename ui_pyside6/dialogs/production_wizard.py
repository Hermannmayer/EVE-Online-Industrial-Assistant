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
from ui_pyside6.views.char_settings_view import get_character_list


class ProductionWizard(QDialog):
    """产线启动小助手 — 检查备料/角色/设施 → 一键启动多条产线"""

    def __init__(self, plans: list[dict], parent=None, *, mat_hangar_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("产线启动小助手")
        self.setMinimumSize(600, 500)
        self.setObjectName("production_wizard")

        self._plans = plans
        self._mat_hangar_id = mat_hangar_id

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
        """启动选中的产线（经 start_plan_batch：校验材料 → 扣减 → 写 started_at → 绑蓝图）"""
        selected = [(cb, p) for cb, p in self._plan_checks if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一条产线")
            return

        char = self._char_combo.currentText()
        facility = self._facility_combo.currentText()

        from services import plan_execution

        plans = [p for _cb, p in selected]
        res = plan_execution.start_plan_batch(
            plans,
            mat_hangar_id=self._mat_hangar_id,
            allow_short=False,
            char_name=char,
            facility=facility,
        )

        # 汇总每条计划的结果
        lines = []
        for item in res.get("results", []):
            name = item.get("plan", {}).get("product_name", "?")
            status = "✓ " if item.get("ok") else "✗ "
            lines.append(f"{status}{name}: {item.get('message', '')}")
        ok_count = res.get("ok_count", 0)
        short_plans = [r for r in res.get("results", []) if r.get("code") == "material_short"]
        msg = f"已启动 {ok_count}/{len(plans)} 条产线\n人物: {char}\n设施: {facility}"
        if lines:
            msg += "\n\n" + "\n".join(lines[:15])
        if short_plans:
            msg += "\n\n⚠ 材料不足的产线未启动，请补料后再试（或在表格右键「项目启动」强制启动）"
        QMessageBox.information(self, "启动完成", msg)
        self.accept()

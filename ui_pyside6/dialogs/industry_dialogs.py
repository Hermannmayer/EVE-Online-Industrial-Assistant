"""工业制造 — 对话框"""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)


class AddPlanDialog(QDialog):
    def __init__(self, product_name: str, score_result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"加入生产计划 — {product_name}")
        self.setMinimumWidth(420)
        self._result_data = None

        layout = QFormLayout(self)
        layout.addRow("物品:", QLabel(product_name))

        profit = score_result.get("profit_per_run", 0)
        margin = score_result.get("margin_pct", 0)
        score = score_result.get("score", 0)
        layout.addRow("评分:", QLabel(f"{score:.1f} | 利润: {profit:,.0f} ISK | 利润率: {margin:.1f}%"))

        self._runs = QSpinBox()
        self._runs.setRange(1, 10000)
        self._runs.setValue(1)
        layout.addRow("批次 (runs):", self._runs)

        self._par = QSpinBox()
        self._par.setRange(1, 100)
        self._par.setValue(1)
        layout.addRow("并行线:", self._par)

        me_te = QHBoxLayout()
        self._me = QSpinBox()
        self._me.setRange(0, 10)
        self._te = QSpinBox()
        self._te.setRange(0, 20)
        me_te.addWidget(QLabel("蓝图ME:"))
        me_te.addWidget(self._me)
        me_te.addWidget(QLabel("蓝图TE:"))
        me_te.addWidget(self._te)
        layout.addRow("蓝图参数:", me_te)

        self._char = QLineEdit()
        self._char.setPlaceholderText("角色名（可选）")
        layout.addRow("角色:", self._char)

        self._fac = QLineEdit()
        self._fac.setPlaceholderText("设施名（可选）")
        layout.addRow("设施:", self._fac)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._on_ok)
        btn.rejected.connect(self.reject)
        layout.addRow(btn)

    def _on_ok(self):
        self._result_data = {
            "runs": self._runs.value(),
            "parallels": self._par.value(),
            "me": self._me.value(),
            "te": self._te.value(),
            "char": self._char.text().strip(),
            "fac": self._fac.text().strip(),
        }
        self.accept()

    def result_data(self) -> dict | None:
        return self._result_data


class ProcurementDialog(QDialog):
    """代采购对话框"""

    def __init__(self, type_id: int, item_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"加入代采购 — {item_name}")
        self.setMinimumWidth(400)
        self._result_data = None
        self._type_id = type_id
        self._item_name = item_name

        import ui_pyside6.theme as theme

        self.setStyleSheet(f"background:{theme.BG_DARK};color:{theme.TEXT_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)

        # 物品名称（只读）
        name_edit = QLineEdit(item_name)
        name_edit.setReadOnly(True)
        name_edit.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_SECONDARY};"
            f"border:1px solid {theme.BORDER};border-radius:3px;padding:4px;"
        )
        form.addRow("物品:", name_edit)

        # 数量
        self._quantity = QSpinBox()
        self._quantity.setRange(1, 999999)
        self._quantity.setValue(1)
        self._quantity.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:3px;padding:4px;"
        )
        form.addRow("数量:", self._quantity)

        # 采购中心
        self._hub = QComboBox()
        self._hub.addItems(["Jita", "Amarr", "Dodixie", "Rens", "Hek"])
        self._hub.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:3px;padding:4px;"
        )
        form.addRow("采购中心:", self._hub)

        # 优先级
        self._priority = QComboBox()
        self._priority.addItems(["紧急", "高", "中", "低"])
        self._priority.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:3px;padding:4px;"
        )
        form.addRow("优先级:", self._priority)

        # 备注
        self._notes = QLineEdit()
        self._notes.setPlaceholderText("备注（可选）")
        self._notes.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:3px;padding:4px;"
        )
        form.addRow("备注:", self._notes)

        layout.addLayout(form)

        # 按钮
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._on_ok)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _on_ok(self):
        priority_map = {"紧急": "urgent", "高": "high", "中": "normal", "低": "low"}
        self._result_data = {
            "type_id": self._type_id,
            "name": self._item_name,
            "quantity": self._quantity.value(),
            "hub": self._hub.currentText(),
            "priority": priority_map[self._priority.currentText()],
            "notes": self._notes.text().strip(),
        }
        self.accept()

    def result_data(self) -> dict | None:
        return self._result_data

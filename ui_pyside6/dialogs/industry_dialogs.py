"""工业制造 — 对话框"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
)


class AddPlanDialog(QDialog):
    def __init__(self, product_name: str, score_result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"加入制造计划 — {product_name}")
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
        layout.addRow("流程数:", self._runs)

        self._par = QSpinBox()
        self._par.setRange(1, 100)
        self._par.setValue(1)
        layout.addRow("并行数:", self._par)

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

"""发明完成回填对话框 — 用户按游戏实际结果填写产出的 T2 BPC 流程数。

发明是概率作业，期望值只适合事前估算；完成后必须由用户回填实际结果，
否则产出记不准、后续成本与库存全错（见 docs/dev/flows.md「科研计划」）。

三个完成入口（计划表单行 / 工业页批量下线 / 采购页一键完成）都经
plan_execution.complete_plan：未回填时该函数返回 code='need_outcome' 拒绝静默完成，
由调用方弹本对话框。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

import ui_pyside6.theme as theme


class InventionOutcomeDialog(QDialog):
    """回填发明实际产出：期望流程数默认值 + 醒目的「发明失败」按钮。

    结果经 outcome() 取：{actual_output_runs: int}。取消 → None。
    """

    def __init__(
        self,
        *,
        plan_name: str,
        expected_runs: int,
        attempts: int = 0,
        decryptor_name: str = "",
        runs_per_bpc: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"发明结果回填 — {plan_name}")
        self.setMinimumWidth(430)
        self._actual: int | None = None
        self._expected = max(0, int(expected_runs))

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        form.addRow("产物:", QLabel(plan_name))
        if runs_per_bpc:
            form.addRow("每次成功产出:", QLabel(f"{runs_per_bpc} 流程"))
        if attempts:
            form.addRow("计划尝试次数:", QLabel(str(attempts)))
        if decryptor_name:
            form.addRow("解码器:", QLabel(decryptor_name))
        form.addRow("期望产出:", QLabel(f"{self._expected} 流程（按成功率估算）"))

        self._spin = QSpinBox()
        self._spin.setRange(0, 1_000_000)
        self._spin.setValue(self._expected)
        self._spin.setToolTip("按游戏里实际拿到的 T2 BPC 流程数填写；没成功就填 0")
        form.addRow("实际产出流程:", self._spin)

        self._hint = QLabel()
        self._hint.setObjectName("invention_hint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)
        self._spin.valueChanged.connect(self._refresh_hint)

        btns = QHBoxLayout()
        self._fail_btn = QPushButton("发明失败")
        self._fail_btn.setToolTip("把实际产出置 0（材料与输入蓝图流程已被消耗，这是游戏事实）")
        self._fail_btn.clicked.connect(self._on_fail)
        btns.addWidget(self._fail_btn)
        btns.addStretch(1)
        root.addLayout(btns)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("确认并完成")
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()
        self._refresh_hint()

    def outcome(self) -> int | None:
        """用户确认的实际产出流程数；取消 → None。"""
        return self._actual

    def _refresh_hint(self) -> None:
        v = self._spin.value()
        if v <= 0:
            self._hint.setText(
                "⚠ 发明失败：本次消耗的数据核心、解码器与输入蓝图流程不会退还，该计划将记为「0 流程」且不产出蓝图。"
            )
        elif self._expected and abs(v - self._expected) > max(1, self._expected // 5):
            self._hint.setText(f"⚠ 与期望值 {self._expected} 相差较大，确认游戏里实际就是这个数？")
        else:
            self._hint.setText(f"成功后产出 {v} 流程的蓝图拷贝；点击「确认并完成」写入库存。")

    def _on_fail(self) -> None:
        self._spin.setValue(0)

    def _on_ok(self) -> None:
        self._actual = int(self._spin.value())
        self.accept()

    def _on_theme_changed(self) -> None:
        for lbl in self.findChildren(QLabel):
            color = theme.ACCENT_YELLOW if lbl.objectName() == "invention_hint" else theme.TEXT_PRIMARY
            lbl.setStyleSheet(f"color: {color}; font-size: {theme.fs(12)}px;")
        self._fail_btn.setStyleSheet(
            f"color: {theme.ACCENT_RED}; font-size: {theme.fs(12)}px; "
            f"border: 1px solid {theme.ACCENT_RED}; border-radius: {theme.RADIUS}px; padding: 4px 10px;"
        )
        self._fail_btn.setCursor(Qt.CursorShape.PointingHandCursor)

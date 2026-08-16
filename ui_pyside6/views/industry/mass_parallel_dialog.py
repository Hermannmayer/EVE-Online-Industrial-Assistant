"""大规模产线并行弹窗 — 两种模式批量设置子项并行数

模式1 按可用产线数：给定总产线 N，按各子项需求轮次权重分配。
模式2 按目标工期：给定 M 天，每子项 parallels = ceil(单线总时长 / M天)。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.industry_dialog_queries import get_item_name, get_mass_parallel_data


def compute_parallel_by_lines(subitems: list[dict], total_lines: int) -> list[dict]:
    """按可用产线数分配并行数（纯函数）。

    subitems: [{id, demand, per_run, ...}]；返回 [{id, parallels}]。
    每子项至少 1 条；剩余产线按需求轮次权重（最大余数法）分配。
    """
    n = len(subitems)
    if n == 0 or total_lines <= 0:
        return [{"id": s["id"], "parallels": 1} for s in subitems]
    weights = [max(1, math.ceil(s.get("demand", 1) / max(s.get("per_run", 1), 1))) for s in subitems]
    remaining = max(0, total_lines - n)  # 先保证每子项 1 条
    total_w = sum(weights)
    if total_w <= 0 or remaining <= 0:
        return [{"id": s["id"], "parallels": 1} for s in subitems]
    ratios = [w / total_w for w in weights]
    exact = [r * remaining for r in ratios]
    alloc = [int(e) for e in exact]
    leftover = remaining - sum(alloc)
    order = sorted(range(n), key=lambda i: exact[i] - alloc[i], reverse=True)
    for k in range(leftover):
        alloc[order[k % n]] += 1
    return [{"id": s["id"], "parallels": 1 + alloc[i]} for i, s in enumerate(subitems)]


def compute_parallel_by_duration(subitems: list[dict], target_days: int) -> list[dict]:
    """按目标工期反推并行数（纯函数）。

    subitems: [{id, duration_sec(单线总时长), ...}]；返回 [{id, parallels}]。
    parallels = max(1, ceil(duration_sec / (target_days × 86400)))。
    """
    target_secs = max(int(target_days), 1) * 86400
    result = []
    for s in subitems:
        duration = int(s.get("duration_sec") or 0)
        parallels = 1 if duration <= 0 else max(1, math.ceil(duration / target_secs))
        result.append({"id": s["id"], "parallels": parallels})
    return result


class MassParallelDialog(QDialog):
    """大规模产线并行 — 按产线数 / 按目标工期"""

    def __init__(self, plans: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("大规模产线并行")
        self.resize(720, 460)
        self._plans = [p for p in plans if int(p.get("sub_level") or 0) > 0]
        self._demand: dict[int, int] = {}
        self._per_run: dict[int, int] = {}
        self._duration: dict[int, int] = {}
        self._preview: list[dict] = []  # 最近一次计算 [{id, parallels}]

        self._demand, self._per_run, self._duration = get_mass_parallel_data(get_container().db, plans, self._plans)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── 模式与参数 ──
        top = QHBoxLayout()
        top.addWidget(QLabel("模式:"))
        self._mode = QComboBox()
        self._mode.addItem("按可用产线数", "lines")
        self._mode.addItem("按目标工期", "duration")
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self._mode)

        top.addWidget(QLabel("参数:"))
        self._param = QSpinBox()
        self._param.setRange(1, 1000)
        self._param.setValue(10)
        self._param.setSuffix(" 条产线")
        top.addWidget(self._param)

        self._calc_btn = QPushButton("计算预览")
        self._calc_btn.clicked.connect(self._compute_preview)
        top.addWidget(self._calc_btn)
        top.addStretch()
        layout.addLayout(top)

        # ── 预览表 ──
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["子项", "母项需求", "当前产出", "调整后并行", "调整后产出", "校验"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 180)
        layout.addWidget(self._table, 1)

        # ── 确认 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认应用")
        btn.accepted.connect(self._on_apply)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._on_mode_changed()

    # ── 工具 ──

    def _resolve_name(self, type_id: int) -> str:
        return get_item_name(get_container().db, type_id)

    def _on_mode_changed(self) -> None:
        is_lines = self._mode.currentData() == "lines"
        self._param.setSuffix(" 条产线" if is_lines else " 天")
        self._param.setRange(1, 1000 if is_lines else 3650)
        self._param.setValue(10)

    def _compute_preview(self) -> None:
        if not self._plans:
            return
        subitems = [
            {
                "id": p["id"],
                "demand": self._demand.get(p["product_type_id"], 0),
                "per_run": self._per_run.get(p["product_type_id"], 1),
                "duration_sec": self._duration.get(p["product_type_id"], 0),
            }
            for p in self._plans
        ]
        if self._mode.currentData() == "lines":
            self._preview = compute_parallel_by_lines(subitems, self._param.value())
        else:
            self._preview = compute_parallel_by_duration(subitems, self._param.value())

        self._table.setRowCount(0)
        self._table.setRowCount(len(self._plans))
        par_by_id = {r["id"]: r["parallels"] for r in self._preview}
        any_short = False
        for row, p in enumerate(self._plans):
            pid = p["product_type_id"]
            runs = int(p.get("runs") or 1)
            parallels = par_by_id.get(p["id"], 1)
            per_run = self._per_run.get(pid, 1)
            demand = self._demand.get(pid, 0)
            output = runs * parallels * per_run
            cells = [
                self._resolve_name(pid),
                f"{demand:,}",
                f"{runs * int(p.get('parallels') or 1) * per_run:,}",
                str(parallels),
                f"{output:,}",
            ]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col >= 1:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, col, it)
            check = QTableWidgetItem("✓" if not demand or output >= demand else f"不足（还差 {demand - output:,}）")
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            check.setForeground(
                QColor(theme.ACCENT_GREEN) if (not demand or output >= demand) else QColor(theme.ACCENT_RED)
            )
            self._table.setItem(row, 5, check)
            any_short = any_short or bool(demand and output < demand)
        if any_short:
            QMessageBox.warning(self, "提示", "部分子项调整后仍不满足母项需求，请在确认前核实。")

    def _on_apply(self) -> None:
        if not self._preview:
            QMessageBox.warning(self, "提示", "请先点「计算预览」")
            return
        get_container().plan_repo.update_batch([(r["id"], {"parallels": r["parallels"]}) for r in self._preview])
        for r in self._preview:
            for p in self._plans:
                if p["id"] == r["id"]:
                    p["parallels"] = r["parallels"]
                    break
        QMessageBox.information(self, "完成", f"已更新 {len(self._preview)} 个子项的并行数")
        self.accept()

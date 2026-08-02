"""子项并行配置弹窗 — 设置每个子项的并行产线数与每条流程

校验：runs × parallels × 单流程产出 ≥ 母项需求（不足则红字并禁用确定）。
保存：逐条 UPDATE production_plans 的 runs/parallels。
"""


from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.plan_decompose import parent_needs

_COL_NAME = 0
_COL_DEMAND = 1  # 母项需求
_COL_OUTPUT = 2  # 当前产出
_COL_PAR = 3  # 并行产线数（QSpinBox）
_COL_RUNS = 4  # 每条流程（QSpinBox）
_COL_CHECK = 5  # 校验


class ChildParallelDialog(QDialog):
    """子项并行配置 — 组内子项 runs/parallels 调整 + 需求校验"""

    def __init__(self, plans: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("子项并行配置")
        self.resize(760, 480)
        self._plans = [p for p in plans if int(p.get("sub_level") or 0) > 0]
        self._demand: dict[int, int] = {}
        self._output_per_run: dict[int, int] = {}
        self._durations: dict[int, str] = {}

        with get_container().db.connect("ref", "user") as conn:
            self._demand = parent_needs(conn, plans)
            for p in self._plans:
                pid = p["product_type_id"]
                self._output_per_run[pid] = self._query_output(conn, pid)
                self._durations[pid] = self._query_duration(conn, p.get("blueprint_type_id"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        tip = QLabel("设置每个子项的并行产线数与每条流程。总产出（runs×并行×单流程产出）须 ≥ 母项需求。")
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self._table = QTableWidget(len(self._plans), 6)
        self._table.setHorizontalHeaderLabels(
            ["子项", "母项需求", "当前产出", "并行产线数", "每条流程", "校验"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._spins: list[tuple[QSpinBox, QSpinBox, QTableWidgetItem, QTableWidgetItem, dict]] = []
        for row, p in enumerate(self._plans):
            pid = p["product_type_id"]
            name = self._resolve_name(pid)
            demand = self._demand.get(pid, 0)
            runs = int(p.get("runs") or 1)
            parallels = int(p.get("parallels") or 1)
            per_run = self._output_per_run.get(pid, 1)
            output = runs * parallels * per_run
            duration = self._durations.get(pid, "")

            name_item = QTableWidgetItem(name + (f"\n时长 {duration}" if duration else ""))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, _COL_NAME, name_item)

            demand_item = self._right_item(f"{demand:,}")
            self._table.setItem(row, _COL_DEMAND, demand_item)

            output_item = self._right_item(f"{output:,}")
            self._table.setItem(row, _COL_OUTPUT, output_item)

            par_spin = QSpinBox()
            par_spin.setRange(1, 1000)
            par_spin.setValue(parallels)
            self._table.setCellWidget(row, _COL_PAR, self._centered(par_spin))

            runs_spin = QSpinBox()
            runs_spin.setRange(1, 2_000_000_000)
            runs_spin.setValue(runs)
            self._table.setCellWidget(row, _COL_RUNS, self._centered(runs_spin))

            check_item = QTableWidgetItem("")
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_CHECK, check_item)

            self._spins.append((par_spin, runs_spin, check_item, output_item, p))
            par_spin.valueChanged.connect(self._validate_row)
            runs_spin.valueChanged.connect(self._validate_row)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(_COL_NAME, 180)
        layout.addWidget(self._table, 1)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)
        self._ok_btn = btn.button(QDialogButtonBox.StandardButton.Ok)

        self._validate_all()

    # ── 工具 ──

    @staticmethod
    def _right_item(text: str) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return it

    @staticmethod
    def _centered(w: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _query_output(self, conn, product_type_id: int) -> int:
        row = conn.execute(
            "SELECT quantity FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
            (product_type_id,),
        ).fetchone()
        return int(row[0]) if row and row[0] else 1

    def _query_duration(self, conn, blueprint_type_id) -> str:
        row = conn.execute(
            "SELECT time FROM blueprint_activities WHERE blueprint_type_id=? AND activity='manufacturing' LIMIT 1",
            (blueprint_type_id,),
        ).fetchone()
        if not row or not row[0]:
            return ""
        secs = int(row[0])
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        return f"{days}d {hours}h" if days else f"{hours}h"

    def _resolve_name(self, type_id: int) -> str:
        with get_container().db.connect("ref") as conn:
            row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id=?", (type_id,)).fetchone()
        return (row[0] or row[1] or str(type_id)) if row else str(type_id)

    # ── 校验 ──

    def _validate_all(self) -> None:
        self._validate_row()

    def _validate_row(self) -> None:
        ok = True
        for _idx, (par, runs, check_item, output_item, p) in enumerate(self._spins):
            pid = p["product_type_id"]
            per_run = self._output_per_run.get(pid, 1)
            demand = self._demand.get(pid, 0)
            total = par.value() * runs.value() * per_run
            output_item.setText(f"{total:,}")
            if demand and total < demand:
                check_item.setText(f"不足（还差 {demand - total:,}）")
                check_item.setForeground(QColor(theme.ACCENT_RED))
                ok = False
            else:
                check_item.setText("✓")
                check_item.setForeground(QColor(theme.ACCENT_GREEN))
        self._ok_btn.setEnabled(ok)

    def _on_accept(self) -> None:
        conn = get_container().db.direct_connect("user")
        try:
            for par, runs, _chk, _out, p in self._spins:
                conn.execute(
                    "UPDATE production_plans SET parallels=?, runs=? WHERE id=?",
                    (par.value(), runs.value(), p["id"]),
                )
                p["parallels"] = par.value()
                p["runs"] = runs.value()
            conn.commit()
        finally:
            conn.close()
        QMessageBox.information(self, "完成", f"已更新 {len(self._spins)} 个子项的并行配置")
        self.accept()

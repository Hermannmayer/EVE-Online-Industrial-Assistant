"""
工业制造页 — 下线确认对话框（CompletePlansDialog）

把一批「待下线(ready)」计划下线：展示产物/流程/产出量，选择产出机库
（默认=设置中的默认产出机库，可改为其他机库或「不自动入库」），确认后
更新每条计划 deposit_hangar_id 并完成入库（不可逆）。
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services import plan_execution


def complete_plans(plans: list[dict], hangar_id: int) -> dict:
    """把一批 ready 计划下线到指定机库。

    hangar_id > 0 → 入库该机库；否则置 NULL（不自动入库，跳过入库仍完成）。
    每条计划先更新 deposit_hangar_id 再调用 complete_plan（幂等）。
    Returns: {"completed": int, "deposited": int, "failed": [产品名...]}
    """
    completed = 0
    deposited = 0
    failed: list[str] = []
    deposit = hangar_id if hangar_id and hangar_id > 0 else None
    for plan in plans:
        with get_container().db.connect("user") as conn:
            conn.execute(
                "UPDATE production_plans SET deposit_hangar_id=? WHERE id=?",
                (deposit, plan["id"]),
            )
        res = plan_execution.complete_plan(plan)
        if res.get("ok"):
            completed += 1
            if res.get("deposited"):
                deposited += 1
        else:
            failed.append(plan.get("product_name") or str(plan.get("id")))
    return {"completed": completed, "deposited": deposited, "failed": failed}


class CompletePlansDialog(QDialog):
    """下线确认 — 展示待下线计划清单 + 选择产出机库。"""

    _HEADERS = ["产物", "流程", "产出量", "当前机库"]

    def __init__(self, plans: list[dict], hangars: list[dict], default_hangar_id: int | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下线确认")
        self.setMinimumSize(560, 420)
        self.resize(640, 480)
        self._plans = plans
        self._hangars = hangars
        self._hangar_by_id = {h["id"]: h["name"] for h in hangars}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        tip = QLabel("以下「待下线」计划将被下线（产出成品入库，不可逆）：")
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(tip)

        # ── 计划清单表 ──
        self._table = QTableWidget(len(plans), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        total_qty = 0
        for row, p in enumerate(plans):
            name = str(p.get("product_name") or f"ID:{p.get('product_type_id', '')}")
            runs = int(p.get("runs") or 1)
            parallels = int(p.get("parallels") or 1)
            qty = runs * parallels * plan_execution.output_per_run(p.get("product_type_id") or 0)
            total_qty += qty
            dep = p.get("deposit_hangar_id")
            dep_name = self._hangar_by_id.get(dep) if dep and dep > 0 else "不自动入库"
            for col, text in [(0, name), (1, f"{runs}X{parallels}"), (2, f"{qty:,}"), (3, dep_name)]:
                it = QTableWidgetItem(str(text))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col >= 1:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, it)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 200)
        layout.addWidget(self._table, 1)

        # ── 产出机库选择 ──
        hangar_row = QHBoxLayout()
        hangar_row.addWidget(QLabel("产出机库:"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.addItem("不自动入库", -1)
        for h in hangars:
            self._hangar_combo.addItem(h["name"], h["id"])
        # 默认：设置的默认产出机库 → 否则第一个机库
        idx = -1
        if default_hangar_id and default_hangar_id > 0 and default_hangar_id in self._hangar_by_id:
            idx = self._hangar_combo.findData(default_hangar_id)
        if idx < 0 and hangars:
            idx = 1  # 第一个机库
        if idx >= 0:
            self._hangar_combo.setCurrentIndex(idx)
        hangar_row.addWidget(self._hangar_combo, 1)
        layout.addLayout(hangar_row)

        # ── 汇总 ──
        self._summary = QLabel(f"共 {len(plans)} 项计划，产出 {total_qty:,} 件")
        self._summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._summary)

        # ── 按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认下线")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    def selected_hangar_id(self) -> int:
        """返回选中的机库 id（-1 = 不自动入库）"""
        return cast(int, self._hangar_combo.currentData())

    def _on_theme_changed(self):
        pass

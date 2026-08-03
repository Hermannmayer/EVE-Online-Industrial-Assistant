"""母项拆解弹窗 — 递归拆解预览 + 确认落库子项产线

把母项产品递归拆成子项产线（sub_level 逐级 +1），预览后写入 production_plans，
母项 sub_level=0、同 group_number。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.plan_decompose import decompose_plan


class ParentDecomposeDialog(QDialog):
    """母项拆解 — 预览子项产线并确认拆解落库"""

    _HEADERS = ["组件", "层", "流程", "并行", "ME-TE", "蓝图"]

    def __init__(self, plan: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"母项拆解 — {plan.get('product_name', '')}")
        self.resize(680, 480)
        self._plan = plan
        self._mat_hangar_id = plan.get("mat_hangar_id")
        self._lines = decompose_plan(plan, mat_hangar_id=self._mat_hangar_id)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        gnum = self._target_group_number()
        group_label = QLabel(f"将拆解到组号 <b>{gnum}</b>，共 <b>{len(self._lines)}</b> 个子项产线")
        group_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 13px;")
        layout.addWidget(group_label)

        if not self._lines:
            info = QLabel("该产品无中间组件可拆解（直接材料均可外购）。")
            info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            layout.addWidget(info)
            btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btn.rejected.connect(self.close)
            layout.addWidget(btn)
            return

        # ── 预览表 ──
        self._table = QTableWidget(len(self._lines), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        for i, line in enumerate(self._lines):
            name = self._resolve_name(line["product_type_id"])
            cells = [
                name,
                str(line["sub_level"]),
                str(line["runs"]),
                str(line["parallels"]),
                f"{line['me_level']}-{line['te_level']}",
                "有蓝图" if line["has_blueprint"] else "无蓝图",
            ]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 5 and not line["has_blueprint"]:
                    it.setForeground(QColor(theme.ACCENT_RED))
                self._table.setItem(i, col, it)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 200)
        layout.addWidget(self._table, 1)

        tip = QLabel("提示：无蓝图的行需先买入对应蓝图才能运行。库存已有的组件会自动少造。")
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(tip)

        # ── 按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认拆解")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _target_group_number(self) -> int:
        existing = int(self._plan.get("group_number") or 0)
        if existing > 0:
            return existing
        with get_container().db.connect("user") as conn:
            row = conn.execute("SELECT COALESCE(MAX(group_number),0) FROM production_plans").fetchone()
        return int(row[0]) + 1

    def _resolve_name(self, type_id: int) -> str:
        with get_container().db.connect("ref") as conn:
            row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id=?", (type_id,)).fetchone()
        return (row[0] or row[1] or str(type_id)) if row else str(type_id)

    def _on_accept(self) -> None:
        gnum = self._target_group_number()
        from services import inventory_manager

        # 从材料机库带出星系（避免子计划空星系 → 回退吉他 SCI）
        solar_system_id = inventory_manager.get_hangar_system_id(self._mat_hangar_id)
        conn = get_container().db.direct_connect("user")
        try:
            if self._plan.get("id"):
                conn.execute(
                    "UPDATE production_plans SET group_number=?, sub_level=0 WHERE id=?",
                    (gnum, self._plan["id"]),
                )
                self._plan["group_number"] = gnum
                self._plan["sub_level"] = 0
                self._plan["group_id"] = gnum
                self._plan["child_level"] = 0
            for line in self._lines:
                name = self._resolve_name(line["product_type_id"])
                existing = conn.execute(
                    "SELECT id FROM production_plans WHERE group_number=? AND product_type_id=?",
                    (gnum, line["product_type_id"]),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE production_plans SET runs=? WHERE id=?", (line["runs"], existing[0])
                    )
                else:
                    conn.execute(
                        "INSERT INTO production_plans (product_type_id, product_name, blueprint_type_id, "
                        "runs, parallels, me_level, te_level, status, group_number, sub_level, mat_hangar_id, "
                        "solar_system_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            line["product_type_id"],
                            name,
                            line["blueprint_type_id"],
                            line["runs"],
                            line["parallels"],
                            line["me_level"],
                            line["te_level"],
                            "pending",
                            gnum,
                            line["sub_level"],
                            self._mat_hangar_id,
                            solar_system_id,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        QMessageBox.information(self, "完成", f"已拆解 {len(self._lines)} 个子项产线到组号 {gnum}")
        self.accept()

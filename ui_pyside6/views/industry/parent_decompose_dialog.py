"""母项拆解弹窗 — 递归拆解预览 + 确认落库子项产线（支持多母项）

把选中母项产品递归拆成子项产线（sub_level 逐级 +1），预览后写入 production_plans，
每个母项 sub_level=0、同 group_number（已有组号复用，否则从 MAX+1 起分配互不重复号）。
"""

from __future__ import annotations

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
    """母项拆解 — 预览子项产线并确认拆解落库（多母项批量）"""

    _HEADERS = ["组号", "组件", "层", "需求", "流程", "并行", "ME-TE", "蓝图"]

    def __init__(self, plans: list[dict], parent=None):
        super().__init__(parent)
        self._plans = [p for p in plans if int(p.get("sub_level") or p.get("child_level") or 0) == 0]
        # 组号一次分配并存储（不在 _on_accept 重查 MAX，防弹窗显示期间新组号竞态）
        self._assignments = self._allocate_and_decompose()

        n_parents = len(self._plans)
        n_groups = len({gnum for _, gnum, _ in self._assignments})
        self._total_lines = sum(len(lines) for _, _, lines in self._assignments)

        self.setWindowTitle(f"母项拆解 ({n_parents} 个母项)")
        self.resize(700, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        group_label = QLabel(
            f"将拆解 <b>{len(self._assignments)}</b> 个母项到 <b>{n_groups}</b> 个组，"
            f"共 <b>{self._total_lines}</b> 个子项产线"
        )
        group_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 13px;")
        layout.addWidget(group_label)

        if not self._assignments:
            info = QLabel("所选母项均无中间组件可拆解（直接材料均可外购）。")
            info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            layout.addWidget(info)
            btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btn.rejected.connect(self.close)
            layout.addWidget(btn)
            return

        # ── 预览表 ──
        self._table = QTableWidget(self._total_lines, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        row_idx = 0
        for _plan, gnum, lines in self._assignments:
            for line in lines:
                name = self._resolve_name(line["product_type_id"])
                cells = [
                    str(gnum),
                    name,
                    str(line["sub_level"]),
                    f"{line.get('demand', 0):,}",
                    str(line["runs"]),
                    str(line["parallels"]),
                    f"{line['me_level']}-{line['te_level']}",
                    "有蓝图" if line["has_blueprint"] else "无蓝图",
                ]
                for col, text in enumerate(cells):
                    it = QTableWidgetItem(text)
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col != 1:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col == 7 and not line["has_blueprint"]:
                        it.setForeground(QColor(theme.ACCENT_RED))
                    self._table.setItem(row_idx, col, it)
                row_idx += 1
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(1, 200)
        layout.addWidget(self._table, 1)

        tip = QLabel(
            "提示：每个子项的「流程」按母项对它的需求自动生成（需求 ÷ 单轮产出，向上取整），"
            "总产出 ≈ 需求（1X）。无蓝图的行需先买入对应蓝图才能运行。库存已有的组件会自动少造。"
        )
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(tip)

        # ── 按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认拆解")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _allocate_and_decompose(self) -> list[tuple[dict, int, list[dict]]]:
        """为每个可拆母项分配组号并拆解 → [(plan, gnum, lines)]。

        已有 group_number>0 的母项复用原组号；无组号的从 MAX(group_number)+1 起
        分配互不重复的号。lines 为空的母项跳过（不分配组号、不落库）。
        """
        decomposable: list[tuple[dict, list[dict]]] = []
        for plan in self._plans:
            lines = decompose_plan(plan, mat_hangar_id=plan.get("mat_hangar_id"))
            if lines:
                decomposable.append((plan, lines))

        existing = {int(p.get("group_number") or 0) for p, _ in decomposable if int(p.get("group_number") or 0) > 0}
        with get_container().db.connect("user") as conn:
            row = conn.execute("SELECT COALESCE(MAX(group_number),0) FROM production_plans").fetchone()
        next_g = int(row[0]) + 1

        assignments: list[tuple[dict, int, list[dict]]] = []
        for plan, lines in decomposable:
            gnum = int(plan.get("group_number") or 0)
            if gnum <= 0:
                while next_g in existing:
                    next_g += 1
                gnum = next_g
                existing.add(next_g)
                next_g += 1
            assignments.append((plan, gnum, lines))
        return assignments

    def _resolve_name(self, type_id: int) -> str:
        with get_container().db.connect("ref") as conn:
            row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id=?", (type_id,)).fetchone()
        return (row[0] or row[1] or str(type_id)) if row else str(type_id)

    def _on_accept(self) -> None:
        from services import inventory_manager

        repo = get_container().plan_repo
        for plan, gnum, lines in self._assignments:
            # 从材料机库带出星系（避免子计划空星系 → 回退吉他 SCI）
            solar_system_id = inventory_manager.get_hangar_system_id(plan.get("mat_hangar_id"))
            if plan.get("id"):
                repo.update(plan["id"], group_number=gnum, sub_level=0)
                plan["group_number"] = gnum
                plan["sub_level"] = 0
                plan["group_id"] = gnum
                plan["child_level"] = 0
            for line in lines:
                name = self._resolve_name(line["product_type_id"])
                existing_id = repo.find_by_group_product(gnum, line["product_type_id"])
                if existing_id:
                    # 重跑拆解：按新 line 整体刷新 runs/parallels/ME-TE，避免残留旧并行数导致超量
                    repo.update(
                        existing_id,
                        runs=line["runs"],
                        parallels=line["parallels"],
                        me_level=line["me_level"],
                        te_level=line["te_level"],
                        materials_ready=1,
                    )
                else:
                    repo.insert_child_plan(
                        product_type_id=line["product_type_id"],
                        product_name=name,
                        blueprint_type_id=line["blueprint_type_id"],
                        runs=line["runs"],
                        parallels=line["parallels"],
                        me_level=line["me_level"],
                        te_level=line["te_level"],
                        group_number=gnum,
                        sub_level=line["sub_level"],
                        mat_hangar_id=plan.get("mat_hangar_id"),
                        solar_system_id=solar_system_id,
                    )
        QMessageBox.information(self, "完成", f"已拆解 {self._total_lines} 个子项产线")
        self.accept()

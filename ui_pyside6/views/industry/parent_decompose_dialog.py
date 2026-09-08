"""母项拆解弹窗 — 递归拆解预览 + 确认落库子项产线（支持多母项）

把选中母项产品递归拆成子项产线（sub_level 逐级 +1），每行预览需求/流程/利润，
可删除选中行（本轮不内造该组件、改外购），确认后写入 production_plans，
每个母项 sub_level=0、同 group_number（已有组号复用，否则从 MAX+1 起分配互不重复号）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.industry_dialog_queries import get_item_name, get_max_group_number
from services.plan_decompose import collect_removed_child_ids, decompose_plan


class ParentDecomposeDialog(QDialog):
    """母项拆解 — 预览子项产线并确认拆解落库（多母项批量）"""

    _HEADERS = ["组号", "组件", "层", "需求", "流程", "并行", "ME-TE", "利润", "蓝图"]

    def __init__(
        self,
        plans: list[dict],
        parent=None,
        *,
        price_settings: dict | None = None,
        default_char_name: str = "",
    ):
        super().__init__(parent)
        self._plans = [p for p in plans if int(p.get("sub_level") or p.get("child_level") or 0) == 0]
        self._price_settings = price_settings or {}
        self._default_char_name = default_char_name or ""
        self._removed_types: set[int] = set()
        # 组号一次分配并存储（不在 _on_accept 重查 MAX，防弹窗显示期间新组号竞态）
        self._assignments = self._allocate_and_decompose()
        self._row_refs: list[tuple[int, int, dict]] = []

        n_parents = len(self._plans)

        self.setWindowTitle(f"母项拆解 ({n_parents} 个母项)")
        self.resize(760, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._group_label = QLabel()
        self._group_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: {theme.fs(13)}px;")
        layout.addWidget(self._group_label)

        if not self._assignments:
            self._group_label.setText("将拆解 <b>0</b> 个母项")
            info = QLabel("所选母项均无中间组件可拆解（直接材料均可外购）。")
            info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            layout.addWidget(info)
            btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btn.rejected.connect(self.close)
            layout.addWidget(btn)
            return

        # ── 预览表 ──
        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setVisible(False)
        self._profit_cache: dict[tuple, float | None] = {}
        for a_idx, (_plan, gnum, lines) in enumerate(self._assignments):
            for line in lines:
                self._append_row(a_idx, gnum, line)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(1, 200)
        layout.addWidget(self._table, 1)

        tip = QLabel(
            "提示：每个子项的「流程」按母项对它的需求自动生成（需求 ÷ 单轮产出，向上取整），"
            "总产出 ≈ 需求（1X）。「利润」按成品价−材料−作业费估算（随价格上下文变化）。"
            "删除一行 = 本轮不内造该组件（改外购）；下次显式「拆解/重算子项」仍会按需求重建。"
            "无蓝图的行需先买入对应蓝图才能运行。库存已有的组件会自动少造。"
        )
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
        layout.addWidget(tip)

        # ── 删除按钮行 ──
        del_row = QHBoxLayout()
        self._del_btn = QPushButton("删除选中行")
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.clicked.connect(self._delete_selected_rows)
        del_row.addWidget(self._del_btn)
        del_row.addStretch(1)
        layout.addLayout(del_row)

        # ── 按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认拆解")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._refresh_summary()

    def _append_row(self, a_idx: int, gnum: int, line: dict) -> None:
        """按一行拆解预览行；记录 _row_refs 供删除反向定位。"""
        row_idx = self._table.rowCount()
        self._table.insertRow(row_idx)
        name = self._resolve_name(line["product_type_id"])
        profit = self._line_profit(a_idx, line)
        cells = [
            str(gnum),
            name,
            str(line["sub_level"]),
            f"{line.get('demand', 0):,}",
            str(line["runs"]),
            str(line["parallels"]),
            f"{line['me_level']}-{line['te_level']}",
            f"{profit:,.0f}" if profit is not None else "—",
            "有蓝图" if line["has_blueprint"] else "无蓝图",
        ]
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col != 1:
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 8 and not line["has_blueprint"]:
                it.setForeground(QColor(theme.ACCENT_RED))
            elif col == 7 and isinstance(profit, int | float) and profit < 0:
                it.setForeground(QColor(theme.ACCENT_RED))
            self._table.setItem(row_idx, col, it)
        self._row_refs.append((a_idx, len(self._assignments[a_idx][2]) - 1, line))

    def _line_profit(self, a_idx: int, line: dict) -> float | None:
        """预估单条子项产线利润（成品卖价 − 材料 − 作业费）。失败返回 None 显示 —。"""
        mother = self._assignments[a_idx][0]
        key = (line["product_type_id"], line.get("me_level", 0), line.get("te_level", 0), line.get("runs", 1))
        if key in self._profit_cache:
            return self._profit_cache[key]
        try:
            from services.char_config_resolver import resolve_char_config
            from services.scoring_service import ScoringService

            char_name = (mother.get("char_name") or "").strip() or self._default_char_name
            char_config = resolve_char_config(char_name=char_name) if char_name else {}
            plan_data = {
                "product_type_id": line["product_type_id"],
                "me_level": line.get("me_level", 0) or 0,
                "te_level": line.get("te_level", 0) or 0,
                "runs": line.get("runs", 1) or 1,
                "parallels": line.get("parallels", 1) or 1,
                "solar_system_id": mother.get("solar_system_id"),
                "mat_hangar_id": mother.get("mat_hangar_id"),
            }
            metrics = ScoringService.calculate_plan_metrics(
                plan_data,
                char_config,
                mat_hub=self._price_settings.get("mat_hub"),
                sell_hub=self._price_settings.get("prod_hub"),
                price_type_mat=self._price_settings.get("mat_price_type"),
                price_type_prod=self._price_settings.get("prod_price_type"),
                system_id=mother.get("solar_system_id"),
            )
            profit = metrics.get("profit")
            result = float(profit) if isinstance(profit, int | float) else None
        except Exception:
            result = None
        self._profit_cache[key] = result
        return result

    def _refresh_summary(self) -> None:
        with_lines = [a for a in self._assignments if a[2]]
        n_mothers = len(with_lines)
        n_groups = len({gnum for _p, gnum, lines in with_lines if lines})
        n_lines = sum(len(lines) for _, _, lines in with_lines)
        self._group_label.setText(
            f"将拆解 <b>{n_mothers}</b>/<b>{len(self._assignments)}</b> 个母项到 "
            f"<b>{n_groups}</b> 个组，共 <b>{n_lines}</b> 个子项产线"
        )

    def _delete_selected_rows(self) -> None:
        """删除选中行：从预览表、_assignments、_row_refs 一致移除，并记录到 _removed_types。"""
        selected = sorted({r.row() for r in self._table.selectedItems()}, reverse=True)
        if not selected:
            QMessageBox.information(self, "提示", "请先在表格中选中要删除的行")
            return
        n_before = len(self._row_refs)
        for row in selected:
            a_idx, l_idx, line = self._row_refs[row]
            tid = int(line.get("product_type_id") or 0)
            if tid:
                self._removed_types.add(tid)
            del self._assignments[a_idx][2][l_idx]
            self._table.removeRow(row)
        self._rebuild_row_refs()
        if self._row_refs:
            self._table.clearSelection()
        self._refresh_summary()
        self._del_btn.setText(f"删除选中行（已删 {n_before - len(self._row_refs)}）")

    def _rebuild_row_refs(self) -> None:
        """平铺 rows 与 assignments 行对齐（删除后行号漂移，重建映射）。"""
        refs: list[tuple[int, int, dict]] = []
        for a_idx, (_plan, _gnum, lines) in enumerate(self._assignments):
            for l_idx, line in enumerate(lines):
                refs.append((a_idx, l_idx, line))
        self._row_refs = refs

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
        next_g = get_max_group_number(get_container().db) + 1

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
        return get_item_name(get_container().db, type_id)

    def _on_accept(self) -> None:
        repo = get_container().plan_repo
        for plan, gnum, _lines in self._assignments:
            # 母项落组号（供 UI 折叠归组）；子项由 rebuild_children 统一生成/合并
            if plan.get("id"):
                repo.update(plan["id"], group_number=gnum, sub_level=0)
                plan["group_number"] = gnum
                plan["sub_level"] = 0
                plan["group_id"] = gnum
                plan["child_level"] = 0

        # 按全局引用式需求重放子项：共享组件跨母项合并为一行，需求=所有母项之和。
        # 拆解模式 create+prune：补建缺失子项、清理不再被引用的旧子项。
        from services.plan_rebuild import rebuild_children

        res = rebuild_children(create=True, prune=True)

        # 预览中删除的行 → 确认后按 组内血缘 删掉对应子项产线（本轮不内造，改外购）
        removed = self._remove_planning_discarded(self._removed_types)
        msg = f"已重算子项产线：新增 {res['created']}、更新 {res['updated']}、清理 {res['deleted']} 条"
        if removed:
            msg += f"，未建 {removed} 条"
        QMessageBox.information(self, "完成", msg)
        self.accept()

    def _remove_planning_discarded(self, removed_types: set[int]) -> int:
        """删除被用户在预览中移除的组件对应的子项产线（含同组子孙）。返回删除行数。"""
        removed_types = {t for t in removed_types if t}
        if not removed_types:
            return 0
        from core.logger import log
        from services import plan_execution

        with get_container().db.connect("user") as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, product_type_id, group_number, sub_level, component_parent_type_id "
                    "FROM production_plans WHERE sub_level > 0"
                ).fetchall()
            ]
        ids = collect_removed_child_ids(rows, removed_types)
        if not ids:
            return 0
        for pid in ids:
            try:
                plan_execution.release_blueprint(pid)
            except Exception:
                log.warning("释放被删子项 %s 蓝图绑定失败", pid, exc_info=True)
        get_container().plan_repo.delete_many(sorted(ids))
        return len(ids)

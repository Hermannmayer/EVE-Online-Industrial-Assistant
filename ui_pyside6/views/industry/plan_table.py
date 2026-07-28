"""生产计划表格 — PlanTable 视图组件"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHeaderView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.logger import log
from ui_pyside6.models.industry_models import PlanTableModel

# ── 列索引常量（与 PlanTableModel._HEADERS 对齐） ────────────
COL_CHECKBOX = 0
COL_ICON = 1
COL_PRODUCT = 2
COL_NOTES = 3
COL_BATCH = 4
COL_PARALLELS = 5
COL_GROUP = 6
COL_CHILD_LEVEL = 7
COL_STATUS = 8
COL_CHAR_NAME = 9
COL_RUNS = 10
COL_BLUEPRINT = 11
COL_TIME = 12
COL_OUTPUT_RATE = 13
COL_FACILITY = 14
COL_OUTPUT = 15
COL_COST = 16
COL_PROFIT = 17
COL_MARKET_MARGIN = 18
COL_PERSONAL_MARGIN = 19

_NUM_COLUMNS = 20


class PlanTable(QWidget):
    """生产计划表格 — 封装 QTableView + PlanTableModel + 右键菜单"""

    plan_updated = Signal()
    refresh_requested = Signal()
    plan_detail_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # ── 布局 ─────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.verticalHeader().setVisible(False)
        self._configure_adaptive_columns()

        layout.addWidget(self._table)

        self._model: PlanTableModel | None = None

        # ── 连接信号 ─────────────────────────────────────────
        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table.clicked.connect(self._on_cell_clicked)

        # ── 头部右键菜单（列可见性控制） ─────────────────────
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(self._on_header_context_menu)

        # ── 行右键菜单 ───────────────────────────────────────
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        # ── 主题 ─────────────────────────────────────────────
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── 公共方法 ──────────────────────────────────────────────

    def _configure_adaptive_columns(self) -> None:
        """配置列宽自适应：窄列固定，产品列拉伸，其余自适应内容"""
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(24)

        # 隐藏并行和批次列（数据仍保留用于计算）
        self._table.setColumnHidden(COL_BATCH, True)
        self._table.setColumnHidden(COL_PARALLELS, True)

        NARROW = {1, 6, 7}  # 图标/组号/子级
        STRETCH = {2}  # 产品名
        FIXED = {0}  # 勾选列固定 24px

        for col in range(_NUM_COLUMNS):
            if col in FIXED:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                header.resizeSection(col, 24)
            elif col in NARROW:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            elif col in STRETCH:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(col, 75)

    def set_model(self, model: PlanTableModel) -> None:
        """设置 PlanTableModel 并自适应列宽"""
        self._model = model
        self._table.setModel(model)
        # 内容自适应后，窄列自动收缩
        self._table.resizeColumnsToContents()
        header = self._table.horizontalHeader()
        # 确保产品列至少有 120px，但不超过可用空间一半
        product_w = header.sectionSize(COL_PRODUCT)
        avail = header.width() if header.width() > 0 else 800
        header.resizeSection(COL_PRODUCT, max(120, min(product_w, avail // 2)))

    def get_model(self) -> PlanTableModel | None:
        return self._model

    def get_table(self) -> QTableView:
        return self._table

    def load_plans(self, plans: list[dict]) -> None:
        """创建新 PlanTableModel 并设置"""
        model = PlanTableModel(plans)
        self.set_model(model)

    # ── 双击事件 ─────────────────────────────────────────────

    def _on_double_clicked(self, index) -> None:
        """双击 → 直接打开编辑生产计划"""
        row = index.row()
        if self._model:
            self._edit_plan(row)

    # ── 头部右键菜单（列可见性控制） ─────────────────────────

    def _on_header_context_menu(self, pos) -> None:
        """右键表头 → 列可见性切换菜单"""
        if not self._model:
            return

        menu = QMenu(self)
        headers = PlanTableModel._HEADERS
        checks: list[QCheckBox] = []

        for col_idx, name in enumerate(headers):
            cb = QCheckBox(name)
            is_hidden = self._table.isColumnHidden(col_idx)
            cb.setChecked(not is_hidden)
            checks.append(cb)

            action = QWidgetAction(menu)
            action.setDefaultWidget(cb)
            menu.addAction(action)

            cb.toggled.connect(lambda checked, c=col_idx, cs=checks: self._toggle_column(c, checked, cs))

        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    def _toggle_column(self, col: int, visible: bool, checks: list[QCheckBox]) -> None:
        """切换列可见性，但至少保留 1 列"""
        if not visible:
            visible_count = sum(1 for c in range(_NUM_COLUMNS) if c != col and not self._table.isColumnHidden(c))
            if visible_count == 0:
                checks[col].blockSignals(True)
                checks[col].setChecked(True)
                checks[col].blockSignals(False)
                return
        self._table.setColumnHidden(col, not visible)

    # ── 行右键菜单 ────────────────────────────────────────────

    def _on_table_context_menu(self, pos) -> None:
        """右键行 → 操作菜单"""
        index = self._table.indexAt(pos)
        if not index.isValid() or not self._model:
            return

        row = index.row()
        plan = self._model.get_plan(row)
        if not plan:
            return

        menu = QMenu(self)

        # ── 编辑 ─────────────────────────────────────────
        menu.addAction("编辑生产计划", lambda: self._edit_plan(row))
        menu.addSeparator()

        # ── 查看 ─────────────────────────────────────────
        menu.addAction("查看核算", lambda: self._view_cost_breakdown(row))
        menu.addAction("查看物品详情", lambda: self._view_item_details(row))
        menu.addSeparator()

        # ── 状态 ─────────────────────────────────────────
        # 备料 toggle
        mats_ready = bool(plan.get("materials_ready", 0))
        if mats_ready:
            a = menu.addAction("取消勾选备料")
        else:
            a = menu.addAction("勾选备料")
        a.triggered.connect(lambda r=row, v=not mats_ready: self._set_materials_ready(r, int(v)))
        menu.addAction("项目启动", lambda: self._set_status(row, "in_progress"))
        menu.addAction("待下线", lambda: self._set_status(row, "ready"))
        menu.addAction("项目完成", lambda: self._set_status(row, "completed"))
        menu.addSeparator()

        # ── 备注 ─────────────────────────────────────────
        menu.addAction("添加备注", lambda: self._add_notes(row))
        menu.addAction("复制蓝图名称", lambda: self._copy_blueprint_name(row))
        menu.addSeparator()

        # ── 高级 ─────────────────────────────────────────
        menu.addAction("查看蓝图原图的NPC卖家", lambda: self._show_npc_seller(row))
        menu.addAction("产线启动小助手", lambda: self._show_production_wizard(row))

        smart_menu = menu.addMenu("智能调整")
        a = smart_menu.addAction("母项智能调整")
        a.triggered.connect(lambda r=row: self._smart_adjust_parent(r))
        a = smart_menu.addAction("子项智能调整")
        a.triggered.connect(lambda r=row: self._smart_adjust_children(r))
        a = smart_menu.addAction("子项大规模产线并行")
        a.triggered.connect(lambda r=row: self._smart_parallel_children(r))

        fac_menu = menu.addMenu("设施设置")
        a = fac_menu.addAction("为设施设置所在星系")
        a.triggered.connect(lambda r=row: self._set_facility_system(r))
        a = fac_menu.addAction("为设施所在星系设置成本系数")
        a.triggered.connect(lambda r=row: self._set_facility_cost_index(r))

        menu.addSeparator()

        # ── 危险操作 ─────────────────────────────────────
        a = menu.addAction("删除行")
        a.triggered.connect(lambda r=row: self._delete_row(r))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── 单击事件 ─────────────────────────────────────────────

    def _on_cell_clicked(self, index) -> None:
        """单击勾选列 → 切换备料状态"""
        if index.column() == COL_CHECKBOX and self._model:
            row = index.row()
            plan = self._model.get_plan(row)
            if plan:
                new_val = 0 if plan.get("materials_ready", 0) else 1
                self._set_materials_ready(row, new_val)

    def _edit_plan(self, row: int) -> None:
        """编辑生产计划 — 打开 PlanEditDialog"""
        if self._model is None:
            return
        from ui_pyside6.views.industry import PlanEditDialog

        plan = self._model.get_plan(row)
        if not plan:
            return
        dlg = PlanEditDialog(self, plan)
        if dlg.exec():
            updated = dlg.get_updated_data()
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute(
                    "UPDATE production_plans SET runs=?, parallels=?, me_level=?, te_level=?, "
                    "char_name=?, facility=?, output_location=?, mat_hub=?, notes=? WHERE id=?",
                    (
                        updated["runs"],
                        updated["parallels"],
                        updated["me_level"],
                        updated["te_level"],
                        updated["char_name"],
                        updated["facility"],
                        updated["output"],
                        updated["material_hub"],
                        updated["notes"],
                        plan["id"],
                    ),
                )
                conn.commit()
                # 更新内存模型
                plan["runs"] = updated["runs"]
                plan["parallels"] = updated["parallels"]
                plan["me_level"] = updated["me_level"]
                plan["te_level"] = updated["te_level"]
                plan["char_name"] = updated["char_name"]
                plan["facility"] = updated["facility"]
                plan["output"] = updated["output"]
                plan["notes"] = updated["notes"]
            finally:
                conn.close()
            self._model.layoutChanged.emit()
            self.plan_updated.emit()

    def _add_notes(self, row: int) -> None:
        """添加备注 — 弹出文本输入框"""
        if self._model is None:
            return
        from PySide6.QtWidgets import QInputDialog

        plan = self._model.get_plan(row)
        if not plan:
            return
        current = plan.get("notes", "") or ""
        text, ok = QInputDialog.getMultiLineText(self, "添加备注", "输入备注内容:", current)
        if ok:
            plan["notes"] = text.strip()
            self._model.layoutChanged.emit()
            if plan.get("id"):
                conn = get_container().db.direct_connect("user")
                try:
                    conn.execute("UPDATE production_plans SET notes=? WHERE id=?", (text.strip(), plan["id"]))
                    conn.commit()
                finally:
                    conn.close()
            self.plan_updated.emit()

    def _modify_runs(self, row: int) -> None:
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        current = int(plan.get("runs", 0))
        val, ok = QInputDialog.getInt(self, "修改流程数", "流程数:", current, 1, 99999)
        if ok:
            # 按比值即时更新时长和产能
            if current > 0:
                ratio = val / current
                plan["calculated_time"] = round(plan.get("calculated_time", 0) * ratio)
                plan["daily_output"] = plan.get("daily_output", 0) / ratio if ratio > 0 else 0
            plan["runs"] = val
            self._model.layoutChanged.emit()
            if plan.get("id"):
                conn = get_container().db.direct_connect("user")
                try:
                    conn.execute("UPDATE production_plans SET runs=? WHERE id=?", (val, plan["id"]))
                    conn.commit()
                finally:
                    conn.close()
            self.plan_updated.emit()

    def _modify_parallels(self, row: int) -> None:
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        current = int(plan.get("parallels", 1))
        val, ok = QInputDialog.getInt(self, "修改并行数", "并行数:", current, 1, 99999)
        if ok:
            val = max(1, val)
            # 按比值即时更新时长（并行只影响时长公式中的总流程，不增加实际耗时）
            if current > 0 and val > 0:
                ratio = val / current
                plan["daily_output"] = plan.get("daily_output", 0) * ratio if plan.get("daily_output", 0) else 0
            plan["parallels"] = val
            self._model.layoutChanged.emit()
            if plan.get("id"):
                conn = get_container().db.direct_connect("user")
                try:
                    conn.execute("UPDATE production_plans SET parallels=? WHERE id=?", (val, plan["id"]))
                    conn.commit()
                finally:
                    conn.close()
            self.plan_updated.emit()

    def _copy_blueprint_name(self, row: int) -> None:
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        bp_name = plan.get("blueprint_name") or plan.get("product_name", "")
        if bp_name:
            QApplication.clipboard().setText(bp_name)

    def _set_materials_ready(self, row: int, value: int) -> None:
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        plan["materials_ready"] = value
        self._model.layoutChanged.emit()
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute("UPDATE production_plans SET materials_ready=? WHERE id=?", (value, plan["id"]))
                conn.commit()
            finally:
                conn.close()
        self.plan_updated.emit()

    def _set_status(self, row: int, status: str) -> None:
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        plan["status"] = status
        self._model.layoutChanged.emit()
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                # 如果状态改为 completed 且尚未入库，自动入库
                deposit_hangar_id = plan.get("deposit_hangar_id")
                deposited = plan.get("deposited", 0)
                if status == "completed" and not deposited and deposit_hangar_id:
                    self._auto_deposit(conn, plan)
                # 如果状态从 completed 改回，重置 deposited
                elif status != "completed" and deposited:
                    plan["deposited"] = 0
                    conn.execute("UPDATE production_plans SET deposited=0 WHERE id=?", (plan["id"],))

                conn.execute(
                    "UPDATE production_plans SET status=?, deposited=? WHERE id=?",
                    (status, plan.get("deposited", 0), plan["id"]),
                )
                conn.commit()
            finally:
                conn.close()
        self.plan_updated.emit()

    def _auto_deposit(self, conn, plan: dict) -> None:
        """自动将成品加入目标机库，更新 deposited 标记"""
        from services.inventory_manager import add_item

        try:
            product_type_id = plan.get("product_type_id")
            runs = max(int(plan.get("runs", 1)), 1)
            parallels = max(int(plan.get("parallels", 1)), 1)
            hangar_id = plan.get("deposit_hangar_id")
            if not hangar_id or not product_type_id:
                return

            # 查询蓝图单流程产出
            ref_conn = get_container().db.direct_connect("ref")
            cur = ref_conn.cursor()
            cur.execute(
                "SELECT quantity FROM blueprint_products WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                (product_type_id,),
            )
            row = cur.fetchone()
            ref_conn.close()
            output_per_run = row[0] if row else 1

            total_qty = runs * parallels * output_per_run
            # 成本价 = material_cost / 总数量（每个成品的加权成本）
            mat_cost = plan.get("material_cost", 0) or 0
            cost_price = mat_cost / max(total_qty, 1)

            add_item(hangar_id, product_type_id, total_qty, round(cost_price, 2))
            plan["deposited"] = 1
        except Exception:
            log.exception("自动入库失败: plan_id=%s", plan.get("id"))

    def _delete_row(self, row: int) -> None:
        if self._model is None:
            return
        if 0 <= row < len(self._model._plans):
            plan = self._model._plans[row]
            if plan.get("id"):
                conn = get_container().db.direct_connect("user")
                try:
                    conn.execute("DELETE FROM production_plans WHERE id=?", (plan["id"],))
                    conn.commit()
                finally:
                    conn.close()
            self._model.beginResetModel()
            self._model._plans.pop(row)
            self._model.endResetModel()
            self.plan_updated.emit()

    # ── Phase 3 占位 ────────────────────────────────────────

    def _view_item_details(self, row: int):
        # 查看物品详情: 打开 MatDlg 显示制造材料
        plan = self._model.get_plan(row) if self._model else {}
        if not plan:
            return
        type_id = plan.get("product_type_id")
        if not type_id:
            return
        from ui_pyside6.views.all_items_view import MatDlg

        dlg = MatDlg(type_id)
        dlg.exec()

    def _view_cost_breakdown(self, row: int):
        # 右键菜单 -> 查看核算：打开成本明细弹窗
        from ui_pyside6.views.industry.cost_breakdown_dialog import CostBreakdownDialog

        plan = self._model.get_plan(row) if self._model else {}
        if not plan:
            return
        dlg = CostBreakdownDialog(plan)
        from PySide6.QtCore import Qt

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def _phase3_placeholder(self, feature_name: str):
        QMessageBox.information(self, "功能开发中", f"「{feature_name}」功能将在阶段三实现。")

    # ── Phase 3: 智能调整 ─────────────────────────────────────

    def _smart_adjust_parent(self, row: int) -> None:
        """母项智能调整：设定目标产量 → 自动计算 runs"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        blueprint_type_id = plan.get("blueprint_type_id")
        if not blueprint_type_id:
            QMessageBox.warning(self, "提示", "该计划无蓝图信息")
            return

        current_runs = int(plan.get("runs", 1))
        current_parallels = max(int(plan.get("parallels", 1)), 1)

        # 查蓝图单流程产出
        conn = get_container().db.direct_connect("ref")
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT quantity FROM blueprint_products WHERE blueprint_type_id=? AND activity='manufacturing'",
                (blueprint_type_id,),
            )
            row_data = cur.fetchone()
            output_per_run = row_data[0] if row_data else 1
        finally:
            conn.close()

        current_output = current_runs * output_per_run * current_parallels

        target, ok = QInputDialog.getInt(
            self,
            "母项智能调整",
            f"当前 {current_runs} 流程 × {current_parallels} 并行 = {current_output} 件\n"
            f"每流程产出: {output_per_run} 件\n\n目标产量:",
            current_output,
            1,
            99999,
        )
        if not ok:
            return

        # 计算新 runs = ceil(target / (output_per_run * parallels))
        new_runs = math.ceil(target / (output_per_run * current_parallels))
        if new_runs == current_runs:
            QMessageBox.information(self, "提示", f"流程数无需调整 ({current_runs})")
            return

        # 更新
        plan["runs"] = new_runs
        self._model.layoutChanged.emit()
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute("UPDATE production_plans SET runs=? WHERE id=?", (new_runs, plan["id"]))
                conn.commit()
            finally:
                conn.close()
        self.plan_updated.emit()

    def _smart_adjust_children(self, row: int) -> None:
        """子项智能调整：根据母项 runs 自动同步子项的 runs/batch"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        group_id = plan.get("group_id")
        if not group_id:
            QMessageBox.warning(self, "提示", "该计划不在组中，无子项可调整")
            return

        current_parent_runs = int(plan.get("runs", 1))
        prod_name = plan.get("product_name", "") or plan.get("blueprint_name", str(plan.get("id", "")))

        # 查找同 group_id 的子项（child_level > 0）
        all_plans = self._model._plans if hasattr(self._model, "_plans") else []
        children = [p for p in all_plans if p.get("group_id") == group_id and p.get("child_level", 0) > 0]

        if not children:
            QMessageBox.warning(self, "提示", "未找到该计划的子项")
            return

        # 询问新的母项流程数
        target_parent_runs, ok = QInputDialog.getInt(
            self,
            "子项智能调整",
            f"母项「{prod_name}」当前流程数: {current_parent_runs}\n共 {len(children)} 个子项\n\n调整后母项流程数:",
            current_parent_runs,
            1,
            99999,
        )
        if not ok or target_parent_runs == current_parent_runs:
            return

        ratio = target_parent_runs / current_parent_runs
        changed = 0
        conn = get_container().db.direct_connect("user")
        try:
            for child in children:
                child_runs = int(child.get("runs", 1))
                child_new = max(1, round(child_runs * ratio))
                if child_new != child_runs:
                    child["runs"] = child_new
                    if child.get("id"):
                        conn.execute("UPDATE production_plans SET runs=? WHERE id=?", (child_new, child["id"]))
                        changed += 1
            # 同步更新母项的 runs
            plan["runs"] = target_parent_runs
            if plan.get("id"):
                conn.execute("UPDATE production_plans SET runs=? WHERE id=?", (target_parent_runs, plan["id"]))
            conn.commit()
        finally:
            conn.close()

        self._model.layoutChanged.emit()
        self.plan_updated.emit()
        QMessageBox.information(
            self,
            "子项调整完成",
            f"母项「{prod_name}」: {current_parent_runs} → {target_parent_runs}\n"
            f"已同步调整 {changed}/{len(children)} 个子项",
        )

    def _smart_parallel_children(self, row: int) -> None:
        """子项大规模产线并行：批量设置子项的并行数"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        group_id = plan.get("group_id")
        if not group_id:
            QMessageBox.warning(self, "提示", "该计划不在组中，无子项可调整")
            return

        all_plans = self._model._plans if hasattr(self._model, "_plans") else []
        children = [p for p in all_plans if p.get("group_id") == group_id and p.get("child_level", 0) > 0]

        if not children:
            QMessageBox.warning(self, "提示", "未找到该计划的子项")
            return

        # 显示当前子项列表及并行数
        msg = "子项当前并行数:\n" + "\n".join(
            f"  {p.get('product_name', p.get('blueprint_name', '?'))}: 并行 {p.get('parallels', 1)}" for p in children
        )
        new_parallels, ok = QInputDialog.getInt(
            self,
            "子项大规模产线并行",
            msg + "\n\n设置所有子项并行数:",
            1,
            1,
            100,
        )
        if not ok:
            return

        changed = 0
        conn = get_container().db.direct_connect("user")
        try:
            for child in children:
                old = int(child.get("parallels", 1))
                if old != new_parallels:
                    child["parallels"] = new_parallels
                    if child.get("id"):
                        conn.execute(
                            "UPDATE production_plans SET parallels=? WHERE id=?",
                            (new_parallels, child["id"]),
                        )
                        changed += 1
            conn.commit()
        finally:
            conn.close()

        self._model.layoutChanged.emit()
        self.plan_updated.emit()
        QMessageBox.information(
            self, "并行调整完成", f"已设置 {changed}/{len(children)} 个子项的并行数为 {new_parallels}"
        )

    def _show_npc_seller(self, row: int) -> None:
        """查看原本图 NPC 卖家"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return
        bp_id = plan.get("blueprint_type_id")
        if not bp_id:
            QMessageBox.warning(self, "提示", "该计划无蓝图信息")
            return
        bp_name = plan.get("blueprint_name", "") or plan.get("product_name", str(bp_id))
        from ui_pyside6.dialogs.npc_seller_dialog import NpcSellerDialog

        dlg = NpcSellerDialog(bp_id, bp_name, self)
        dlg.exec()

    def _set_facility_system(self, row: int) -> None:
        """为设施设置所在星系 — 星系搜索 + 自动带出成本系数"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        # 检查 universe 数据是否就绪
        conn = get_container().db.direct_connect("ref")
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM solar_system")
            has_systems = cur.fetchone()[0] > 0
        finally:
            conn.close()

        if not has_systems:
            QMessageBox.warning(self, "数据未就绪", "星系数据尚未加载。请先运行「数据初始化」中的 SDE 扩展数据。")
            return

        current_facility = plan.get("facility", "") or ""
        system_name, ok = QInputDialog.getText(
            self,
            "设置设施星系",
            f"当前设施: {current_facility}\n\n输入星系名称（支持部分匹配）:",
            text=current_facility,
        )
        if not ok or not system_name.strip():
            return

        # 查找星系
        conn = get_container().db.direct_connect("ref")
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT solar_system_id, solar_system_name, security FROM solar_system "
                "WHERE solar_system_name LIKE ? LIMIT 10",
                (f"%{system_name.strip()}%",),
            )
            matches = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        if not matches:
            QMessageBox.warning(self, "未找到星系", f"未找到匹配「{system_name}」的星系")
            return

        if len(matches) == 1:
            selected = matches[0]
        else:
            # 多匹配时让用户选择
            items = [f"{m['solar_system_name']} (安全等级 {m['security']:.1f})" for m in matches]
            sel, ok = QInputDialog.getItem(self, "选择星系", "找到多个匹配:", items, 0, False)
            if not ok:
                return
            idx = items.index(sel)
            selected = matches[idx]

        # 更新 plan
        ss_name = selected["solar_system_name"]
        ss_id = selected["solar_system_id"]
        plan["facility"] = ss_name

        # 自动带出成本系数
        sci = get_container().pricing_service.get_system_cost_index(ss_id, "manufacturing")

        # 持久化
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute(
                    "UPDATE production_plans SET facility=? WHERE id=?",
                    (ss_name, plan["id"]),
                )
                conn.commit()
            finally:
                conn.close()

        self._model.layoutChanged.emit()
        self.plan_updated.emit()
        QMessageBox.information(
            self,
            "设置完成",
            f"设施星系: {ss_name}\n"
            f"安全等级: {selected['security']:.1f}\n"
            f"制造成本指数(SCI): {sci:.4f}\n\n"
            f"可在「成本系数」中调整附加费率。",
        )

    def _set_facility_cost_index(self, row: int) -> None:
        """为设施所在星系设置成本系数 — 覆盖 SCI 或添加附加费率"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        facility = plan.get("facility", "") or "未设置"

        # 从 DB 读取当前系数（如果有 system_id 可以从 plan 推断，但当前没有这个字段）
        # 这里只设一个简单的附加费率 multiplier
        current_mult = float(plan.get("cost_multiplier", 1.0)) if "cost_multiplier" in plan else 1.0

        val, ok = QInputDialog.getDouble(
            self,
            "设施成本系数",
            f"设施: {facility}\n当前系数: {current_mult:.2f}x\n\n新系数 (1.0 = 标准 SCI, >1 = 附加费用):",
            current_mult,
            0.1,
            10.0,
            2,
        )
        if not ok:
            return

        # 持久化到 plan（扩展字段：facility_cost_mult）
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute(
                    "UPDATE production_plans SET facility_cost_mult=? WHERE id=?",
                    (val, plan["id"]),
                )
                conn.commit()
            finally:
                conn.close()

        QMessageBox.information(self, "设置完成", f"设施成本系数已设为 {val:.2f}x")

    def _show_production_wizard(self, row: int) -> None:
        """产线启动小助手：选择计划 → 配置角色/设施 → 启动"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        # 收集同 group 或关联计划
        group_id = plan.get("group_id")
        all_plans = self._model._plans if hasattr(self._model, "_plans") else []
        if group_id:
            related = [p for p in all_plans if p.get("group_id") == group_id]
        else:
            related = [plan]
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        dlg = ProductionWizard(related, self)
        dlg.exec()
        self.plan_updated.emit()

    # ── 主题 ─────────────────────────────────────────────────

    def _on_theme_changed(self) -> None:
        # 表格体样式：直接设置完整 QTableView QSS（含选中行颜色），
        # 绕过原生 windowsvista 风格对 ::item:selected 伪状态的限制
        self._table.setStyleSheet(
            f"QTableView {{"
            f"  background-color: {theme.BG_DARK};"
            f"  alternate-background-color: {theme.BG_SURFACE};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: 6px;"
            f"  gridline-color: {theme.BORDER};"
            f"  selection-background-color: {theme.PRIMARY};"
            f"  selection-color: {theme.TEXT_BRIGHT};"
            f"  outline: none;"
            f"}}"
            f"QTableView::item {{"
            f"  padding: 4px 8px;"
            f"  border-bottom: 1px solid {theme.BORDER};"
            f"}}"
            f"QTableView::item:selected {{"
            f"  background-color: {theme.PRIMARY};"
            f"  color: {theme.TEXT_BRIGHT};"
            f"}}"
        )
        # 紧凑表头覆盖全局（全局 padding 6x8, font-size 12px）
        self._table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 2px 4px; font-size: 11px; }}"
        )

"""生产计划表格 — PlanTable 视图组件"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
from ui_pyside6.models.industry_models import PlanTableModel

# ── 列索引常量（与 PlanTableModel._HEADERS 对齐） ────────────
COL_ICON = 0
COL_PRODUCT = 1
COL_BATCH = 2
COL_PARALLELS = 3
COL_GROUP = 4
COL_CHILD_LEVEL = 5
COL_STATUS = 6
COL_NOTES = 7
COL_CHAR_NAME = 8
COL_RUNS = 9
COL_BLUEPRINT = 10
COL_TIME = 11
COL_OUTPUT_RATE = 12
COL_FACILITY = 13
COL_OUTPUT = 14
COL_COST = 15
COL_PROFIT = 16
COL_MARKET_MARGIN = 17
COL_PERSONAL_MARGIN = 18
COL_ACTIONS = 19

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
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(26)

        layout.addWidget(self._table)

        self._model: PlanTableModel | None = None

        # ── 连接信号 ─────────────────────────────────────────
        self._table.doubleClicked.connect(self._on_double_clicked)

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

    def set_model(self, model: PlanTableModel) -> None:
        """设置 PlanTableModel"""
        self._model = model
        self._table.setModel(model)

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
        """双击操作列 → 不编辑；可编辑列 → QTableView 默认编辑；其余 → 发射 plan_detail_requested"""
        col = index.column()
        if col == COL_ACTIONS:
            return
        # 可编辑列交给 QTableView 默认编辑行为
        if self._model and col in PlanTableModel._EDITABLE_COLS:
            return
        # 发射详情请求
        row = index.row()
        if self._model:
            plan = self._model.get_plan(row)
            plan_id = plan.get("id")
            if plan_id is not None:
                self.plan_detail_requested.emit(int(plan_id))

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

    # ── 行右键菜单（14 个菜单项） ────────────────────────────

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

        # 1. 修改流程数
        menu.addAction("修改流程数", lambda: self._modify_runs(row))

        # 2. 修改并行数
        menu.addAction("修改并行数", lambda: self._modify_parallels(row))

        # 3. 分隔线
        menu.addSeparator()

        # 4. 复制制造所需蓝图名称到剪切板
        menu.addAction("复制制造所需蓝图名称到剪切板", lambda: self._copy_blueprint_name(row))

        # 5. 查看核算（阶段二占位）
        menu.addAction("查看核算", lambda: self._view_cost_breakdown(row))

        # 6. 查看物品详情（阶段二占位）
        menu.addAction("查看物品详情", lambda: self._view_item_details(row))

        # 7. 分隔线
        menu.addSeparator()

        # 8. 勾选备料
        menu.addAction("勾选备料", lambda: self._set_materials_ready(row, 1))

        # 9. 取消勾选备料
        menu.addAction("取消勾选备料", lambda: self._set_materials_ready(row, 0))

        # 10. 项目启动
        menu.addAction("项目启动", lambda: self._set_status(row, "in_progress"))

        # 11. 项目完成
        menu.addAction("项目完成", lambda: self._set_status(row, "completed"))

        # 12. 分隔线
        menu.addSeparator()

        # 13. 删除行
        menu.addAction("删除行", lambda: self._delete_row(row))

        # --- Phase 3: 高级功能 ---
        menu.addSeparator()

        smart_menu = menu.addMenu("智能调整")
        a = smart_menu.addAction("母项智能调整")
        a.triggered.connect(lambda: self._phase3_placeholder("母项智能调整"))
        a = smart_menu.addAction("子项智能调整")
        a.triggered.connect(lambda: self._phase3_placeholder("子项智能调整"))
        a = smart_menu.addAction("子项大规模产线并行")
        a.triggered.connect(lambda: self._phase3_placeholder("子项大规模产线并行"))

        a = menu.addAction("查看原本图的NPC卖家")
        a.triggered.connect(lambda: self._phase3_placeholder("查看原本图的NPC卖家"))

        view_menu = menu.addMenu("更多修改")
        a = view_menu.addAction("为设施设置所在星系")
        a.triggered.connect(lambda: self._phase3_placeholder("为设施设置所在星系"))
        a = view_menu.addAction("为设施所在星系设置成本系数")
        a.triggered.connect(lambda: self._phase3_placeholder("为设施所在星系设置成本系数"))

        a = menu.addAction("产线启动小助手")
        a.triggered.connect(lambda: self._phase3_placeholder("产线启动小助手"))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── 行菜单操作 ───────────────────────────────────────────

    def _modify_runs(self, row: int) -> None:
        plan = self._model.get_plan(row)
        current = int(plan.get("runs", 0))
        val, ok = QInputDialog.getInt(self, "修改流程数", "流程数:", current, 1, 99999)
        if ok:
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
        plan = self._model.get_plan(row)
        current = int(plan.get("parallels", 1))
        val, ok = QInputDialog.getInt(self, "修改并行数", "并行数:", current, 1, 99999)
        if ok:
            plan["parallels"] = max(1, val)
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
        plan = self._model.get_plan(row)
        bp_name = plan.get("blueprint_name") or plan.get("product_name", "")
        if bp_name:
            QApplication.clipboard().setText(bp_name)

    def _set_materials_ready(self, row: int, value: int) -> None:
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
        plan = self._model.get_plan(row)
        plan["status"] = status
        self._model.layoutChanged.emit()
        if plan.get("id"):
            conn = get_container().db.direct_connect("user")
            try:
                conn.execute("UPDATE production_plans SET status=? WHERE id=?", (status, plan["id"]))
                conn.commit()
            finally:
                conn.close()
        self.plan_updated.emit()

    def _delete_row(self, row: int) -> None:
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

    # ── 主题 ─────────────────────────────────────────────────

    def _on_theme_changed(self) -> None:
        self._table.setStyleSheet(
            f"QTableView {{ gridline-color: {theme.BORDER}; color: {theme.TEXT_PRIMARY}; }}"
            f"QTableView::item:selected {{ background-color: {theme.BG_SURFACE_LIGHT}; color: {theme.TEXT_BRIGHT}; }}"
        )

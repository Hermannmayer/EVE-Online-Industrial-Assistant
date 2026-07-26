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


_NUM_COLUMNS = 19


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
        self._configure_adaptive_columns()

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

    def _configure_adaptive_columns(self) -> None:
        """配置列宽自适应：窄列固定，产品列拉伸，其余自适应内容"""
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)

        NARROW = {0, 2, 3, 4, 5}  # 图标/批次/并行/组号/子级
        STRETCH = {1}  # 产品名
        # 其余：根据内容自适应 + interactive 可调

        for col in range(19):
            if col in NARROW:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            elif col in STRETCH:
                header.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                header.resizeSection(col, 75)

    def set_model(self, model: PlanTableModel) -> None:
        """设置 PlanTableModel 并自适应列宽"""
        self._model = model
        self._table.setModel(model)
        # 内容自适应后，窄列自动收缩
        self._table.resizeColumnsToContents()
        header = self._table.horizontalHeader()
        # 确保产品列至少有 120px，但不超过可用空间一半
        product_w = header.sectionSize(1)
        avail = header.width() if header.width() > 0 else 800
        header.resizeSection(1, max(120, min(product_w, avail // 2)))

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
        a.triggered.connect(lambda r=row: self._smart_adjust_parent(r))
        a = smart_menu.addAction("子项智能调整")
        a.triggered.connect(lambda r=row: self._smart_adjust_children(r))
        a = smart_menu.addAction("子项大规模产线并行")
        a.triggered.connect(lambda r=row: self._smart_parallel_children(r))

        a = menu.addAction("查看原本图的NPC卖家")
        a.triggered.connect(lambda r=row: self._show_npc_seller(r))

        view_menu = menu.addMenu("更多修改")
        a = view_menu.addAction("为设施设置所在星系")
        a.triggered.connect(lambda r=row: self._set_facility_system(r))
        a = view_menu.addAction("为设施所在星系设置成本系数")
        a.triggered.connect(lambda r=row: self._set_facility_cost_index(r))

        a = menu.addAction("产线启动小助手")
        a.triggered.connect(lambda r=row: self._show_production_wizard(r))

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

    # ── Phase 3: 智能调整 ─────────────────────────────────────

    def _smart_adjust_parent(self, row: int) -> None:
        """母项智能调整：设定目标产量 → 自动计算 runs"""
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
        # 紧凑表头覆盖全局（全局 padding 6x8, font-size 12px）
        self._table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 2px 4px; font-size: 11px; }}"
        )

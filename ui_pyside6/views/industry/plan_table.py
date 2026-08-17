"""生产计划表格 — PlanTable 视图组件"""

from __future__ import annotations

from datetime import UTC, datetime

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
from ui_pyside6.views.industry.plan_table_constants import (
    COL_BLUEPRINT,
    COL_CHECKBOX,
    COL_CHILD_LEVEL,
    COL_GROUP,
    COL_PRODUCT,
    COL_STATUS,
    FIXED_WIDTHS,
    NUM_COLUMNS,
)
from ui_pyside6.views.industry.plan_table_delegate import PlanTableDelegate, ReadyButtonDelegate


class PlanTable(QWidget):
    """生产计划表格 — 封装 QTableView + PlanTableModel + 右键菜单"""

    plan_updated = Signal()
    refresh_requested = Signal()
    plan_detail_requested = Signal(int)
    launcher_requested = Signal(str)  # 产线启动小助手（传初始人物名，空串=未分配）

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
        # 状态列「待下线」渲染成按钮（点击走 _on_cell_clicked）
        self._table.setItemDelegateForColumn(COL_STATUS, ReadyButtonDelegate(self._table))
        # 其余列展示职责（染色/图标/底色/复选框/对齐/尺寸）交给 PlanTableDelegate
        self._table.setItemDelegate(PlanTableDelegate(self._table))

        layout.addWidget(self._table)

        self._model: PlanTableModel | None = None
        # 工具栏当前材料机库 ID（由 IndustryPage 注入，启动时兜底）
        self._mat_hangar_id: int | None = None

        # ── 连接信号 ─────────────────────────────────────────
        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table.clicked.connect(self._on_cell_clicked)
        self._table.entered.connect(self._on_cell_entered)

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

        NARROW = {COL_GROUP, COL_CHILD_LEVEL}  # 组号/子级
        STRETCH = {COL_PRODUCT}  # 产品名
        # 备料勾选 / 图标列固定窄宽（适配复选框与图标，避免被内容/表头撑宽）

        for col in range(NUM_COLUMNS):
            if col in FIXED_WIDTHS:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                header.resizeSection(col, FIXED_WIDTHS[col])
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
        # 收紧固定窄列（备料勾选/图标），避免被内容或表头撑宽
        for col, w in FIXED_WIDTHS.items():
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(col, w)
        # 确保产品列至少有 120px，但不超过可用空间一半
        product_w = header.sectionSize(COL_PRODUCT)
        avail = header.width() if header.width() > 0 else 800
        header.resizeSection(COL_PRODUCT, max(120, min(product_w, avail // 2)))

    def get_model(self) -> PlanTableModel | None:
        return self._model

    def set_mat_hangar_id(self, mat_hangar_id: int | None) -> None:
        """注入工具栏当前材料机库 ID（启动时用于兜底旧计划）。"""
        self._mat_hangar_id = mat_hangar_id

    def _solar_system_for_mat_hangar(self, mat_hangar_id: int | None) -> int | None:
        """从材料机库带出所在星系 ID（材料在哪个星系造，成本指数就按它算）。"""
        from services import inventory_manager

        return inventory_manager.get_hangar_system_id(mat_hangar_id)

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
            visible_count = sum(1 for c in range(NUM_COLUMNS) if c != col and not self._table.isColumnHidden(c))
            if visible_count == 0:
                checks[col].blockSignals(True)
                checks[col].setChecked(True)
                checks[col].blockSignals(False)
                return
        self._table.setColumnHidden(col, not visible)

    # ── 行右键菜单 ────────────────────────────────────────────

    def _on_table_context_menu(self, pos) -> None:
        """右键行 → 操作菜单（多选时批量操作对选中行全部生效）"""
        index = self._table.indexAt(pos)
        if not index.isValid() or not self._model:
            return

        # 收集选中行：右键点击的行不在选中集时只用当前行
        selection_model = self._table.selectionModel()
        selected_indexes = selection_model.selectedRows() if selection_model else []
        if not any(idx.row() == index.row() for idx in selected_indexes):
            selected_rows = [index.row()]
        else:
            selected_rows = [idx.row() for idx in selected_indexes]

        row = index.row()
        plan = self._model.get_plan(row)
        if not plan:
            return

        # 「共享组件」合成根节点：无计划 id，不支持行操作（仅作分组标题/折叠）
        if plan.get("_synthetic"):
            model = self._model
            if model is not None:
                menu = QMenu(self)
                menu.addAction("展开/折叠共享组件", lambda: model.toggle_collapse(-1))
                menu.exec(self._table.viewport().mapToGlobal(pos))
            return

        def batch(fn):
            """批量操作：对每行执行 fn(row)"""
            for r in selected_rows:
                fn(r)

        menu = QMenu(self)

        # ── 编辑（批量适用：一次编辑对所有行生效，不含 ME/TE） ─
        menu.addAction(
            "编辑生产计划",
            lambda: self._batch_edit_plans(selected_rows) if len(selected_rows) > 1 else self._edit_plan(row),
        )
        menu.addSeparator()

        # ── 材料/时间效率（批量适用） — 不影响其他属性 ──
        menu.addAction("设置蓝图等级...", lambda: self._batch_set_me_te(selected_rows))
        menu.addAction("绑定库存蓝图...", lambda: self._show_blueprint_picker(row))
        menu.addSeparator()

        # ── 查看 ─────────────────────────────────────────
        menu.addAction("查看核算", lambda: self._view_cost_breakdown(row))
        menu.addSeparator()

        # ── 状态（按当前行状态显隐；批量时对选中行逐条生效） ──────────
        # 备料 toggle — 使用右键点击行的状态决定勾选/取消
        mats_ready = bool(plan.get("materials_ready", 0))
        if mats_ready:
            a = menu.addAction("取消勾选备料")
            a.triggered.connect(lambda: batch(lambda r: self._set_materials_ready(r, 0)))
        else:
            a = menu.addAction("勾选备料")
            a.triggered.connect(lambda: batch(lambda r: self._set_materials_ready(r, 1)))

        status = (plan.get("status") or "").lower()
        if status == "pending":
            a = menu.addAction("项目启动")
            a.triggered.connect(lambda: batch(lambda r: self._start_plan(r)))
        elif status in ("in_progress", "running"):
            # 仅「软件误点、游戏未启动」时可撤销并返还材料
            a = menu.addAction("撤销启动（返还材料）")
            a.triggered.connect(lambda: batch(lambda r: self._undo_start(r)))
        elif status == "ready":
            # 待下线：游戏产线已跑完、材料已扣，点击下线（不可逆）产出成品
            a = menu.addAction("下线")
            a.triggered.connect(lambda: batch(lambda r: self._set_status(r, "completed")))
        elif status in ("completed", "done"):
            a = menu.addAction("设为待生产（复用）")
            a.triggered.connect(lambda: batch(lambda r: self._reset_for_reuse(r)))
        menu.addSeparator()

        # ── 备注（批量适用） ──────────────────────────────
        menu.addAction("添加备注", lambda: self._add_notes(row))
        menu.addAction("复制蓝图名称", lambda: self._copy_blueprint_name(row))
        menu.addSeparator()

        # ── 高级（批量适用） ──────────────────────────────
        menu.addAction("查看蓝图原图的NPC卖家", lambda: batch(lambda r: self._show_npc_seller(r)))
        menu.addAction("产线启动小助手", lambda: self._show_production_wizard(row))

        # ── 智能调整（拆解/并行，作用于选中行所属组） ──────────
        smart_menu = menu.addMenu("智能调整")
        a = smart_menu.addAction("母项调整（递归拆解）")
        a.triggered.connect(lambda: self._decompose_parent(selected_rows))
        a = smart_menu.addAction("子项调整（并行配置）")
        a.triggered.connect(lambda: self._adjust_children(selected_rows))
        a = smart_menu.addAction("子项大规模产线并行")
        a.triggered.connect(lambda: self._mass_parallel(selected_rows))
        a = smart_menu.addAction("重算子项（按母项当前需求）")
        a.triggered.connect(lambda: self._recalc_children(selected_rows))

        menu.addSeparator()

        # ── 危险操作（批量适用） ──────────────────────────
        a = menu.addAction("删除行")
        a.triggered.connect(lambda: self._delete_rows(selected_rows))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── 单击事件 ─────────────────────────────────────────────

    def _on_cell_clicked(self, index) -> None:
        """单击勾选列 → 切换备料；蓝图列 → 绑定蓝图；产品列 → 折叠/展开；待下线状态 → 确认后单独下线"""
        if not self._model:
            return
        row = index.row()
        plan = self._model.get_plan(row)
        if not plan:
            return
        if index.column() == COL_CHECKBOX:
            new_val = 0 if plan.get("materials_ready", 0) else 1
            self._set_materials_ready(row, new_val)
        elif index.column() == COL_BLUEPRINT:
            self._show_blueprint_picker(row)
        elif index.column() == COL_PRODUCT:
            # 「共享组件」合成根：点击切换共享区折叠
            if plan.get("_synthetic"):
                self._model.toggle_collapse(-1)
                return
            # 母项行（child_level==0）且有子项时，点击切换折叠
            gid = plan.get("group_id") or plan.get("group_number") or 0
            lvl = int(plan.get("child_level") or plan.get("sub_level") or 0)
            if lvl == 0 and gid and self._model._has_children(gid):
                self._model.toggle_collapse(gid)
        elif index.column() == COL_STATUS and (plan.get("status") or "").lower() == "ready":
            self._complete_plan_with_dialog(plan)

    def _on_cell_entered(self, index) -> None:
        """悬停待下线状态单元格 → 手型光标；悬停可折叠母项 → 手型光标"""
        if not self._model:
            return
        plan = self._model.get_plan(index.row())
        if index.column() == COL_STATUS and plan is not None and (plan.get("status") or "").lower() == "ready":
            cursor = Qt.CursorShape.PointingHandCursor
        elif index.column() == COL_PRODUCT and plan is not None:
            gid = plan.get("group_id") or plan.get("group_number") or 0
            lvl = int(plan.get("child_level") or plan.get("sub_level") or 0)
            cursor = (
                Qt.CursorShape.PointingHandCursor
                if (lvl == 0 and gid and self._model._has_children(gid))
                else Qt.CursorShape.ArrowCursor
            )
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self._table.viewport().setCursor(cursor)

    def _complete_plan_with_dialog(self, plan: dict) -> None:
        """状态列「待下线」→ 下线确认弹窗（选产出机库）→ 单独下线"""
        from services.inventory_manager import get_hangars
        from services.user_settings import get_default_hangar_id
        from ui_pyside6.views.industry.complete_plans_dialog import CompletePlansDialog, complete_plans

        hangars = get_hangars()
        default_hid = get_default_hangar_id("default_deposit_hangar_id")
        dlg = CompletePlansDialog([plan], hangars, default_hid, self)
        if not dlg.exec():
            return
        result = complete_plans([plan], dlg.selected_hangar_id())
        if not result["completed"]:
            QMessageBox.warning(self, "下线失败", "、".join(result["failed"]) or "未知错误")
            return
        if self._model is None:
            return
        plan["status"] = "completed"
        plan["deposited"] = 1 if result["deposited"] else 0
        plan["completed_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        plan["assigned_blueprint_id"] = None
        self._model.layoutChanged.emit()
        self._rebuild_subitems()
        self.plan_updated.emit()

    def _edit_plan(self, row: int) -> None:
        """编辑生产计划 — 打开 PlanEditDialog，保存后同步重算"""
        if self._model is None:
            return
        from ui_pyside6.views.industry import PlanEditDialog

        plan = self._model.get_plan(row)
        if not plan:
            return
        dlg = PlanEditDialog(self, plan)
        if dlg.exec():
            updated = dlg.get_updated_data()
            final_mat = updated.get("mat_hangar_id")
            solar_system_id = self._solar_system_for_mat_hangar(final_mat)
            # 设施名：编辑对话框不含 facility；材料机库未设 facility 时自动带出机库名称
            facility = plan.get("facility", "") or ""
            if not facility and final_mat:
                from services.inventory_manager import get_hangar_name

                facility = get_hangar_name(final_mat)
            get_container().plan_repo.update(
                plan["id"],
                runs=updated["runs"],
                parallels=updated["parallels"],
                char_name=updated["char_name"],
                notes=updated["notes"],
                deposit_hangar_id=updated.get("deposit_hangar_id"),
                mat_hangar_id=final_mat,
                solar_system_id=solar_system_id,
                facility=facility,
            )
            # 更新内存模型的基础字段（保留现有 ME/TE 值，编辑对话框不含 ME/TE；
            # facility/mat_hub/sell_hub 由工具栏价格设置与「设置设施星系」管理，编辑不改）
            plan["runs"] = updated["runs"]
            plan["parallels"] = updated["parallels"]
            plan["char_name"] = updated["char_name"]
            plan["notes"] = updated["notes"]
            plan["deposit_hangar_id"] = updated.get("deposit_hangar_id")
            plan["mat_hangar_id"] = final_mat
            plan["solar_system_id"] = solar_system_id
            plan["facility"] = facility

            # 同步重算该条计划，立即更新派生字段
            from services.char_config_resolver import resolve_char_config

            char_name = updated.get("char_name", "").strip()
            char_config = resolve_char_config(char_name=char_name) or {}
            metrics = get_container().scoring_service().calculate_plan_metrics(plan, char_config)
            # 编辑母项：同组有更深子项时，材料成本立即改按子项制造价（不再依赖后续批量重算，
            # 避免瞬时显示市场价）
            from services.plan_metrics import adjust_mother_metrics, mother_subitem_cost_map

            gid = plan.get("group_id") or plan.get("group_number")
            if gid:
                from services.industry_dialog_queries import get_subitem_plans

                subs = get_subitem_plans(
                    get_container().db, gid, int(plan.get("child_level") or plan.get("sub_level") or 0)
                )
                if subs:
                    base: dict[int, tuple[dict, dict]] = {}
                    for s in subs:
                        s["group_id"] = s.get("group_number", 0)
                        s["child_level"] = s.get("sub_level", 0)
                        sc = resolve_char_config(char_name=s.get("char_name") or "") or {}
                        base[s["id"]] = (s, get_container().scoring_service().calculate_plan_metrics(s, sc))
                    sub_cost_map = mother_subitem_cost_map(base, plan)
                    if sub_cost_map:
                        total_mult = max(int(plan.get("runs", 1)), 1) * max(int(plan.get("parallels", 1)), 1)
                        adj_mat, adj_profit, adj_margin, _ = adjust_mother_metrics(metrics, sub_cost_map, total_mult)
                        metrics = dict(metrics)
                        metrics["material_cost"] = adj_mat
                        metrics["profit"] = adj_profit
                        metrics["margin"] = adj_margin
            plan.update(metrics)

            self._rebuild_subitems()
            self._model.layoutChanged.emit()
            self.plan_updated.emit()

    def _batch_edit_plans(self, rows: list[int]) -> None:
        """批量编辑生产计划 — 一次修改所有选中行（不含 ME/TE）"""
        if self._model is None or not rows:
            return
        from ui_pyside6.views.industry.plan_edit_dialog import PlanEditDialog

        first = self._model.get_plan(rows[0]) if rows else None
        dlg = PlanEditDialog(
            self,
            {
                "_selected_rows": rows,
                "runs": first.get("runs", 1) if first else 1,
                "parallels": first.get("parallels", 1) if first else 1,
            },
            batch_mode=True,
            row_count=len(rows),
        )
        if dlg.exec():
            updated = dlg.get_updated_data()
            # 批量模式：机库字段仅在用户显式选择（非「未设置」）时更新，避免清空既有值
            fields: dict = {
                "runs": updated.get("runs"),
                "parallels": updated.get("parallels"),
                "char_name": updated["char_name"],
                "notes": updated["notes"],
            }
            fields = {k: v for k, v in fields.items() if v is not None}
            if updated.get("deposit_hangar_id") is not None:
                fields["deposit_hangar_id"] = updated["deposit_hangar_id"]
            if updated.get("mat_hangar_id") is not None:
                fields["mat_hangar_id"] = updated["mat_hangar_id"]
                # 显式设材料机库 → 同步重算所在星系（成本指数）
                fields["solar_system_id"] = self._solar_system_for_mat_hangar(updated["mat_hangar_id"])

            ids: list[int] = []
            for r in rows:
                plan = self._model.get_plan(r)
                if not plan:
                    continue
                if plan.get("id"):
                    ids.append(plan["id"])
            if ids:
                get_container().plan_repo.update_many(ids, **fields)

            # 同步内存模型
            for r in rows:
                plan = self._model.get_plan(r)
                if not plan:
                    continue
                plan["runs"] = fields.get("runs", plan.get("runs", 1))
                plan["parallels"] = fields.get("parallels", plan.get("parallels", 1))
                plan["char_name"] = fields["char_name"]
                plan["notes"] = fields["notes"]
                if "deposit_hangar_id" in fields:
                    plan["deposit_hangar_id"] = fields["deposit_hangar_id"]
                if "mat_hangar_id" in fields:
                    plan["mat_hangar_id"] = fields["mat_hangar_id"]
                    plan["solar_system_id"] = fields["solar_system_id"]
            self._rebuild_subitems()
            self._model.layoutChanged.emit()
            self.plan_updated.emit()

    def _batch_set_me_te(self, rows: list[int]) -> None:
        """批量设置 ME/TE — 带滑块的合并对话框"""
        if self._model is None or not rows:
            return
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider, QSpinBox, QVBoxLayout

        import ui_pyside6.theme as theme

        dlg = QDialog(self)
        dlg.setWindowTitle("设置蓝图等级")
        dlg.setMinimumWidth(360)
        dlg.setStyleSheet(f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        root = QVBoxLayout(dlg)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # 从首行加载当前值
        first = self._model.get_plan(rows[0]) if rows else None
        cur_me = int(first.get("me_level", 0)) if first else 0
        cur_te = int(first.get("te_level", 0)) if first else 0

        # ME
        root.addWidget(QLabel("材料效率(ME) 0-10:"))
        me_row = QHBoxLayout()
        me_slider = QSlider(Qt.Orientation.Horizontal)
        me_slider.setRange(0, 10)
        me_slider.setValue(cur_me)
        me_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        me_slider.setTickInterval(1)
        me_spin = QSpinBox()
        me_spin.setRange(0, 10)
        me_spin.setValue(cur_me)
        me_spin.setFixedWidth(56)
        me_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        me_slider.valueChanged.connect(me_spin.setValue)
        me_spin.valueChanged.connect(me_slider.setValue)
        me_row.addWidget(me_slider, 1)
        me_row.addWidget(me_spin)
        root.addLayout(me_row)

        # TE
        root.addWidget(QLabel("时间效率(TE) 0-20:"))
        te_row = QHBoxLayout()
        te_slider = QSlider(Qt.Orientation.Horizontal)
        te_slider.setRange(0, 20)
        te_slider.setValue(cur_te)
        te_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        te_slider.setTickInterval(5)
        te_spin = QSpinBox()
        te_spin.setRange(0, 20)
        te_spin.setValue(cur_te)
        te_spin.setFixedWidth(56)
        te_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        te_slider.valueChanged.connect(te_spin.setValue)
        te_spin.valueChanged.connect(te_slider.setValue)
        te_row.addWidget(te_slider, 1)
        te_row.addWidget(te_spin)
        root.addLayout(te_row)

        root.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)

        remove_theme = theme.add_theme_listener(
            lambda: dlg.setStyleSheet(
                f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; font-size: 12px;"
            )
        )

        if not dlg.exec():
            remove_theme()
            return
        remove_theme()

        me_val = me_slider.value()
        te_val = te_slider.value()
        ids: list[int] = []
        for r in rows:
            plan = self._model.get_plan(r)
            if not plan:
                continue
            plan["me_level"] = me_val
            plan["te_level"] = te_val
            if plan.get("id"):
                ids.append(plan["id"])
        if ids:
            get_container().plan_repo.update_many(ids, me_level=me_val, te_level=te_val)
        self._rebuild_subitems()
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
                get_container().plan_repo.update(plan["id"], notes=text.strip())
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
                get_container().plan_repo.update(plan["id"], runs=val)
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
                get_container().plan_repo.update(plan["id"], parallels=val)
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
            get_container().plan_repo.update(plan["id"], materials_ready=value)
        self.plan_updated.emit()

    def _start_plan(self, row: int) -> None:
        """启动计划：校验材料 → 不足弹确认（强制/取消）→ 扣减 → 写 started_at → 绑蓝图"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan or not plan.get("id"):
            return
        from services import plan_execution

        mat_hangar_id = plan.get("mat_hangar_id") or getattr(self, "_mat_hangar_id", None)
        allow_short = False

        if not mat_hangar_id:
            ret = QMessageBox.question(
                self,
                "启动计划",
                "材料机库未设置，跳过材料扣减？\n（可在顶部工具栏「材料机库」下拉选择）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        # 材料校验（仅材料机库已设置时）
        shortfalls: list[dict] = []
        if mat_hangar_id:
            shortfalls = [r for r in plan_execution.check_materials(plan, mat_hangar_id) if (r.get("missing") or 0) > 0]
        if shortfalls:
            lines = "\n".join(f"  {r.get('name')}: 缺 {r.get('missing'):,.0f}" for r in shortfalls[:10])
            if len(shortfalls) > 10:
                lines += f"\n  … 等 {len(shortfalls)} 种"
            ret = QMessageBox.question(
                self,
                "材料不足",
                f"以下材料不足：\n{lines}\n\n是否强制启动？（扣减现有库存，缺口标记待补）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            allow_short = True

        res = plan_execution.start_plan(plan, mat_hangar_id=mat_hangar_id, allow_short=allow_short)
        if not res.get("ok"):
            QMessageBox.warning(self, "启动失败", res.get("message", "未知错误"))
            return
        # 同步内存模型（DB 已由 start_plan 写入；其余派生字段经 plan_updated → load_plans 重载）
        plan["status"] = "in_progress"
        plan["started_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        plan["mat_hangar_id"] = mat_hangar_id
        self._model.layoutChanged.emit()
        self.plan_updated.emit()

    def _reset_for_reuse(self, row: int) -> None:
        """设为待生产：仅 completed 计划复用（材料已在成品中，不返还）。

        清除完成痕迹（started_at/completed_at/deposited/material_short）与蓝图占用，
        置回 pending 供再次启动，不触碰库存。
        """
        model = self._model
        if model is None:
            return
        plan = model.get_plan(row)
        if not plan or not plan.get("id"):
            return
        from services import plan_execution

        ret = QMessageBox.question(
            self,
            "设为待生产",
            "将已完成计划重置为待生产以便复用？\n材料不返还（已完成计划的材料已变为成品入库），并清除完成记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        res = plan_execution.reset_plan_for_reuse(plan["id"])
        if not res.get("ok"):
            QMessageBox.warning(self, "操作失败", res.get("message", "未知错误"))
            return
        plan["status"] = "pending"
        plan["started_at"] = None
        plan["completed_at"] = None
        plan["deposited"] = 0
        plan["material_short"] = ""
        plan["assigned_blueprint_id"] = None
        model.layoutChanged.emit()
        self.plan_updated.emit()

    def _undo_start(self, row: int) -> None:
        """撤销启动：取消误启动的产线并返还已扣减材料到材料机库"""
        model = self._model
        if model is None:
            return
        plan = model.get_plan(row)
        if not plan or not plan.get("id"):
            return
        if plan.get("status") not in ("in_progress", "running"):
            QMessageBox.warning(self, "提示", "仅生产中计划可撤销启动")
            return
        from services import plan_execution

        ret = QMessageBox.question(
            self,
            "撤销启动",
            "确定撤销该产线启动？\n将取消生产，并返还已扣减材料到材料机库。\n"
            "（仅当尚未在游戏中启动该产线时使用——游戏产线一经启动不退还材料）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        res = plan_execution.cancel_plan(plan)
        if not res.get("ok"):
            QMessageBox.warning(self, "撤销失败", res.get("message", "未知错误"))
            return
        plan["status"] = "pending"
        plan["started_at"] = None
        plan["material_short"] = ""
        plan["assigned_blueprint_id"] = None
        model.layoutChanged.emit()
        QMessageBox.information(self, "已撤销", res.get("message", "已撤销启动"))
        self.plan_updated.emit()

    def _set_status(self, row: int, status: str) -> None:
        """状态流转：completed → 完成入库（complete_plan）；其余 → 直接改状态。"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan or not plan.get("id"):
            return
        if status == "completed":
            self._complete_plan(plan)
            return
        plan["status"] = status
        self._model.layoutChanged.emit()
        repo = get_container().plan_repo
        # 状态从 completed 改回时重置入库标记
        if status != "completed" and plan.get("deposited"):
            plan["deposited"] = 0
            repo.update(plan["id"], deposited=0)
        repo.update(plan["id"], status=status)
        self.plan_updated.emit()

    def _complete_plan(self, plan: dict) -> None:
        """完成计划：成品入库 + 消耗 BPC + 置 completed（经 plan_execution.complete_plan）"""
        model = self._model
        if model is None:
            return
        from services import plan_execution

        res = plan_execution.complete_plan(plan)
        if not res.get("ok"):
            QMessageBox.warning(self, "完成失败", res.get("message", "未知错误"))
            return
        plan["status"] = "completed"
        plan["deposited"] = res.get("deposited", 0)
        plan["completed_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        plan["assigned_blueprint_id"] = None
        model.layoutChanged.emit()
        if not res.get("deposited"):
            QMessageBox.information(self, "完成", res.get("message", "计划已完成"))
        self._rebuild_subitems()
        self.plan_updated.emit()

    def _show_blueprint_picker(self, row: int) -> None:
        """单击蓝图列/右键菜单 → 绑定库存蓝图弹窗"""
        model = self._model
        if model is None:
            return
        plan = model.get_plan(row)
        if not plan:
            return
        from ui_pyside6.views.industry.blueprint_picker_dialog import BlueprintPickerDialog

        dlg = BlueprintPickerDialog(plan, self)
        if dlg.exec():
            bound = dlg.selected_blueprint_ids
            plan["assigned_blueprint_id"] = bound[0] if bound else None
            plan["bound_blueprint_ids"] = list(bound)
            plan["need_blueprints"] = int(dlg.need_count or 1)
            model.layoutChanged.emit()
            self.plan_updated.emit()

    def _delete_row(self, row: int) -> None:
        self._delete_rows([row])

    def _rebuild_subitems(self) -> None:
        """计划（母项）变更后自动联动重放子项。幂等：无拆解时零副作用。"""
        from services.plan_rebuild import rebuild_children

        try:
            rebuild_children()
        except Exception:
            from core.logger import log

            log.exception("自动重放子项失败")

    def _recalc_children(self, rows: list[int]) -> None:
        """手动兜底：按母项当前需求全量重放子项（数量/并行/ME 联动）。"""
        if self._model is None or not rows:
            return
        from PySide6.QtWidgets import QMessageBox

        from services.plan_rebuild import rebuild_children

        ret = QMessageBox.question(
            self,
            "重算子项",
            "按所有母项当前的需求（数量/并行/ME）重新生成子项产线？\n已投产中的子项流程不会被改动。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        res = rebuild_children(create=True, prune=True)
        QMessageBox.information(
            self,
            "完成",
            f"重算完成：新增 {res['created']}、更新 {res['updated']}、清理 {res['deleted']} 条子项",
        )
        self.plan_updated.emit()

    def _delete_rows(self, rows: list[int]) -> None:
        """批量删除多行。

        - 删母项：其引用的子项若不再被任何母项引用则级联收缩；仍被其他母项引用则保留。
        - 删子项（单独删某条产线）：删除后不会因后续编辑母项/重放被自动加回，
          仅显式「母项拆解/重算子项」才会重新生成。
        """
        if self._model is None:
            return
        plans = self._model._plans
        deleted_rows = [plans[r] for r in rows if 0 <= r < len(plans)]
        selected_ids = {p["id"] for p in deleted_rows if p.get("id")}
        if not selected_ids:
            return

        from services import plan_execution

        for pid in selected_ids:
            plan_execution.release_blueprint(pid)

        get_container().plan_repo.delete_many(list(selected_ids))
        self._model._plans = [p for p in plans if p.get("id") not in selected_ids]
        self._model.beginResetModel()
        self._model.endResetModel()

        from services.plan_rebuild import rebuild_children

        # 含母项删除 → 收缩不再被引用的子项；仅删子项 → 不重建不收缩（保持已删产线消失）
        if any(int(p.get("child_level") or p.get("sub_level") or 0) == 0 for p in deleted_rows):
            rebuild_children(create=False, prune=True)
        else:
            rebuild_children()
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

    def _view_cost_breakdown(
        self,
        row: int,
        *,
        price_type_mat: str | None = None,
        price_type_prod: str | None = None,
    ):
        # 右键菜单 -> 查看核算：打开成本明细弹窗
        from ui_pyside6.views.industry.cost_breakdown_dialog import CostBreakdownDialog

        plan = self._model.get_plan(row) if self._model else {}
        if not plan:
            return
        dlg = CostBreakdownDialog(
            plan,
            price_type_mat=price_type_mat,
            price_type_prod=price_type_prod,
        )
        from PySide6.QtCore import Qt

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # 保持引用：无 parent 的非模态对话框若仅靠局部变量持有，
        # Python GC 可能在对话框仍显示时回收包装对象 → 原生段错误（闪退）
        self._cost_breakdown_dlg = dlg
        dlg.show()

    def _phase3_placeholder(self, feature_name: str):
        QMessageBox.information(self, "功能开发中", f"「{feature_name}」功能将在阶段三实现。")

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

    def _selected_groups_and_children(self, selected_rows: list[int]) -> tuple[list[dict], list[dict]]:
        """从 model 全量 + 选中行索引聚合 (parents, children)。"""
        from services.plan_decompose import collect_group_members

        if self._model is None:
            return [], []
        selected = [self._model.get_plan(r) for r in selected_rows if 0 <= r < self._model.rowCount()]
        return collect_group_members(self._model._plans, [p for p in selected if p])

    def _decompose_parent(self, rows: list[int]) -> None:
        """母项调整：对选中母项递归拆解成子项产线（sub_level 逐级 +1）"""
        if self._model is None:
            return
        selected = [self._model.get_plan(r) for r in rows if 0 <= r < self._model.rowCount()]
        parents = [p for p in selected if p and int(p.get("child_level") or 0) == 0]
        if not parents:
            QMessageBox.information(self, "提示", "未选中母项")
            return
        from ui_pyside6.views.industry.parent_decompose_dialog import ParentDecomposeDialog

        dlg = ParentDecomposeDialog(parents, self)
        if dlg.exec():
            self.plan_updated.emit()

    def _adjust_children(self, rows: list[int]) -> None:
        """子项调整：跨选中行组内子项并行配置（runs/parallels + 需求校验）"""
        parents, children = self._selected_groups_and_children(rows)
        if not children:
            QMessageBox.information(self, "提示", "所选计划均不在组中或无子项可调整")
            return
        from ui_pyside6.views.industry.child_parallel_dialog import ChildParallelDialog

        dlg = ChildParallelDialog(parents + children, self)
        if dlg.exec():
            self.plan_updated.emit()

    def _mass_parallel(self, rows: list[int]) -> None:
        """子项大规模产线并行：按产线数 / 按目标工期 两种模式"""
        parents, children = self._selected_groups_and_children(rows)
        if not children:
            QMessageBox.information(self, "提示", "所选计划均不在组中或无子项可调整")
            return
        from ui_pyside6.views.industry.mass_parallel_dialog import MassParallelDialog

        dlg = MassParallelDialog(parents + children, self)
        if dlg.exec():
            self.plan_updated.emit()

    def _set_facility_system(self, row: int) -> None:
        """为设施设置所在星系 — 星系搜索对话框 + 自动带出成本系数"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return

        from ui_pyside6.dialogs.system_search_dialog import SystemSearchDialog

        dlg = SystemSearchDialog(self, "设置设施星系")
        if not dlg.exec():
            return
        sel = dlg.get_selected()
        if not sel:
            return
        ss_id, ss_name = sel

        # 更新内存 plan
        plan["facility"] = ss_name
        plan["solar_system_id"] = ss_id

        # 自动带出成本系数
        sci = get_container().pricing_service.get_system_cost_index(ss_id, "manufacturing")

        # 持久化（设施名 + 星系列）
        if plan.get("id"):
            get_container().plan_repo.update(plan["id"], facility=ss_name, solar_system_id=ss_id)

        self._model.layoutChanged.emit()
        self.plan_updated.emit()
        QMessageBox.information(
            self,
            "设置完成",
            f"设施星系: {ss_name}\n制造成本指数(SCI): {sci:.4f}\n\n可在「成本系数」中调整附加费率。",
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
        current_mult = float(plan.get("facility_cost_mult", 1.0) or 1.0)

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
            get_container().plan_repo.update(plan["id"], facility_cost_mult=val)

        QMessageBox.information(self, "设置完成", f"设施成本系数已设为 {val:.2f}x")

    def _show_production_wizard(self, row: int) -> None:
        """产线启动小助手：交给工业页统一打开（单实例），初始定位到该行所属人物。"""
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return
        self.launcher_requested.emit((plan.get("char_name") or "").strip())

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

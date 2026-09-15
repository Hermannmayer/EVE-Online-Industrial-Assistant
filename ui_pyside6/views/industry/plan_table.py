"""生产计划表格 — PlanTable 视图组件

**渲染已迁到 QML**（`ui_qml/qml/pages/PlanTablePane.qml`，阶段 2a）：本类不再持有
`QTableView`，而是持有一个 `QQuickWidget` 宿主 + `PlanTableBridge`。
对外 API（`get_model` / `set_model` / `set_price_context` / 四个信号）保持不变，
`industry_view.py` 与既有测试无需改动调用方式。

**业务逻辑全部留在这里**：启动/下线/删行/拆解/落库等仍是本类的方法，
QML 只通过 bridge 转发调用。这样迁移期只有一份业务实现。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QVBoxLayout, QWidget

import ui_pyside6.theme as theme
from core.container import get_container
from ui_qml.models.industry_models import PlanTableModel
from ui_qml.models.plan_table_constants import (
    COL_BLUEPRINT,
    COL_CHECKBOX,
    COL_NOTES,
    COL_PRODUCT,
    COL_STATUS,
)

if TYPE_CHECKING:
    from ui_qml.bridge.plan_table_bridge import PlanTableBridge
    from ui_qml.models.plan_qml_model import PlanQmlModel

#: QML 页面路径（相对 ui_qml/qml/）
QML_PANE = "pages/PlanTablePane.qml"


class PlanTable(QWidget):
    """生产计划表格 — QML 渲染 + 本类承载全部业务动作"""

    plan_updated = Signal()
    refresh_requested = Signal()
    plan_detail_requested = Signal(int)
    launcher_requested = Signal(str)  # 产线启动小助手（传初始人物名，空串=未分配）

    def __init__(self, parent: QWidget | None = None, *, headless: bool = False):
        """`headless=True` 时**不创建 QML 宿主**，只保留业务控制器身份。

        阶段 2b 起工业页整页是 QML，表格由 `IndustryPage.qml` 里的 `PlanTablePane`
        渲染、桥从 context 注入；本类再建一个宿主就是白开一个 QML 引擎。
        但业务方法与 `QMessageBox.question(self, ...)` 的窗口父仍需一个 QWidget，
        故保留 QWidget 身份（不显示即可）。
        """
        super().__init__(parent)

        # ui_qml 的导入放在这里而不是模块顶层：ui_qml 侧要读 industry 包的列常量，
        # 而本模块又由 industry/__init__.py 在包初始化时导入 —— 顶层导入会形成
        # 「包初始化 → plan_table → ui_qml → 包初始化」的循环。延迟到实例化时，
        # 那时包早已初始化完毕。
        from ui_qml.bridge.plan_table_bridge import PlanTableBridge

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model: PlanQmlModel | None = None
        # 工具栏当前材料机库 ID（由 IndustryPage 注入，启动时兜底）
        self._mat_hangar_id: int | None = None
        # 工具栏价格设置/人物访问器（由 IndustryPage 注入，母项拆解利润预览用）
        self._get_price_settings = None
        self._get_char_name = None

        self._bridge: PlanTableBridge = PlanTableBridge(self, self)
        self._host: PageHost | None = None
        if not headless:
            from ui_qml.host import PageHost

            self._host = PageHost(QML_PANE, context={"planTableBridge": self._bridge}, parent=self)
            layout.addWidget(self._host)

        theme.add_theme_listener(self._on_theme_changed)

    @property
    def bridge(self) -> PlanTableBridge:
        """给 QML 页面用的桥（工业页把表格嵌进自己的 QML 树时用）。"""
        return self._bridge

    # ── 公共方法 ──────────────────────────────────────────────

    def set_model(self, model: PlanTableModel) -> None:
        """设置模型。传进来的 `PlanTableModel` 会被换成 `PlanQmlModel` 实例。

        QML 的 `TableView` 要**命名角色**，只有 `PlanQmlModel` 提供 `roleNames()`。
        数据本身直接交给新实例，不做拷贝。
        """
        from ui_qml.models.plan_qml_model import PlanQmlModel

        qml_model = model if isinstance(model, PlanQmlModel) else PlanQmlModel(model._plans)
        self._model = qml_model
        self._bridge.notify_model_changed()

    def get_model(self) -> PlanQmlModel | None:
        return self._model

    def set_mat_hangar_id(self, mat_hangar_id: int | None) -> None:
        """注入工具栏当前材料机库 ID（启动时用于兜底旧计划）。"""
        self._mat_hangar_id = mat_hangar_id

    def set_price_context(self, get_price_settings, get_char_name) -> None:
        """注入工具栏价格设置/人物访问器（母项拆解利润预览用）。"""
        self._get_price_settings = get_price_settings
        self._get_char_name = get_char_name

    def _solar_system_for_mat_hangar(self, mat_hangar_id: int | None) -> int | None:
        """从材料机库带出所在星系 ID（材料在哪个星系造，成本指数就按它算）。"""
        from services import inventory_manager

        return inventory_manager.get_hangar_system_id(mat_hangar_id)

    def scroll_value(self) -> float:
        """当前纵向滚动位置（页面状态保存用）。"""
        return self._bridge.scroll_position()

    def set_scroll_value(self, value: float) -> None:
        """恢复纵向滚动位置。"""
        self._bridge.request_scroll_restore(float(value))

    def load_plans(self, plans: list[dict]) -> None:
        """创建新模型并设置"""
        from ui_qml.models.plan_qml_model import PlanQmlModel

        self.set_model(PlanQmlModel(plans))

    # ── QML 回调：单元格交互 ──────────────────────────────────

    def _on_cell_clicked_by_pos(self, row: int, column: int) -> None:
        """单击单元格：勾选 / 绑蓝图 / 折叠 / 待下线（对应 QML 的 `bridge.activate`）。

        与旧 `_on_cell_clicked(index)` 同一逻辑，只是入参从 `QModelIndex` 换成行列号。
        """
        if self._model is None:
            return
        plan = self._model.get_plan(row)
        if not plan:
            return
        if column == COL_CHECKBOX:
            self._set_materials_ready(row, 0 if plan.get("materials_ready", 0) else 1)
        elif column == COL_BLUEPRINT:
            self._show_blueprint_picker(row)
        elif column == COL_PRODUCT:
            if plan.get("_synthetic"):
                self._model.toggle_collapse(-1)
                return
            gid = plan.get("group_id") or plan.get("group_number") or 0
            lvl = int(plan.get("child_level") or plan.get("sub_level") or 0)
            if lvl == 0 and gid and self._model._has_children(gid):
                self._model.toggle_collapse(gid)
        elif column == COL_STATUS and (plan.get("status") or "").lower() == "ready":
            self._complete_plan_with_dialog(plan)

    def commit_cell_edit(self, row: int, column: int, text: str) -> bool:
        """QML 内联编辑落库入口（模型只改内存，这里负责写库）。

        返回 False 表示该列不可编辑或值非法。

        **只持久化备注列**，与迁移前一致：其余可编辑列（人物/设施/成功率/解码器）
        的内联改动仍只留在内存字典里。它们改完需要重算派生指标（走 `_edit_plan`
        那条会调 `calculate_plan_metrics` 的路径），单靠一次 `setData` 落库会留下
        与指标不一致的行——那是另一件事，不在阶段 2a 范围内。
        """
        if self._model is None:
            return False
        index = self._model.index(row, column)
        if not self._model.setData(index, text):
            return False
        # 不 emit plan_updated —— 那会触发 load_plans → set_plans（重置模型），
        # 让每次改备注都全表重载，并打断正在进行的编辑。
        if column == COL_NOTES:
            plan = self._model.get_plan(row)
            if plan and plan.get("id"):
                get_container().plan_repo.update(plan["id"], notes=str(plan.get("notes") or ""))
        return True

    def _complete_plan_with_dialog(self, plan: dict) -> None:
        """状态列「待下线」→ 下线确认弹窗（选产出机库）→ 单独下线。

        对话框/预检/失败提示都收敛在小助手共用的 `complete_one_plan`，这里只负责
        把成功结果回写到内存中的行。
        """
        from ui_pyside6.views.industry.complete_plans_dialog import complete_one_plan

        result = complete_one_plan(self, plan)
        if result is None:  # 用户取消或下线失败（已弹过告警）
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

    def _complete_rows_with_dialog(self, rows: list[int]) -> None:
        """批量下线：**一次**对话框选产出机库，再整批完成。

        右键「下线」是批量入口，逐行调 `_complete_plan_with_dialog` 会连弹 N 次框；
        这里复用 `complete_plans(plans, hangar_id)` 的单次对话流程。
        `deposit_hangar_id` 为空的行也在对话框里选机库，不再静默跳过入库。
        """
        if self._model is None:
            return
        ready = [p for p in (self._model.get_plan(r) for r in rows) if p and (p.get("status") or "").lower() == "ready"]
        if not ready:
            return
        from services.inventory_manager import get_hangars
        from services.user_settings import get_default_hangar_id
        from ui_pyside6.views.industry.complete_guard import confirm_bp_shortfall
        from ui_pyside6.views.industry.complete_plans_dialog import complete_plans
        from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog

        dlg = CompletePlansDialog(ready, get_hangars(), get_default_hangar_id("default_deposit_hangar_id"), self)
        if not dlg.exec():
            return
        allow_bp_short = confirm_bp_shortfall(self, ready)
        if allow_bp_short is None:
            return
        result = complete_plans(ready, dlg.selected_hangar_id(), allow_bp_short=allow_bp_short)
        if result["failed"]:
            detail = "\n".join(result.get("failed_reasons") or []) or "、".join(result["failed"])
            QMessageBox.warning(self, "下线失败", detail)
        self._rebuild_subitems()
        self.plan_updated.emit()

    def _edit_plan(self, row: int) -> None:
        """编辑生产计划 — 打开 PlanEditDialog（QML 版），保存后同步重算"""
        if self._model is None:
            return
        from ui_qml.bridge.plan_edit_bridge import PlanEditQmlDialog as PlanEditDialog

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
        from ui_qml.bridge.plan_edit_bridge import PlanEditQmlDialog as PlanEditDialog

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
        dlg.setStyleSheet(
            f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; font-size: {theme.fs(12)}px;"
        )

        root = QVBoxLayout(dlg)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # 从首行加载当前值
        first = self._model.get_plan(rows[0]) if rows else None
        cur_me = int(first.get("me_level", 0)) if first else 0
        cur_te = int(first.get("te_level", 0)) if first else 0

        # 已绑产线按各自绑定蓝图的等级结算，这里的计划级值只是**未绑线**的兜底 ——
        # 不说清楚用户会以为改了没生效（逐线计算上线后的语义变化）
        if first and first.get("bound_blueprint_ids"):
            hint = QLabel("已绑定产线的等级以各自绑定的蓝图为准；此处只影响**未绑定**的产线。")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
            root.addWidget(hint)

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
                f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; font-size: {theme.fs(12)}px;"
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

        # 软阻塞预检：材料缺口 / 蓝图流程不足 —— 两者都可强制启动
        allow_short = False
        allow_bp_short = False
        shortfalls: list[dict] = []
        if mat_hangar_id:
            shortfalls = [r for r in plan_execution.check_materials(plan, mat_hangar_id) if (r.get("missing") or 0) > 0]
        bp_short = plan_execution.binding_shortfall(plan["id"])

        reasons: list[str] = []
        if shortfalls:
            lines = "\n".join(f"  {r.get('name')}: 缺 {r.get('missing'):,.0f}" for r in shortfalls[:10])
            if len(shortfalls) > 10:
                lines += f"\n  … 等 {len(shortfalls)} 种"
            reasons.append(f"材料不足：\n{lines}")
        if bp_short:
            reasons.append(f"蓝图流程不足：{bp_short}")
        if reasons:
            ret = QMessageBox.question(
                self,
                "启动前确认",
                "\n\n".join(reasons) + "\n\n是否强制启动？\n"
                "材料按现有库存扣减、缺口记待补；蓝图**不会**自动补流程或换绑，"
                "完成时按实际可用流程消耗。\n"
                "由此产生的账面偏差，请稍后用「蓝图管理 → 粘贴导入蓝图 → 全量同步」矫正。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            allow_short = bool(shortfalls)
            allow_bp_short = bool(bp_short)

        res = plan_execution.start_plan(
            plan,
            mat_hangar_id=mat_hangar_id,
            allow_short=allow_short,
            allow_bp_short=allow_bp_short,
        )
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

    def _show_blueprint_picker(self, row: int) -> None:
        """单击蓝图列/右键菜单 → 绑定库存蓝图弹窗"""
        model = self._model
        if model is None:
            return
        plan = model.get_plan(row)
        if not plan:
            return
        from ui_qml.bridge.blueprint_picker_bridge import BlueprintPickerQmlDialog as BlueprintPickerDialog

        dlg = BlueprintPickerDialog(plan, self)
        if dlg.exec():
            bound = dlg.bridge.selected_ids()
            plan["assigned_blueprint_id"] = bound[0] if bound else None
            plan["bound_blueprint_ids"] = list(bound)
            plan["need_blueprints"] = dlg.bridge.need_count()
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
        """批量取消生产（解除蓝图绑定 + 删除计划行）。

        - 删母项：其引用的子项若不再被任何母项引用则级联收缩；仍被其他母项引用则保留。
        - 删子项（单独删某条产线）：删除后不会因后续编辑母项/重放被自动加回，
          仅显式「母项拆解/重算子项」才会重新生成。
        - **不返还已扣减材料**（领域模型见 AUDIT-20260801.md：与游戏「取消产线只退蓝图」一致）。
          在产计划被删后材料不会退回，所以删前必须让用户知情 —— 这也是以前缺的那道确认。
        """
        if self._model is None:
            return
        plans = self._model._plans
        deleted_rows = [plans[r] for r in rows if 0 <= r < len(plans)]
        selected_ids = {p["id"] for p in deleted_rows if p.get("id")}
        if not selected_ids:
            return

        running = [p for p in deleted_rows if (p.get("status") or "").lower() in ("in_progress", "running")]
        if running:
            names = "、".join(str(p.get("product_name") or p.get("id")) for p in running[:3])
            if len(running) > 3:
                names += f" 等 {len(running)} 条"
            text = (
                f"选中的 {len(selected_ids)} 条计划里有 {len(running)} 条正在生产：{names}。\n\n"
                "「取消生产」将解除蓝图绑定并删除计划行，\n"
                "已扣减的材料不会返还（与游戏「取消产线只退蓝图」一致）。\n\n"
                "若只是软件误点、游戏尚未开造，请改用「撤销启动（返还材料）」。\n\n"
                "确定继续？"
            )
        else:
            text = f"确定取消 {len(selected_ids)} 条计划？"
        ret = QMessageBox.question(
            self,
            "取消生产",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
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
        from ui_qml.bridge.all_items_bridge import MatQmlDialog as MatDlg

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
        from ui_qml.bridge.cost_breakdown_bridge import CostBreakdownQmlDialog as CostBreakdownDialog

        plan = self._model.get_plan(row) if self._model else {}
        if not plan:
            return
        # 未显式传入时跟随工具栏价格设置（含倍率），与主表批量重算口径一致
        ps: dict = self._get_price_settings() if self._get_price_settings else {}
        if price_type_mat is None and ps:
            price_type_mat = str(ps.get("mat_price_type") or "") or None
        if price_type_prod is None and ps:
            price_type_prod = str(ps.get("prod_price_type") or "") or None
        dlg = CostBreakdownDialog(
            plan,
            price_type_mat=price_type_mat,
            price_type_prod=price_type_prod,
            mat_mult=float(ps.get("mat_mult") or 1.0) if ps else 1.0,
            prod_mult=float(ps.get("prod_mult") or 1.0) if ps else 1.0,
        )
        from PySide6.QtCore import Qt

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # 保持引用：无 parent 的非模态对话框若仅靠局部变量持有，
        # Python GC 可能在对话框仍显示时回收包装对象 → 原生段错误（闪退）
        self._cost_breakdown_dlg = dlg
        dlg.show()

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
        from ui_qml.bridge.npc_seller_bridge import NpcSellerQmlDialog

        dlg = NpcSellerQmlDialog(bp_id, bp_name, self)
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
        from ui_qml.bridge.parent_decompose_bridge import ParentDecomposeQmlDialog as ParentDecomposeDialog

        dlg = ParentDecomposeDialog(
            parents,
            self,
            price_settings=self._get_price_settings() if self._get_price_settings else None,
            default_char_name=self._get_char_name() if self._get_char_name else "",
        )
        if dlg.exec():
            self.plan_updated.emit()

    def _adjust_children(self, rows: list[int]) -> None:
        """子项调整：跨选中行组内子项并行配置（runs/parallels + 需求校验）"""
        parents, children = self._selected_groups_and_children(rows)
        if not children:
            QMessageBox.information(self, "提示", "所选计划均不在组中或无子项可调整")
            return
        from ui_qml.bridge.child_parallel_bridge import ChildParallelQmlDialog as ChildParallelDialog

        dlg = ChildParallelDialog(parents + children, self)
        if dlg.exec():
            self.plan_updated.emit()

    def _mass_parallel(self, rows: list[int]) -> None:
        """子项大规模产线并行：按产线数 / 按目标工期 两种模式"""
        parents, children = self._selected_groups_and_children(rows)
        if not children:
            QMessageBox.information(self, "提示", "所选计划均不在组中或无子项可调整")
            return
        from ui_qml.bridge.mass_parallel_bridge import MassParallelQmlDialog as MassParallelDialog

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

        from ui_qml.bridge.system_search_bridge import SystemSearchQmlDialog

        dlg = SystemSearchQmlDialog(self, "设置设施星系")
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
        """主题切换：模型里的颜色是**已解析的 hex**（见 `PlanQmlModel` 的说明），
        必须补发一次 dataChanged 才会重绘。
        """
        self._bridge.refreshColors()

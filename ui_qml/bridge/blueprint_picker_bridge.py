"""绑定库存蓝图对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/blueprint_picker_dialog.py`：
一条产线（parallels 之一）独占一张库存蓝图，勾选 parallels 张可用蓝图，
每张可用流程 ≥ runs。**勾选即实时落库**（勾选集 = 最终绑定集，全量替换）。

与原版逐条对齐的行为：

- 绑定状态以 DB 为权威（`plan_execution.get_plan_binding_state`），不信任传入的 plan dict；
- 被其他活跃计划占用的行禁勾选；自己已绑定的行不算占用，默认勾选；
- 满额（已勾 = 需求）后再勾会**回滚并提示**，不做静默截断；
- 写入失败（竞态：刚被别的计划占用）→ 按 DB 现状还原勾选 + 红字提示。

差异：原版用 `QMessageBox` 弹确认/警告，这里改成桥的提示文案（页面已经是 QML）；
「完成」时绑定不足也改成本地两步确认（`pendingClose`），不弹原生框。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from services import plan_execution
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["BlueprintPickerBridge", "BlueprintPickerQmlDialog"]

_QML_FILE = "dialogs/BlueprintPickerDialog.qml"

_BIG_INFINITY = 10**15

#: 表格文本列（复选框列由 QML 单独画）
_HEADERS = ["类型", "ME", "TE", "可用流程", "机库", "状态"]


def available_runs(opt: dict) -> int:
    """BPC 可用流程 = quantity×runs；BPO 视为无限（纯函数，原样搬过来）。"""
    if opt.get("is_bpo"):
        return _BIG_INFINITY
    return int(opt.get("available_runs") or 0)


class BlueprintPickerBridge(DialogBridge):
    """蓝图多选绑定的 QML 后端。"""

    contentChanged = Signal()

    def __init__(self, plan: dict) -> None:
        super().__init__()
        from services.industry_dialog_queries import get_blueprint_picker_data

        self._plan = plan
        self._blueprint_type_id: int | None = None
        self._options: list[dict] = []
        self._checked: list[bool] = []
        self._disabled: list[bool] = []
        self._rows: list[dict] = []
        self._empty_hint = ""
        self._status_text = ""
        self._status_token = ""
        self._pending_close = False
        self._loading = True
        self._need = 1
        self._runs = 1
        self._selected_ids: list[int] = []

        self.set_title(f"绑定库存蓝图 - {plan.get('product_name', '')}")
        self._get_picker_data = get_blueprint_picker_data
        self._load()

    # ── 只读输出 ──────────────────────────────────────────────

    needLabel = Property(str, lambda self: self._need_label(), notify=contentChanged)
    headers = Property(list, lambda self: list(_HEADERS), constant=True)
    rows = Property(list, lambda self: list(self._rows), notify=contentChanged)
    statusText = Property(str, lambda self: self._status_text, notify=contentChanged)
    statusToken = Property(str, lambda self: self._status_token, notify=contentChanged)
    emptyHint = Property(str, lambda self: self._empty_hint, notify=contentChanged)
    hasOptions = Property(bool, lambda self: bool(self._options), notify=contentChanged)
    canNpcSeller = Property(bool, lambda self: self._blueprint_type_id is not None, notify=contentChanged)
    #: 确认后的绑定集合（调用方用它回填 plan dict）
    selectedBlueprintIds = Property(list, lambda self: list(self._selected_ids), notify=contentChanged)
    needCount = Property(int, lambda self: self._need, notify=contentChanged)

    def _need_label(self) -> str:
        return (
            f"产品 {self._plan.get('product_name', '')}  "
            f"需 {self._need} 张蓝图（{self._need} 条并行产线）× 每条 {self._runs} 流程"
        )

    # ── 数据加载 ──────────────────────────────────────────────

    def _load(self) -> None:
        """读绑定状态 + 可选蓝图，构建行（原 `_load` 逐行照搬）。"""
        plan_id = self._plan.get("id")
        product_type_id = self._plan.get("product_type_id")
        runs = max(int(self._plan.get("runs", 1)), 1)

        # 以 DB 权威值为准读取当前绑定与产线数
        state: dict = (
            plan_execution.get_plan_binding_state(plan_id)
            if plan_id
            else {"bound": [], "need": int(self._plan.get("parallels") or 1), "runs": runs}
        )
        bound_ids = list(state.get("bound") or [])
        need = max(int(state.get("need") or 1), 1)
        db_runs = max(int(state.get("runs") or 1), 1)
        self._need = need
        self._runs = db_runs

        blueprint_type_id, options = self._get_picker_data(get_container().db, int(product_type_id or 0))
        self._blueprint_type_id = blueprint_type_id
        if blueprint_type_id is None:
            self._empty_hint = "无法确定该产品的蓝图类型"
            self._options = []
            self._loading = False
            self._rebuild()
            return
        self._options = options
        if not options:
            self._empty_hint = "库存中没有该蓝图。可通过「查看NPC卖家」购买原图，或从游戏粘贴导入。"
            self._loading = False
            self._rebuild()
            return

        # 占用校正：排除本计划自身占用（自己已绑定的 BPC 显示可用、默认勾选）
        occupied_others = plan_execution.get_occupied_blueprint_ids(get_container().db, exclude_plan_id=plan_id)
        bound_set = set(bound_ids)
        self._checked = [bool(opt["id"] in bound_set) for opt in options]
        self._disabled = [
            bool((opt.get("occupied") or opt["id"] in occupied_others) and opt["id"] not in bound_set)
            for opt in options
        ]
        self._loading = False
        self._reconcile()

    # ── 行渲染 ────────────────────────────────────────────────

    def _rebuild(self) -> None:
        """把选项 + 勾选/禁用状态渲染成视图模型（颜色在 Python 侧算）。"""
        rows: list[dict] = []
        for i, opt in enumerate(self._options):
            disabled = self._disabled[i] if i < len(self._disabled) else False
            is_bpo = bool(opt.get("is_bpo"))
            avail = available_runs(opt)
            runs_short = not is_bpo and avail < self._runs
            occupied = disabled  # 被其他计划占用（自己绑定的不算）
            if occupied:
                status, token = "占用中", "TEXT_SECONDARY"
            elif runs_short:
                status, token = "流程不足", "ACCENT_ORANGE"
            else:
                status, token = "可用", "TEXT_PRIMARY"
            rows.append(
                {
                    "index": i,
                    "checkable": not disabled,
                    "checked": self._checked[i] if i < len(self._checked) else False,
                    "disabled": disabled,
                    "cells": [
                        cell("原图" if is_bpo else "拷贝"),
                        cell(str(opt.get("me_level", 0))),
                        cell(str(opt.get("te_level", 0))),
                        cell("无限" if is_bpo else f"{avail:,}"),
                        cell(opt.get("hangar_name", "") or "-"),
                        cell(status, token),
                    ],
                }
            )
        self._rows = rows
        self.contentChanged.emit()

    # ── 交互 ──────────────────────────────────────────────────

    def _count_checked(self) -> int:
        return sum(1 for i, on in enumerate(self._checked) if on and not self._disabled[i])

    @Slot(int, bool)
    def toggle(self, index: int, checked: bool) -> None:
        """勾选变化：一条产线一张蓝图，最多勾 need 张，超出的勾选回滚并提示。"""
        if self._loading or not 0 <= index < len(self._options) or self._disabled[index]:
            return
        self._checked[index] = bool(checked)
        self._pending_close = False
        if checked and self._count_checked() > max(int(self._need), 1):
            self._checked[index] = False
            self._rebuild()
            self._refresh_status(truncated=True)
            return
        self._reconcile()

    @Slot(list)
    def checkRows(self, indices: list) -> None:
        """右键批量勾选（原 `_set_selected_checked(rows, True)`）。

        注意参数是**行号**（QML 选中态 `selRows`），与 `selectedBlueprintIds`
        给出的蓝图 id 不是一回事。
        """
        self._bulk(indices, lambda i: True)

    @Slot(list)
    def uncheckRows(self, indices: list) -> None:
        self._bulk(indices, lambda i: False)

    @Slot(list)
    def onlyKeep(self, indices: list) -> None:
        """仅保留所选（取消其他）。"""
        keep = {int(i) for i in indices}
        self._pending_close = False
        for i in range(len(self._options)):
            if not self._disabled[i]:
                self._checked[i] = i in keep
        self._reconcile()

    def _bulk(self, indices: list, value: Any) -> None:
        self._pending_close = False
        for raw in indices:
            i = int(raw)
            if 0 <= i < len(self._options) and not self._disabled[i]:
                self._checked[i] = bool(value(i))
        self._reconcile()

    def _reconcile(self) -> None:
        """收集勾选集 → 全量替换写入绑定 → 刷新状态（原 `_reconcile`）。"""
        plan_id = self._plan.get("id")
        checked = [int(opt["id"]) for i, opt in enumerate(self._options) if self._checked[i] and not self._disabled[i]]
        need = max(int(self._need), 1)
        truncated = len(checked) > need
        if truncated:
            checked = checked[:need]

        if plan_id and not plan_execution.bind_blueprints(plan_id, checked):
            # 竞态：刚被其他计划占用 → 按 DB 现状还原勾选
            state = plan_execution.get_plan_binding_state(plan_id)
            valid = set(state["bound"])
            for i, opt in enumerate(self._options):
                self._checked[i] = opt["id"] in valid
            self._selected_ids = checked
            self._rebuild()
            self._status_text = "所选蓝图刚被其他活跃计划占用，已还原为当前绑定，请重新勾选"
            self._status_token = "ACCENT_RED"
            self.contentChanged.emit()
            return

        self._selected_ids = checked
        self._refresh_status(truncated=truncated)

    def _refresh_status(self, *, truncated: bool = False) -> None:
        count = len(self._selected_ids)
        need = max(int(self._need), 1)
        if truncated:
            self._status_text = f"一条产线一张蓝图：已按需取前 {need} 张兑现（勾选 {count} → 绑 {need} 张）"
            self._status_token = "ACCENT_ORANGE"
        elif count >= need:
            self._status_text = f"已选 {count} / 需 {need} 张 ✔"
            self._status_token = "GREEN"
        else:
            self._status_text = f"已选 {count} / 需 {need} 张 — 还差 {need - count} 张蓝图"
            self._status_token = "ACCENT_RED"
        self._rebuild()

    # ── 按钮 ──────────────────────────────────────────────────

    @Slot()
    def npcSeller(self) -> None:
        """查看NPC卖家。"""
        if self._blueprint_type_id is None:
            return

        from ui_qml.bridge.npc_seller_bridge import NpcSellerQmlDialog

        name = self._plan.get("product_name", str(self._blueprint_type_id))
        parent = self.host_widget()
        NpcSellerQmlDialog(self._blueprint_type_id, name, parent).exec()

    @Slot()
    def accept(self) -> None:
        """「完成」：绑定不足时先在本地确认一次，再点一次才关闭（替代原生确认框）。"""
        count = len(self._selected_ids)
        need = max(int(self._need), 1)
        if count < need and not self._pending_close:
            self._pending_close = True
            self.set_error(
                f"当前仅绑定 {count}/{need} 条产线的蓝图，不足部分完成后无法启动。仍要关闭请再点一次「完成」。"
            )
            return
        self.accepted.emit()

    def selected_ids(self) -> list[int]:
        """给 Python 侧读绑定集合（`selectedBlueprintIds` 在 mypy 眼里是 Property 描述符）。"""
        return list(self._selected_ids)

    def need_count(self) -> int:
        """给 Python 侧读需要的产线条数（同上，`needCount` 是 Property）。"""
        return int(self._need)


class BlueprintPickerQmlDialog(QmlDialog):
    """QML 版「绑定库存蓝图」。`BlueprintPickerDialog(plan, parent)` 的调用方原样可用。"""

    def __init__(self, plan: dict, parent: Any = None) -> None:
        bridge = BlueprintPickerBridge(plan)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(720, 520))

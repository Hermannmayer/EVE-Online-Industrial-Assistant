"""绑定库存蓝图对话框的桥（阶段 4）。

对照旧 Widgets 版：
一条产线（parallels 之一）独占一张库存蓝图，勾选 parallels 张可用蓝图，
每张可用流程 ≥ runs。

**勾选阶段不落库，点「完成」才写**（2026-09-27 改）。原实现是「勾选即实时落库」：
每次勾选都全量替换写库 + `_rebuild()` 换掉整个行模型，而 QML 那边 `model` 是普通
var 列表（不是 `QAbstractItemModel`）→ `ListView` 整体重建、**滚动位置回顶**。
用户实测：滑到中段勾第一格，列表直接跳回最顶端，于是「多选」根本没法用。

现在的分工：

- **行数据是常量**（`rows`，`constant=True`）：只有装载时算一次，勾选永远不碰它；
- **勾选态单独承载**：`checkedIndexes` / `isChecked()` + `checkRevisionChanged` 心跳，
  QML 的复选框按心跳回读（超需回滚、右键批量勾选都能同步过去）；
- **写库只发生在 `accept()`**（「完成」）：「取消 / 点 X」不写任何东西。

其余行为与原版逐条对齐：

- 绑定状态以 DB 为权威（`plan_execution.get_plan_binding_state`），不信任传入的 plan dict；
- 被其他活跃计划占用的行禁勾选；自己已绑定的行不算占用，默认勾选；
- 满额（已勾 = 需求）后再勾会**回滚并提示**，不做静默截断；
- 写入失败（竞态：刚被别的计划占用）→ 按 DB 现状还原勾选 + 红字提示，且**不关窗**。

差异：原版用 `QMessageBox` 弹确认/警告，这里改成桥的提示文案（页面已经是 QML）；
「完成」时绑定不足也改成本地两步确认（`pendingClose`），不弹原生框。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from services import plan_execution
from services.plan_job_kinds import RULE_BPC_RUNS, RULE_BPO_ONLY, input_blueprint_rule
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["BlueprintPickerBridge", "BlueprintPickerQmlDialog"]

_QML_FILE = "dialogs/BlueprintPickerDialog.qml"

_BIG_INFINITY = 10**15

#: 表格文本列（复选框列由 QML 单独画）
_HEADERS = ["类型", "ME", "TE", "可用流程", "机库", "状态"]

#: 输入蓝图规则 → `needLabel` 里的名词（「需 N 张<这个>」）。活动真源见 `services.plan_job_kinds`。
_NEED_KIND_TEXT: dict[str, str] = {
    RULE_BPC_RUNS: "蓝图拷贝",  # 发明：T1 BPC
    RULE_BPO_ONLY: "蓝图原本",  # 拷贝 / 研究：只能是原图
}
#: 输入蓝图规则 → 空态提示里的括注（没有对应规则就不括注）
_EMPTY_KIND_TEXT: dict[str, str] = {
    RULE_BPC_RUNS: "（BPC 拷贝）",
    RULE_BPO_ONLY: "（BPO 原本）",
}


def available_runs(opt: dict) -> int:
    """BPC 可用流程 = quantity×runs；BPO 视为无限（纯函数，原样搬过来）。"""
    if opt.get("is_bpo"):
        return _BIG_INFINITY
    return int(opt.get("available_runs") or 0)


class BlueprintPickerBridge(DialogBridge):
    """蓝图多选绑定的 QML 后端。"""

    #: 静态内容（行 / 表头 / 空态提示）变化 —— **只在装载时发一次**（`rows` 是常量）
    contentChanged = Signal()
    #: 状态行（计数 / 提示）变化
    statusChanged = Signal()
    #: 勾选态心跳：QML 的每个复选框靠它把自己拉回与桥一致（含超需回滚、右键批量）
    checkRevisionChanged = Signal()

    def __init__(self, plan: dict) -> None:
        super().__init__()
        from services.industry_dialog_queries import get_blueprint_picker_data

        self._plan = plan
        self._blueprint_type_id: int | None = None
        self._bp_name = ""
        self._kind_label_text = "蓝图"
        self._empty_kind_label = ""
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
        self._check_revision = 0

        self.set_title(f"绑定库存蓝图 - {plan.get('product_name', '')}")
        self._get_picker_data = get_blueprint_picker_data
        self._load()

    # ── 只读输出 ──────────────────────────────────────────────

    needLabel = Property(str, lambda self: self._need_label(), notify=contentChanged)
    headers = Property(list, lambda self: list(_HEADERS), constant=True)
    #: 行数据**常量**：勾选态不在其中（`checked` 只作打开时的初值）。
    #: 每次交互重建它 = ListView 重建 = 滚动位置回顶，见模块 docstring。
    rows = Property(list, lambda self: list(self._rows), constant=True)
    statusText = Property(str, lambda self: self._status_text, notify=statusChanged)
    statusToken = Property(str, lambda self: self._status_token, notify=statusChanged)
    emptyHint = Property(str, lambda self: self._empty_hint, notify=contentChanged)
    hasOptions = Property(bool, lambda self: bool(self._options), notify=contentChanged)
    canNpcSeller = Property(bool, lambda self: self._blueprint_type_id is not None, notify=contentChanged)
    #: 当前勾选集合（点「完成」前的暂存值；调用方在 `exec()` 返回真之后读它 = 已落库那份）
    selectedBlueprintIds = Property(list, lambda self: list(self._selected_ids), notify=statusChanged)
    needCount = Property(int, lambda self: self._need, notify=contentChanged)
    #: 勾选态心跳（自增），见 `checkRevisionChanged`
    checkRevision = Property(int, lambda self: self._check_revision, notify=checkRevisionChanged)

    def _need_label(self) -> str:
        """需求行 —— **要绑的是哪一张蓝图**（解析不出名字时退回旧文案）。

        只写「需 N 张蓝图」时，科研行（发明/拷贝/研究）的用户根本不知道要绑定的是
        哪张图；名字由活动感知查询给出（发明 = T2 反查出的 T1）。
        """
        product = self._plan.get("product_name", "")
        if self._bp_name:
            return (
                f"产品 {product}  需 {self._need} 张{self._kind_label_text}「{self._bp_name}」"
                f"（{self._need} 条并行产线）× 每条 {self._runs} 流程"
            )
        return f"产品 {product}  需 {self._need} 张蓝图（{self._need} 条并行产线）× 每条 {self._runs} 流程"

    # ── 数据加载 ──────────────────────────────────────────────

    def _load(self) -> None:
        """读绑定状态 + **按活动**解析该计划要绑的那张蓝图，构建行（原 `_load` 逐行照搬）。

        查询走 `get_blueprint_picker_data(db, plan)`（活动感知）。以前按
        `product_type_id` 反查 `activity='manufacturing'`：科研行的 `product_type_id`
        本身就是一张蓝图、反查不到 → 整个弹窗空白（用户报的「点『蓝图差几张』弹出空白」）。
        """
        plan_id = self._plan.get("id")
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

        # 需求行/空态文案里的名词由输入蓝图规则决定（发明只能绑 BPC、拷贝/研究只能绑 BPO）
        rule = input_blueprint_rule(self._plan.get("activity"))
        self._kind_label_text = _NEED_KIND_TEXT.get(rule, "蓝图")
        self._empty_kind_label = _EMPTY_KIND_TEXT.get(rule, "")

        data = self._get_picker_data(get_container().db, self._plan)
        self._blueprint_type_id = data.get("type_id")
        self._bp_name = str(data.get("name") or "")
        is_blueprint = bool(data.get("is_blueprint", True))

        if self._blueprint_type_id is None:
            # 空态也要说清「这张计划本来该绑哪张蓝图」：活动 + 蓝图库里没有配方行
            act = self._plan.get("activity") or "manufacturing"
            self._empty_hint = f"解析不出该计划要绑的输入蓝图（活动：{act}）—— 蓝图库里没有对应的配方行"
            self._options = []
            self._loading = False
            self._rebuild()
            return
        if not is_blueprint:
            # T3 发明的输入是古遗物：有类型、有名字，但库存蓝图库里永远没有它
            self._empty_hint = (
                f"该作业的输入是「{self._bp_name}」，不是蓝图（T3 发明的输入是古遗物），无法在蓝图库里绑定"
            )
            self._options = []
            self._loading = False
            self._rebuild()
            return

        options = list(data.get("options") or [])
        self._options = options
        if not options:
            self._empty_hint = (
                f"库存里没有「{self._bp_name}」{self._empty_kind_label}。"
                "可在蓝图管理里从游戏粘贴导入，或用「查看NPC卖家」购买原图。"
            )
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
        # 行数据只在这里算一次（之后是常量，勾选不再重建它）；勾选态走心跳通道
        self._rebuild()
        self._sync_checks()

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
    #
    # **勾选阶段一律不写库、不重建 `rows`**：写库在 `accept()`，重建 `rows` 会换掉
    # QML 的 ListView model（普通 var 列表）→ 滚动位置回顶，正是「滑到中段勾一格就跳回
    # 最顶端」的成因。勾选态只改 `_checked` 并打一次 `checkRevisionChanged` 心跳。

    def _count_checked(self) -> int:
        return sum(1 for i, on in enumerate(self._checked) if on and not self._disabled[i])

    def _pending_ids(self) -> list[int]:
        """按行序取勾选集合（行序 = 蓝图 id 顺序，与旧 `_reconcile` 的 `checked[:need]` 同口径）。"""
        return [
            int(o["id"])
            for i, o in enumerate(self._options)
            if i < len(self._checked) and self._checked[i] and not self._disabled[i]
        ]

    def _cap_checked(self) -> bool:
        """超需 → 从**行号大**的一头回滚；返回是否回滚过（批量勾选走这条）。"""
        need = max(int(self._need), 1)
        if self._count_checked() <= need:
            return False
        keep = 0
        for i in range(len(self._options)):
            if self._checked[i] and not self._disabled[i]:
                keep += 1
                if keep > need:
                    self._checked[i] = False
        return True

    def _sync_checks(self, *, truncated: bool = False) -> None:
        """勾选态变化的统一出口：算选中集 + 状态行 + 心跳。**不碰 `rows`**。"""
        self._selected_ids = self._pending_ids()
        self._check_revision += 1
        self._refresh_status(truncated=truncated)
        self.checkRevisionChanged.emit()

    @Slot(int, bool)
    def toggle(self, index: int, checked: bool) -> None:
        """勾选变化：一条产线一张蓝图，最多勾 need 张，超出的**这一次勾选**回滚并提示。"""
        if self._loading or not 0 <= index < len(self._options) or self._disabled[index]:
            return
        self._checked[index] = bool(checked)
        self._pending_close = False
        truncated = False
        if checked and self._count_checked() > max(int(self._need), 1):
            self._checked[index] = False
            truncated = True
        self._sync_checks(truncated=truncated)

    @Slot(int, result=bool)
    def isChecked(self, index: int) -> bool:
        """某行当前是否勾选 —— QML 的复选框靠它回读，超需回滚 / 右键批量都能同步回去。"""
        if not 0 <= index < len(self._checked):
            return False
        if index < len(self._disabled) and self._disabled[index]:
            return False
        return bool(self._checked[index])

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
        self._sync_checks(truncated=self._cap_checked())

    def _bulk(self, indices: list, value: Any) -> None:
        self._pending_close = False
        for raw in indices:
            i = int(raw)
            if 0 <= i < len(self._options) and not self._disabled[i]:
                self._checked[i] = bool(value(i))
        self._sync_checks(truncated=self._cap_checked())

    def _refresh_status(self, *, truncated: bool = False) -> None:
        count = len(self._selected_ids)
        need = max(int(self._need), 1)
        if truncated:
            self._status_text = f"一条产线一张蓝图：已按需保留前 {need} 张（多勾的已取消）"
            self._status_token = "ACCENT_ORANGE"
        elif count >= need:
            self._status_text = f"已选 {count} / 需 {need} 张 ✔ 点「完成」写入"
            self._status_token = "GREEN"
        else:
            self._status_text = f"已选 {count} / 需 {need} 张 — 还差 {need - count} 张蓝图"
            self._status_token = "ACCENT_RED"
        self.statusChanged.emit()

    # ── 按钮 ──────────────────────────────────────────────────

    @Slot()
    def npcSeller(self) -> None:
        """查看NPC卖家 —— 卖家窗的标题用**要绑的那张蓝图**的名字。

        以前拿 `plan["product_name"]`：科研行那是**产物**的名字（发明 = 产出的 T2 蓝图），
        跟 NPC 卖的输入 T1 原图对不上，标题会指错图。
        """
        if self._blueprint_type_id is None:
            return

        from ui_qml.bridge.npc_seller_bridge import NpcSellerQmlDialog

        name = self._bp_name or self._plan.get("product_name") or str(self._blueprint_type_id)
        parent = self.host_widget()
        NpcSellerQmlDialog(self._blueprint_type_id, name, parent).show()

    @Slot()
    def accept(self) -> None:
        """「完成」：**这一次**才把勾选集写库；绑定不足时先在本地确认一次（点两次才关）。

        先确认再写：不足的那一次不进 `_commit`，所以「取消 / 点 X」不会留下任何写入。
        """
        count = len(self._selected_ids)
        need = max(int(self._need), 1)
        if count < need and not self._pending_close:
            self._pending_close = True
            self.set_error(
                f"当前仅选 {count}/{need} 条产线的蓝图，不足部分完成后无法启动。仍要关闭请再点一次「完成」。"
            )
            return
        if not self._commit(self._pending_ids()):
            return
        self.accepted.emit()

    def _commit(self, checked: list[int]) -> bool:
        """把勾选集**全量替换**写库（一条产线一张蓝图）。

        竞态（刚被别的活跃计划占用）→ 按 DB 现状还原勾选 + 红字提示，**不关窗**，
        与原 `_reconcile` 的失败口径一致。
        """
        plan_id = self._plan.get("id")
        if plan_id and not plan_execution.bind_blueprints(plan_id, checked):
            state = plan_execution.get_plan_binding_state(plan_id)
            valid = set(state["bound"])
            for i, opt in enumerate(self._options):
                self._checked[i] = opt["id"] in valid
            self._selected_ids = self._pending_ids()
            self._status_text = "所选蓝图刚被其他活跃计划占用，已还原为当前绑定，请重新勾选"
            self._status_token = "ACCENT_RED"
            self._check_revision += 1
            self.statusChanged.emit()
            self.checkRevisionChanged.emit()
            return False
        self._selected_ids = checked
        return True

    def selected_ids(self) -> list[int]:
        """给 Python 侧读绑定集合（`selectedBlueprintIds` 在 mypy 眼里是 Property 描述符）。"""
        return list(self._selected_ids)

    def need_count(self) -> int:
        """给 Python 侧读需要的产线条数（同上，`needCount` 是 Property）。"""
        return int(self._need)


class BlueprintPickerQmlDialog(QmlDialog):
    """QML 版「绑定库存蓝图」。`BlueprintPickerDialog(plan, parent)` 的调用方原样可用。

    `size` 由 720×520 收窄到 **540×470**（2026-09-27）：列宽改成「按内容取值、只让状态列吃
    余量」之后，720 宽会在「机库」和「状态」之间空出一大块 —— 用户报的「错位、不紧凑」
    有一半来自这个多出来的宽度。窗口仍可拉大（多出来的宽度进状态列）。
    """

    def __init__(self, plan: dict, parent: Any = None) -> None:
        bridge = BlueprintPickerBridge(plan)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(540, 470))

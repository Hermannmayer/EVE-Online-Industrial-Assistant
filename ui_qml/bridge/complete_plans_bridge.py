"""下线确认对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/complete_plans_dialog.py` 里的
`CompletePlansDialog`：展示待下线清单 + 选产出机库。

**产出量与流水号的计算留在 `complete_plans_dialog` 的既有函数里**
（`complete_plans` / `complete_one_plan` / `_ask_invention_outcome` 都是模块级业务函数，
不随对话框迁移），本桥只负责把它算好的清单画出来并回传选中的机库。

**逐条选产出机库**（2026-09-25 修回）：`d2ac6a2`(2026-09-11) 把批量下线从「逐行沿用各
计划自己配好的机库」退化成「一个下拉覆盖整批」，且初值取的是**全局默认**而不是该计划自己
存的值。现在每行一个下拉，初值 = 该计划的 `deposit_hangar_id`（查不到再退化默认值、
再退化第一个真实机库）；底部那一个降级成「统一设为」，一次写全部行。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["CompletePlansBridge", "CompletePlansQmlDialog"]

_QML_FILE = "dialogs/CompletePlansDialog.qml"


class CompletePlansBridge(DialogBridge):
    """下线确认的 QML 后端。

    **逐行机库是 `_hangar_indexes`（与 `plans` 同序），不再是单个标量。**
    """

    selectionChanged = Signal()
    #: 清单行**整体**变了 —— 只有「统一设为」发它。
    #:
    #: 为什么单独一个信号：QML 的 `Repeater.model` 是 JS 数组，通知一次就**整体重建委托**
    #: （这正是重排「统一设为」所需要的，见 `rows`）。但逐行改一格时不必付这个代价 ——
    #: 那一行的 `currentIndex` 已经是用户刚选的值了（样式自己赋的），重建纯属浪费，
    #: 还会在弹出层正在收起时销毁它的宿主委托。
    rowsChanged = Signal()

    def __init__(
        self,
        plans: list[dict],
        hangars: list[dict],
        default_hangar_id: int | None,
        *,
        count_text: str,
        rows: list[dict],
        total_qty: int,
    ) -> None:
        super().__init__()
        self._plans = plans
        self._hangars = [{"id": -1, "name": "不自动入库"}] + [dict(h) for h in hangars]
        self._rows = rows
        self._total_qty = int(total_qty)
        self.set_title("下线确认")

        self._default_hangar_id = default_hangar_id
        #: 每行的机库下标，与 `plans` 同序（`hangarIndexAt` / `selected_hangar_ids` 都读它）
        self._hangar_indexes = [self._initial_index(p) for p in plans]
        #: 自增心跳：见 `hangarRevision`
        self._revision = 0
        self._count_text = count_text

    # ── 只读展示 ──

    tipText = Property(
        str,
        lambda self: "以下「待下线」计划将被下线（产出成品入库，不可逆）：",
        constant=True,
    )
    #: 列标题（第 4 列现在是**逐行下拉**，不再是只读的「当前机库」）
    headers = Property(list, lambda self: ["产物", "流程", "产出量", "产出机库"], constant=True)
    #: 清单行 [{name, runs, qty}]（与 Widgets 版一致）
    #:
    #: ⚠️ 第 4 列的机库**不在这里** —— 它在 `hangarIndexAt()`。这样 `rows` 保持「纯展示」，
    #: 也免得每行重复一份会变的状态。
    #:
    #: `notify=rowsChanged` 的唯一目的是让「统一设为」能重排所有行：QML 的 `Repeater.model`
    #: 拿到的是 JS 数组，通知一次就整体重建委托。**不能只靠 `hangarRevision` 心跳** ——
    #: 用户点过某行之后，Qt 样式的委托里 `currentIndex = index` 是 JS 赋值，绑定已被摘掉
    #: （离屏实测：改统一值后那一行仍是用户先前选的），必须重建委托才能把绑定重新建起来。
    rows = Property(list, lambda self: list(self._rows), notify=rowsChanged)
    summaryText = Property(
        str,
        lambda self: f"{self._count_text}，产出 {self._total_qty:,} 件",
        constant=True,
    )

    # ── 产出机库 ──

    hangarNames = Property(list, lambda self: [h["name"] for h in self._hangars], constant=True)

    @Property(int, notify=selectionChanged)
    def hangarRevision(self) -> int:
        """自增心跳（每次选择变化 +1）。

        与 `LauncherWindow.qml:409` 的 `tickRevision` 同形：QML 的行内下拉在
        `currentIndex` 绑定里显式读一下它，绑定才重新求值。
        """
        return self._revision

    @Slot(int, result=int)
    def hangarIndexAt(self, row: int) -> int:
        """第 `row` 行的机库下标（越界返回 0 = 「不自动入库」）。"""
        if 0 <= row < len(self._hangar_indexes):
            return self._hangar_indexes[row]
        return 0

    @Slot(int, int)
    def setHangarIndexAt(self, row: int, index: int) -> None:
        """把第 `row` 行改成下拉的第 `index` 项。越界忽略（不抛）。"""
        if not 0 <= row < len(self._hangar_indexes):
            return
        if not 0 <= index < len(self._hangars):
            return
        if self._hangar_indexes[row] == index:
            return
        self._hangar_indexes[row] = index
        self._revision += 1
        self.selectionChanged.emit()

    @Slot(int)
    def setAllHangars(self, index: int) -> None:
        """「统一设为」：把**每一行**都改成第 `index` 项（含用户已单独改过的行）。"""
        if not 0 <= index < len(self._hangars):
            return
        if all(i == index for i in self._hangar_indexes):
            return
        self._hangar_indexes = [index] * len(self._hangar_indexes)
        self._revision += 1
        self.selectionChanged.emit()
        #: 必须再发一次 `rowsChanged`：已单独改过的那些行，其 `currentIndex` 绑定已被样式
        #: 的 JS 赋值摘掉，光改桥里的值它们不会动（实测）。整表重建才会重建绑定。
        self.rowsChanged.emit()

    def selected_hangar_ids(self) -> list[int]:
        """按 `plans` 顺序的产出机库 id（`-1` = 不自动入库）。"""
        return [self._id_at(i) for i in self._hangar_indexes]

    def selected_hangar_id(self) -> int:
        """**单行路径**（`complete_one_plan`）用的标量；批量入口请用 `selected_hangar_ids()`。"""
        if self._hangar_indexes:
            return self._id_at(self._hangar_indexes[0])
        return self._id_at(self._initial_index({}))

    # ── 内部 ──

    def _initial_index(self, plan: dict) -> int:
        """该行的初值：计划自己的 `deposit_hangar_id` → 全局默认 → 第一个真实机库 → 0。

        `0` 就是「不自动入库」（机库表里 `-1` 那项），因此**无机库时自然退化成 -1**。
        """
        for cand in (plan.get("deposit_hangar_id"), self._default_hangar_id):
            if cand and cand > 0:
                found = self._index_of(int(cand))
                if found is not None:
                    return found
        return 1 if len(self._hangars) > 1 else 0  # 第一个真实机库（没有就「不自动入库」）

    def _index_of(self, hangar_id: int) -> int | None:
        for i, h in enumerate(self._hangars):
            if h["id"] == hangar_id:
                return i
        return None

    def _id_at(self, index: int) -> int:
        if 0 <= index < len(self._hangars):
            return int(cast(int, self._hangars[index]["id"]))
        return -1


class CompletePlansQmlDialog(QmlDialog):
    """QML 版「下线确认」。

    批量入口取 `selected_hangar_ids()`（逐条）；单行入口取 `selected_hangar_id()`（标量）。
    """

    def __init__(
        self,
        plans: list[dict],
        hangars: list[dict],
        default_hangar_id: int | None,
        parent: Any = None,
    ) -> None:
        from services import plan_execution

        rows: list[dict] = []
        total_qty = 0
        for plan in plans:
            name = str(plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}")
            runs = int(plan.get("runs") or 1)
            parallels = int(plan.get("parallels") or 1)
            qty = runs * parallels * plan_execution.output_per_run(plan.get("product_type_id") or 0)
            total_qty += qty
            # 机库名不再进 rows：第 4 列是逐行下拉，名字由 `hangarNames` + `hangarIndex` 决定。
            # （机库 id 在表里查不到时，下拉自然停在「不自动入库」——旧代码在这里直接显示
            #   `str(None)`，界面上会出现「None」，随本次一并消掉。）
            rows.append(
                {
                    "name": name,
                    "runs": f"{parallels}X{runs}",
                    "qty": f"{qty:,}",
                }
            )

        bridge = CompletePlansBridge(
            plans,
            hangars,
            default_hangar_id,
            count_text=f"共 {len(plans)} 项计划",
            rows=rows,
            total_qty=total_qty,
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(640, 480))

    def selected_hangar_id(self) -> int:
        return self.bridge.selected_hangar_id()  # type: ignore[no-any-return]

    def selected_hangar_ids(self) -> list[int]:
        """按 `plans` 顺序的产出机库 id —— 批量下线入口用这个（不再一个值盖全批）。"""
        return self.bridge.selected_hangar_ids()  # type: ignore[no-any-return]

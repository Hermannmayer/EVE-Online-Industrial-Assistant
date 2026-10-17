"""发明结果回填**列表版**的桥（批量下线用）。

单条版见 `ui_qml/bridge/invention_outcome_bridge.py` —— 它仍在单行下线 / 小助手的
路径上；本模块只服务「一次下线 N 条发明计划」：`complete_plans` 原先在循环里逐条弹窗，
10 条发明要点 20 次「确认 + 关闭」（2026-10-11 用户报的体验问题）。

回填口径与单条版**逐字一致**：填的是「成功产线数」，实际产出流程数 = 成功数 × 每张流程。
每行的「每张流程」由调用方（`complete_plans_dialog._invention_expected`，走
`invention_output_runs(base_runs, decryptor)`）算好后传进来 —— 桥**不重算**，
两处各写一套公式必然漂移。同理，「总尝试次数」（= `runs × parallels`）也由调用方算好，
桥只拿它当成功数的上限与展示值。

`outcome()` → `{plan_id: (实际产出流程数, BPC 张数)}`；取消 → None。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["InventionOutcomeListBridge", "InventionOutcomeListQmlDialog"]

_QML_FILE = "dialogs/InventionOutcomeListDialog.qml"


class InventionOutcomeListBridge(DialogBridge):
    """发明结果回填列表的 QML 后端。

    行数据是**常量**（`rows`），成功数单独持有 —— 编辑一行不该让列表重建
    （同 `BlueprintPickerDialog` 的勾选态：重建会丢用户已填的其他行）。
    """

    #: 任一行的成功数变了（逐行编辑 / 全部失败）
    valueChanged = Signal()

    def __init__(self, rows: list[dict] | None = None) -> None:
        super().__init__()
        self._rows: list[dict] = []
        self._successes: list[int] = []
        self._outcome: dict[int, tuple[int, int]] | None = None
        for raw in rows or []:
            #: 调用方给的是**总**尝试次数（runs × 并行数，口径见
            # `complete_plans_dialog._invention_attempts`）；它同时是成功数输入框的上限
            attempts = max(int(raw.get("attempts") or 0), 1)
            runs_per = max(int(raw.get("runs_per_bpc") or 0), 0)
            #: 预填期望成功产线数（与单条版一致），并夹到总尝试次数内 —— 一条产线最多成功一次
            expected = max(0, min(int(raw.get("expected_bpc") or 0), attempts))
            self._rows.append(
                {
                    "index": len(self._rows),
                    "planId": int(raw.get("plan_id") or 0),
                    "name": str(raw.get("name") or ""),
                    "attempts": attempts,
                    "decryptor": str(raw.get("decryptor") or ""),
                    "runsPerBpc": runs_per,
                    "expectedBpc": expected,
                    "successes": expected,
                }
            )
            self._successes.append(expected)
        self.set_title(f"发明结果回填 — 本批 {len(self._rows)} 条")

    # ── 行数据 ────────────────────────────────────────────────

    #: 只读行数据 [{index, planId, name, attempts, decryptor, runsPerBpc, expectedBpc, successes}]
    rows = Property(list, lambda self: self._rows, constant=True)
    canAccept = Property(bool, lambda self: bool(self._rows), constant=True)

    @Slot(int, result=int)
    def successAt(self, index: int) -> int:
        """该行当前成功产线数（QML 靠它回读：批量操作后各行要同步）。"""
        return self._successes[index] if 0 <= index < len(self._successes) else 0

    @Slot(int, result=int)
    def actualRunsAt(self, index: int) -> int:
        """该行换算出的实际产出流程数 = 成功数 × 每张流程。"""
        if not 0 <= index < len(self._rows):
            return 0
        return self._successes[index] * int(self._rows[index]["runsPerBpc"])

    # ── 编辑 ──────────────────────────────────────────────────

    @Slot(int, int)
    def setSuccesses(self, index: int, value: int) -> None:
        if not 0 <= index < len(self._successes):
            return
        upper = max(int(self._rows[index]["attempts"]), 1)
        clamped = max(0, min(upper, int(value)))
        if clamped == self._successes[index]:
            return
        self._successes[index] = clamped
        self._rows[index]["successes"] = clamped
        self.valueChanged.emit()

    @Slot(int)
    def markFailed(self, index: int) -> None:
        """逐行「发明失败」：把该行成功数置 0（材料与输入流程已被消耗，这是游戏事实）。"""
        self.setSuccesses(index, 0)

    @Slot()
    def markAllFailed(self) -> None:
        """「全部失败」：一次把本批所有行置 0 —— 否则 10 行要按 10 次。"""
        changed = False
        for i, value in enumerate(self._successes):
            if value:
                self._successes[i] = 0
                self._rows[i]["successes"] = 0
                changed = True
        if changed:
            self.valueChanged.emit()

    # ── 汇总 / 提示 ───────────────────────────────────────────

    def _total_bpc(self) -> int:
        return sum(self._successes)

    def _total_runs(self) -> int:
        return sum(self._successes[i] * int(r["runsPerBpc"]) for i, r in enumerate(self._rows))

    #: 本批成功产线数合计（= 产出的 BPC 张数）
    totalBpc = Property(int, lambda self: self._total_bpc(), notify=valueChanged)
    #: 本批实际产出流程数合计
    totalRuns = Property(int, lambda self: self._total_runs(), notify=valueChanged)

    @Property(str, notify=valueChanged)
    def hintText(self) -> str:
        """与单条版同口径的提示（失败行的消耗不退）。"""
        if self._total_bpc() <= 0:
            return (
                "⚠ 全部发明失败：本次消耗的数据核心、解码器与输入蓝图流程不会退还，"
                "这些计划将记为「0 流程」且不产出蓝图。"
            )
        return (
            f"本批 {len(self._rows)} 条发明：成功 {self._total_bpc()} 张 × 各自每张流程 "
            f"= 共 {self._total_runs()} 流程；失败行的消耗不退。"
        )

    # ── 结果 ──────────────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        self._outcome = {
            int(row["planId"]): (self.actualRunsAt(i), self._successes[i]) for i, row in enumerate(self._rows)
        }
        self.accepted.emit()

    def outcome(self) -> dict[int, tuple[int, int]] | None:
        """{plan_id: (实际产出流程数, BPC 张数)}；取消 → None。"""
        return self._outcome


class InventionOutcomeListQmlDialog(QmlDialog):
    """QML 版「发明结果回填（列表）」。"""

    def __init__(self, rows: list[dict] | None = None, parent: Any = None) -> None:
        bridge = InventionOutcomeListBridge(rows)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(880, 420))

    def outcome(self) -> dict[int, tuple[int, int]] | None:
        return self.bridge.outcome()  # type: ignore[no-any-return]

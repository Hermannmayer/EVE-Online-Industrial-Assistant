"""子项并行配置对话框的桥（阶段 4）。

只设置每个子项的「并行产线数」上限，「每条流程」按**净缺口**自动生成
（`plan_rebuild.plan_net_runs`：毛需求 − 母项材料机库里的成品库存，再找并行数），
总产出实时显示并校验「产出 + 库存 ≥ 毛需求」。

**口径与 `plan_rebuild._finalize_runs` 同一真源**：旧版按毛需求
`ceil(demand/(per_run×parallels))` 算，用户一打开本对话框再点确定，就把自动排好的
`4×3=12` 写回成 `5×4=20`（多造 8 个）。
**在产行（`in_progress`/`running`）完全只读：`parallels` 与 `runs` 都不写**
（整批产出 = `parallels × runs × 单轮产出`，写并行数同样会成倍改产出；口径同
`_finalize_runs`「已投产产线不砍流程」）—— `accept()` 的行集合里不含它们。
保存仍走 `plan_repo.update_batch`（逐条 UPDATE parallels/runs）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.container import get_container
from services.plan_rebuild import plan_net_runs
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["ChildParallelBridge", "ChildParallelQmlDialog"]

_QML_FILE = "dialogs/ChildParallelDialog.qml"

#: 在产状态：这两个状态的行**完全只读**（`parallels` 与 `runs` 都不写）—— 口径同
#: `services.plan_rebuild._LOCKED_RUNS_STATUSES`（「已投产产线不砍流程」）。
#: 为什么连 `parallels` 也不写：整批产出 = `parallels × runs × 单轮产出`，在产行的 `runs`
#: 冻结时改并行数照样把产出成倍放大（实测 346 冻结 runs=4、拖到 10 条 → 40 件，净缺口 12）。
_LOCKED_STATUSES = ("in_progress", "running")


class ChildParallelBridge(DialogBridge):
    """子项并行配置的 QML 后端。"""

    rowsChanged = Signal()

    def __init__(self, plans: list[dict]) -> None:
        super().__init__()
        from services.industry_dialog_queries import get_child_parallel_data

        self._all_plans = plans
        self._plans = [p for p in plans if int(p.get("sub_level") or 0) > 0]
        self._demand: dict[int, int] = {}
        self._output_per_run: dict[int, int] = {}
        self._durations: dict[int, str] = {}
        self._available: dict[int, int] = {}
        (
            self._demand,
            self._output_per_run,
            self._durations,
            self._available,
        ) = get_child_parallel_data(get_container().db, plans, self._plans)
        #: 在产行（`runs` 冻结，只写 parallels）：plan id → bool
        self._locked = {int(p["id"]): self._is_locked(p) for p in self._plans if p.get("id")}
        #: 每行：{planId, name, duration, demand, available, netDemand, output, runs, check, checkToken, parallels, locked}
        self._rows: list[dict] = []
        self._can_accept = True
        self.set_title("子项并行配置")
        self._build_rows()

    @staticmethod
    def _is_locked(plan: dict) -> bool:
        """在产（`in_progress`/`running`）：本对话框对该行**只读**（`parallels`/`runs` 都不写）。"""
        return (plan.get("status") or "").lower() in _LOCKED_STATUSES

    tipText = Property(
        str,
        lambda self: (
            "只需设置每个子项的「并行产线数」（上限）；「每条流程」按净缺口自动生成："
            "毛需求先减去母项材料机库里的成品库存，再取轮数最少的并行方案，不会多造。"
            "在产子项只读：并行数与流程数都不能改。"
        ),
        constant=True,
    )
    headers = Property(
        list,
        lambda self: ["子项", "毛需求", "总产出", "并行产线数", "每条流程(自动)", "校验（库存/净缺口）"],
        constant=True,
    )
    rows = Property(list, lambda self: self._rows, notify=rowsChanged)
    canAccept = Property(bool, lambda self: self._can_accept, notify=rowsChanged)

    def _build_rows(self) -> None:
        from services.industry_dialog_queries import get_item_name

        self._rows = []
        for plan in self._plans:
            pid = plan["product_type_id"]
            name = get_item_name(get_container().db, pid)
            demand = self._demand.get(pid, 0)
            available = self._available.get(pid, 0)
            per_run = self._output_per_run.get(pid, 1)
            locked = bool(self._locked.get(plan["id"]))
            if locked:
                # 在产：只读 —— 并行数与流程数都显示库中现值，accept 也不写
                parallels = int(plan.get("parallels") or 1)
                runs = int(plan.get("runs") or 1)
            else:
                parallels, runs, _net_lines = plan_net_runs(demand, per_run, available, int(plan.get("parallels") or 1))
            self._rows.append(
                {
                    "planId": plan["id"],
                    "name": name,
                    "duration": self._durations.get(pid, ""),
                    "demand": demand,
                    "available": available,
                    "netDemand": max(0, demand - available),
                    "output": parallels * runs * per_run,
                    "runs": runs,
                    "parallels": parallels,
                    "locked": locked,
                    "check": "",
                    "checkToken": "",
                }
            )
        self._validate()

    # ── 校验（净口径：产出 + 库存 ≥ 毛需求）───────────────────

    def _per_run(self, row: dict) -> int:
        plan = next((p for p in self._plans if p["id"] == row["planId"]), None)
        pid = int((plan or {}).get("product_type_id") or 0)
        return int(self._output_per_run.get(pid, 1))

    def _validate(self) -> None:
        ok = True
        for row in self._rows:
            per_run = self._per_run(row)
            total = row["parallels"] * row["runs"] * per_run
            row["output"] = total
            demand = row["demand"]
            available = row.get("available", 0)
            ledger = f"库存 {available:,}｜净缺口 {max(0, demand - available):,}"
            if demand and total + available < demand:
                head = "在产，并行/流程数均只读" if row.get("locked") else "不足"
                row["check"] = f"{head}（还差 {demand - available - total:,}）｜{ledger}"
                row["checkToken"] = "ACCENT_RED"
                # 在产行的缺口**不是本对话框能修的**（整行只读），只报警不阻断保存
                ok = ok and bool(row.get("locked"))
            elif row.get("locked"):
                row["check"] = f"在产，并行/流程数均只读｜{ledger}"
                row["checkToken"] = "ACCENT_GREEN"
            else:
                row["check"] = f"✓ {ledger}"
                row["checkToken"] = "ACCENT_GREEN"
        self._can_accept = ok

    @Slot(int, int)
    def setParallels(self, index: int, value: int) -> None:
        """并行产线数变化 → 该行按净口径重新定稿（并行数是**上限**，系统不会超过它）。

        在产行**直接忽略**：整批产出 = `parallels × runs × 单轮产出`，`runs` 冻死时改并行数
        照样把产出成倍放大，所以这一行在本对话框里完全只读（口径同
        `plan_rebuild._LOCKED_RUNS_STATUSES`）。
        """
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        if row.get("locked"):
            return
        value = max(1, min(1000, int(value)))
        plan = next((p for p in self._plans if p["id"] == row["planId"]), None)
        pid = int((plan or {}).get("product_type_id") or 0)
        parallels, runs, _net_lines = plan_net_runs(
            row["demand"], self._per_run(row), int(self._available.get(pid, 0)), value
        )
        row["parallels"] = parallels
        row["runs"] = runs
        self._validate()
        self.rowsChanged.emit()

    @Slot()
    def accept(self) -> None:
        """保存：**在产行不进写库集合**（只读，`parallels`/`runs` 都不写），其余行两列一起写。

        全是在产行时没有任何可写的 —— 直接收工（不写空批次），仍发 `accepted` 让对话框关闭。
        内存 plan 只对可写行同步，避免界面与库不一致。
        """
        if not self._can_accept:
            return
        updates = []
        for row in self._rows:
            if row.get("locked"):
                continue
            updates.append((row["planId"], {"parallels": row["parallels"], "runs": row["runs"]}))
            plan = next((p for p in self._plans if p["id"] == row["planId"]), None)
            if plan is not None:
                plan["parallels"] = row["parallels"]
                plan["runs"] = row["runs"]
        if updates:
            get_container().plan_repo.update_batch(updates)
        self.accepted.emit()

    def row_count(self) -> int:
        return len(self._rows)


class ChildParallelQmlDialog(QmlDialog):
    """QML 版「子项并行配置」。`ChildParallelDialog(plans, parent)` 的调用方原样可用。"""

    def __init__(self, plans: list[dict], parent: Any = None) -> None:
        super().__init__(_QML_FILE, ChildParallelBridge(plans), parent=parent, size=(820, 520))

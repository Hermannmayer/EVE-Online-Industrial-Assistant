"""编辑生产计划对话框的桥（阶段 4 的样板）。

对照 Widgets 版 `ui_pyside6/views/industry/plan_edit_dialog.py`，
对外契约保持一致：`exec()` → `get_updated_data()` 返回同一个字段字典
（含批量模式下「未勾选同步则流程/并行为 None」那条规则）。

科研行的 `runs` 语义不同（发明=尝试次数 / 拷贝=每份流程 / 研究=目标等级），
标签与提示随活动类型走 —— 与 Widgets 版逐条对齐。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from services import inventory_manager
from services.plan_job_kinds import normalize
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["PlanEditBridge", "PlanEditQmlDialog"]

_QML_FILE = "dialogs/PlanEditDialog.qml"

#: 活动类型 → (流程数的标签, 提示)
_RUNS_LABELS: dict[str, tuple[str, str]] = {
    "copying": ("每份流程", "每份 BPC 的授权生产流程数（上限=蓝图拷贝上限）"),
    "invention": ("尝试次数", "要跑几次发明尝试；每次消耗 1 个输入 BPC 流程与一份数据核心"),
    "researching_material_efficiency": ("目标 ME 等级", "材料效率研究的目标等级"),
    "researching_time_efficiency": ("目标 TE 等级", "时间效率研究的目标等级"),
}


class PlanEditBridge(DialogBridge):
    """编辑 / 批量编辑生产计划的 QML 后端。"""

    fieldsChanged = Signal()

    def __init__(self, plan_data: dict | None = None, *, batch_mode: bool = False, row_count: int = 0) -> None:
        super().__init__()
        self._plan = plan_data or {}
        self._batch_mode = bool(batch_mode)
        self._row_count = int(row_count)

        activity = normalize(self._plan.get("activity"))
        self._runs_label, runs_tip = _RUNS_LABELS.get(activity, ("流程数", ""))
        self._runs_tip = runs_tip
        # 拷贝行的「份数」存在 parallels 上；科研行并行恒为 1
        self._parallel_label = "产出份数" if activity == "copying" else "并行数"
        self._parallel_tip = "拷贝行表示产出的 BPC 份数" if activity == "copying" else ""

        self._runs = int(self._plan.get("runs", 1) or 1)
        self._parallels = int(self._plan.get("parallels", 1) or 1)
        self._sync_runs = not self._batch_mode
        self._notes = str(self._plan.get("notes", "") or "")

        self._chars = self._load_chars()
        char = str(self._plan.get("char_name") or self._plan.get("character") or "")
        if char and char not in self._chars:
            self._chars.insert(0, char)
        self._char_index = self._chars.index(char) if char in self._chars else 0

        self._hangars = self._load_hangars()
        self._deposit_index = self._index_of_hangar(self._plan.get("deposit_hangar_id"))
        self._mat_index = self._index_of_hangar(self._plan.get("mat_hangar_id"))

        self.set_title(
            f"批量编辑生产计划 ({self._row_count} 行)"
            if self._batch_mode
            else f"编辑生产计划 - {self._plan.get('product_name', '未知产品')}"
        )

    # ── 初始数据 ──────────────────────────────────────────────

    @staticmethod
    def _load_chars() -> list[str]:
        from services.char_config_resolver import get_character_list

        chars = list(get_character_list() or [])
        return chars or ["main"]

    @staticmethod
    def _load_hangars() -> list[dict]:
        """机库下拉：首项是「未设置」(-1)，其余来自机库列表。"""
        out: list[dict] = [{"id": -1, "name": "未设置"}]
        try:
            for hangar in inventory_manager.get_hangars():
                out.append({"id": hangar.get("id"), "name": hangar.get("name", "")})
        except Exception:
            pass
        return out

    def _index_of_hangar(self, hangar_id: Any) -> int:
        if not hangar_id:
            return 0
        for i, hangar in enumerate(self._hangars):
            if hangar["id"] == hangar_id:
                return i
        return 0

    # ── 只读展示 ──────────────────────────────────────────────

    @Property(str, constant=True)
    def productLabel(self) -> str:
        if self._batch_mode:
            return f"已选中 {len(self._plan.get('_selected_rows', []))} 行"
        return str(self._plan.get("product_name", "—"))

    @Property(bool, constant=True)
    def batchMode(self) -> bool:
        return self._batch_mode

    runsLabel = Property(str, lambda self: self._runs_label, constant=True)
    runsTip = Property(str, lambda self: self._runs_tip, constant=True)
    parallelLabel = Property(str, lambda self: self._parallel_label, constant=True)
    parallelTip = Property(str, lambda self: self._parallel_tip, constant=True)

    chars = Property(list, lambda self: list(self._chars), constant=True)
    hangars = Property(list, lambda self: [h["name"] for h in self._hangars], constant=True)

    # ── 可编辑字段 ────────────────────────────────────────────

    runs = Property(int, lambda self: self._runs, notify=fieldsChanged)
    parallels = Property(int, lambda self: self._parallels, notify=fieldsChanged)
    syncRuns = Property(bool, lambda self: self._sync_runs, notify=fieldsChanged)
    charIndex = Property(int, lambda self: self._char_index, notify=fieldsChanged)
    depositIndex = Property(int, lambda self: self._deposit_index, notify=fieldsChanged)
    matIndex = Property(int, lambda self: self._mat_index, notify=fieldsChanged)
    notes = Property(str, lambda self: self._notes, notify=fieldsChanged)

    @Slot(int)
    def setRuns(self, value: int) -> None:
        self._runs = max(1, min(99999, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setParallels(self, value: int) -> None:
        self._parallels = max(1, min(100, int(value)))
        self.fieldsChanged.emit()

    @Slot(bool)
    def setSyncRuns(self, value: bool) -> None:
        self._sync_runs = bool(value)
        self.fieldsChanged.emit()

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        if 0 <= index < len(self._chars):
            self._char_index = index
            self.set_error("")
            self.fieldsChanged.emit()

    @Slot(int)
    def setDepositIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars):
            self._deposit_index = index
            self.fieldsChanged.emit()

    @Slot(int)
    def setMatIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars):
            self._mat_index = index
            self.fieldsChanged.emit()

    @Slot(str)
    def setNotes(self, text: str) -> None:
        self._notes = str(text)

    # ── 校验 / 取值 ───────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        if not self.currentChar().strip():
            self.set_error("请输入角色名")
            return
        self.accepted.emit()

    def currentChar(self) -> str:
        """给 Python 侧读当前角色名（`charIndex` 是 Property，mypy 读不出 str）。"""
        if 0 <= self._char_index < len(self._chars):
            return self._chars[self._char_index]
        return ""

    def data(self) -> dict:
        """与 Widgets 版 `get_updated_data()` 完全同形。"""
        deposit = self._hangars[self._deposit_index]["id"] if self._hangars else None
        material = self._hangars[self._mat_index]["id"] if self._hangars else None
        sync = self._sync_runs
        result: dict[str, Any] = {
            "runs": self._runs if sync else None,
            "parallels": self._parallels if sync else None,
            "char_name": self.currentChar().strip(),
            "notes": self._notes.strip(),
            "deposit_hangar_id": None if deposit in (None, -1) else deposit,
            "mat_hangar_id": None if material in (None, -1) else material,
        }
        if not self._batch_mode:
            result["product_name"] = self.productLabel
        return result


class PlanEditQmlDialog(QmlDialog):
    """QML 版「编辑生产计划」。对外 API 与 Widgets 版一致。"""

    def __init__(
        self,
        parent: Any = None,
        plan_data: dict | None = None,
        *,
        batch_mode: bool = False,
        row_count: int = 0,
    ) -> None:
        bridge = PlanEditBridge(plan_data, batch_mode=batch_mode, row_count=row_count)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(480, 430))

    def get_updated_data(self) -> dict:
        return self.bridge.data()  # type: ignore[no-any-return]

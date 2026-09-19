"""编辑生产计划对话框的桥（阶段 4 的样板）。

对照 Widgets 版 `ui_pyside6/views/industry/plan_edit_dialog.py`，
对外契约保持一致：`exec()` → `get_updated_data()` 返回同一个字段字典
（含批量模式下「未勾选同步则流程/并行为 None」那条规则）。

科研行的 `runs` 语义不同（发明=每线尝试次数 / 拷贝=每份流程 / 研究=目标等级），
标签与提示随活动类型走 —— 与 Widgets 版逐条对齐。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from domain.research import (
    ACTIVITY_INVENTION,
    ACTIVITY_RESEARCH_ME,
    ACTIVITY_RESEARCH_TE,
    decryptor_ids,
    decryptor_labels,
)
from services import inventory_manager
from services.plan_job_kinds import ACTIVITY_MANUFACTURING, normalize
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["PlanEditBridge", "PlanEditQmlDialog"]

_QML_FILE = "dialogs/PlanEditDialog.qml"

#: 效率研究的两种活动（并行数对它们没有意义）
_RESEARCH_ACTIVITIES = frozenset({ACTIVITY_RESEARCH_ME, ACTIVITY_RESEARCH_TE})

#: 活动类型 → (流程数的标签, 提示)
_RUNS_LABELS: dict[str, tuple[str, str]] = {
    "copying": ("每份流程", "每份 BPC 的授权生产流程数（上限=蓝图拷贝上限）"),
    "invention": (
        "每线尝试次数",
        "每条并行产线要跑几次发明尝试；总尝试 = 每线尝试次数 × 并行数\n每次尝试消耗 1 个输入 BPC 流程与一份数据核心",
    ),
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
        self._activity = activity
        self._runs_label, runs_tip = _RUNS_LABELS.get(activity, ("流程数", ""))
        self._runs_tip = runs_tip
        # 拷贝行的「份数」存在 parallels 上；科研行并行恒为 1
        self._parallel_label = "产出份数" if activity == "copying" else "并行数"
        self._parallel_tip = "拷贝行表示产出的 BPC 份数" if activity == "copying" else ""

        self._runs = int(self._plan.get("runs", 1) or 1)
        self._parallels = int(self._plan.get("parallels", 1) or 1)
        self._sync_runs = not self._batch_mode
        self._notes = str(self._plan.get("notes", "") or "")
        self._me = max(0, min(10, int(self._plan.get("me_level", 0) or 0)))
        self._te = max(0, min(20, int(self._plan.get("te_level", 0) or 0)))

        # 解码器（仅发明行）：把计划里存的 type_id 映射到下拉索引
        raw_dec = self._plan.get("decryptor_type_id")
        self._orig_decryptor_id = int(raw_dec) if raw_dec else None
        self._decryptor_ids = decryptor_ids()
        self._decryptor_index = (
            self._decryptor_ids.index(self._orig_decryptor_id) if self._orig_decryptor_id in self._decryptor_ids else 0
        )

        self._chars = self._load_chars()
        char = str(self._plan.get("char_name") or self._plan.get("character") or "")
        if char and char not in self._chars:
            self._chars.insert(0, char)
        self._char_index = self._chars.index(char) if char in self._chars else 0

        self._hangars = self._load_hangars()
        self._deposit_index = self._index_of_hangar(self._plan.get("deposit_hangar_id"))
        self._mat_index = self._index_of_hangar(self._plan.get("mat_hangar_id"))
        #: 用户是否手工选过产出机库 —— 没选过才跟随材料机库
        self._deposit_user_edited = False

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
    #: ME/TE 只对制造行开放（科研行恒 0；批量模式沿用「不含 ME/TE」的既有约定）
    showMeTe = Property(
        bool,
        lambda self: self._activity == ACTIVITY_MANUFACTURING and not self._batch_mode,
        constant=True,
    )
    #: 研究行的并行数没有意义（runs 本身就是目标等级），藏起来
    showParallel = Property(bool, lambda self: self._activity not in _RESEARCH_ACTIVITIES, constant=True)
    #: 解码器只对发明行有意义（它改产出流程数与成功率）
    showDecryptor = Property(bool, lambda self: self._activity == ACTIVITY_INVENTION, constant=True)
    decryptorLabels = Property(list, lambda self: decryptor_labels(), constant=True)

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
    me = Property(int, lambda self: self._me, notify=fieldsChanged)
    te = Property(int, lambda self: self._te, notify=fieldsChanged)
    decryptorIndex = Property(int, lambda self: self._decryptor_index, notify=fieldsChanged)
    #: 发明行的只读补充：总尝试 = 每线尝试次数 × 并行作业数
    totalAttempts = Property(
        str,
        lambda self: f"总尝试 {self._runs * self._parallels} 次" if self._activity == ACTIVITY_INVENTION else "",
        notify=fieldsChanged,
    )

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
        if not 0 <= index < len(self._hangars):
            return
        self._deposit_index = index
        self._deposit_user_edited = True
        self.fieldsChanged.emit()

    @Slot(int)
    def setMatIndex(self, index: int) -> None:
        if not 0 <= index < len(self._hangars):
            return
        self._mat_index = index
        # 产出机库没被单独改过 → 跟着材料机库走（与科研三框同一规则）
        if not self._deposit_user_edited:
            self._deposit_index = index
        self.fieldsChanged.emit()

    @Slot(int)
    def setMe(self, value: int) -> None:
        self._me = max(0, min(10, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setTe(self, value: int) -> None:
        self._te = max(0, min(20, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setDecryptorIndex(self, index: int) -> None:
        if 0 <= index < len(self._decryptor_ids):
            self._decryptor_index = index
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
        if self.showMeTe:
            result["me_level"] = self._me
            result["te_level"] = self._te
        if self.showDecryptor:
            dec = int(self._decryptor_ids[self._decryptor_index] or 0) or None
            result["decryptor_type_id"] = dec
            if dec != self._orig_decryptor_id:
                # 换了解码器 → 原来手填的成功率是按旧解码器算的，清掉让评分链
                # 按「当前角色技能 × 新解码器」重新算
                result["success_rate"] = None
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
        super().__init__(_QML_FILE, bridge, parent=parent, size=(480, 340))

    def get_updated_data(self) -> dict:
        return self.bridge.data()  # type: ignore[no-any-return]

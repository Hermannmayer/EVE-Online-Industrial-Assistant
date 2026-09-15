"""科研计划对话框的桥（阶段 4b 收尾）：拷贝 / 发明 / 效率研究。

对照 Widgets 版 `ui_pyside6/dialogs/research_plan_dialogs.py`。三个类共用同一套
「角色 / 材料机库 / 输出机库 / 设施」骨架（原 `_ResearchDialogBase`）——QML 里
没有可继承的私有窗口基类，所以把公共字段与取值搬进 `_ResearchBridgeBase`，
QML 侧的同一块再抽成 `ResearchCommonFields.qml`，避免三份重复。

对外契约逐字保留：`exec()` → [`result_data()`]（外加发明那个 `outcome_combo()`）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from domain.research import (
    ACTIVITY_COPYING,
    ACTIVITY_INVENTION,
    ACTIVITY_RESEARCH_ME,
    ACTIVITY_RESEARCH_TE,
    DECRYPTORS,
    Decryptor,
)
from services import inventory_manager
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "CopyPlanBridge",
    "CopyPlanDialogQmlDialog",
    "InventionPlanBridge",
    "InventionPlanDialogQmlDialog",
    "ResearchPlanBridge",
    "ResearchPlanDialogQmlDialog",
]

_COPY_QML = "dialogs/CopyPlanDialog.qml"
_INVENTION_QML = "dialogs/InventionPlanDialog.qml"
_RESEARCH_QML = "dialogs/ResearchPlanDialog.qml"

_TIP = "提示：科研作业不消耗蓝图原本的流程；发明成功率高时一次尝试即可产出整张 BPC。"
_NOT_SET = "未设置"


def _hangars() -> list[dict]:
    """机库列表；读不到就空表（对齐原 `_hangars()` 的兜底）。"""
    try:
        return inventory_manager.get_hangars()
    except Exception:
        return []


def _default_hangar_id(key: str) -> int | None:
    """默认机库设置；未设/读盘失败 → None（对齐原 `_default_hangar_id`）。"""
    try:
        from services import user_settings

        return user_settings.get_default_hangar_id(key)
    except Exception:
        return None


class _ResearchBridgeBase(DialogBridge):
    """三张科研对话框的公共字段：角色 / 材料机库 / 输出机库 / 设施。"""

    #: 公共字段任一变化（QML 靠它把下拉的当前值刷回来）
    fieldsChanged = Signal()

    def __init__(self, blueprint_name: str, *, title: str) -> None:
        super().__init__()
        self.set_title(f"{title} — {blueprint_name}")
        self._blueprint_name = str(blueprint_name)
        self._result: dict[str, Any] | None = None

        self._chars = self._load_chars()
        self._char_index = 0

        # 索引 0 固定是「未设置」(-1)，对应原版 `addItem("未设置", -1)`。
        self._hangars: list[dict] = [{"id": -1, "name": _NOT_SET}]
        for hangar in _hangars():
            self._hangars.append({"id": hangar.get("id"), "name": hangar.get("name", "")})

        self._mat_index = self._index_of(_default_hangar_id("default_mat_hangar_id"))
        # 输出机库的默认值：先研究机库，退而求其次用存放机库（与原版 `or` 语义一致）
        out_default = _default_hangar_id("default_research_hangar_id") or _default_hangar_id(
            "default_deposit_hangar_id"
        )
        self._out_index = self._index_of(out_default)

        # 设施：原版是空的可编辑下拉（currentIndex(-1)），所以初值是空串
        self._facility = ""

    # ── 初始化数据 ───────────────────────────────────────────

    @staticmethod
    def _load_chars() -> list[str]:
        """角色下拉；没配角色时退回 "main"（原版 `addItem("main")`）。"""
        from services.char_config_resolver import get_character_list

        chars = list(get_character_list() or [])
        return chars or ["main"]

    def _index_of(self, hangar_id: Any) -> int:
        """机库 id → 下拉索引；未设/找不到 → 0（即「未设置」）。"""
        if not hangar_id:
            return 0
        for i, hangar in enumerate(self._hangars):
            if hangar["id"] == hangar_id:
                return i
        return 0

    # ── 只读展示 ─────────────────────────────────────────────

    blueprintName = Property(str, lambda self: self._blueprint_name, constant=True)
    charOptions = Property(list, lambda self: list(self._chars), constant=True)
    hangarOptions = Property(list, lambda self: [h["name"] for h in self._hangars], constant=True)
    #: 设施下拉的候选（原版只填了机库名，不含「未设置」）
    facilityOptions = Property(list, lambda self: [h["name"] for h in self._hangars[1:]], constant=True)
    tip = Property(str, lambda self: _TIP, constant=True)

    # ── 可编辑字段 ───────────────────────────────────────────

    charIndex = Property(int, lambda self: self._char_index, notify=fieldsChanged)
    matIndex = Property(int, lambda self: self._mat_index, notify=fieldsChanged)
    outIndex = Property(int, lambda self: self._out_index, notify=fieldsChanged)
    facility = Property(str, lambda self: self._facility, notify=fieldsChanged)

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        if 0 <= index < len(self._chars):
            self._char_index = index
            self.fieldsChanged.emit()

    @Slot(int)
    def setMatIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars):
            self._mat_index = index
            self.fieldsChanged.emit()

    @Slot(int)
    def setOutIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars):
            self._out_index = index
            self.fieldsChanged.emit()

    @Slot(str)
    def setFacility(self, text: str) -> None:
        self._facility = str(text)

    # ── 取值 ─────────────────────────────────────────────────

    def currentChar(self) -> str:
        """当前角色名（`charIndex` 是 Property，mypy 读不出 str，另给直取入口）。"""
        if 0 <= self._char_index < len(self._chars):
            return self._chars[self._char_index]
        return ""

    def currentFacility(self) -> str:
        return self._facility.strip()

    def _hangar_id(self, index: int) -> int | None:
        """下拉索引 → 机库 id；「未设置」(-1)/越界 → None（对齐原 `> 0` 判定）。"""
        if not 0 <= index < len(self._hangars):
            return None
        raw = self._hangars[index]["id"]
        if raw is None:
            return None
        value = int(raw)
        return value if value > 0 else None

    def _common_data(self, activity: str) -> dict[str, Any]:
        mat_id = self._hangar_id(self._mat_index)
        out_id = self._hangar_id(self._out_index)
        return {
            "activity": activity,
            "char_name": self.currentChar().strip(),
            "mat_hangar_id": mat_id,
            "deposit_hangar_id": out_id,
            "solar_system_id": inventory_manager.get_hangar_system_id(mat_id) if mat_id else None,
            "facility": self.currentFacility(),
        }

    def result_data(self) -> dict[str, Any] | None:
        """确定之后才有值；取消/未点确定 → None（与原版 `_result_data` 一致）。"""
        return self._result


# ══════════════════════════════════════════════════════════════
#  拷贝计划
# ══════════════════════════════════════════════════════════════


class CopyPlanBridge(_ResearchBridgeBase):
    """拷贝计划：份数 + 每份授权流程（上限 = 蓝图 copying 活动上限）。"""

    #: 拷贝专属字段变化。**不复用父类的 `fieldsChanged`** —— 子类类体里引用不到父类
    #: 的类属性名（mypy/py 都会报 `NameError: name 'fieldsChanged' is not defined`），
    #: 这也是 hangar_dialogs 里同款坑；各给各的信号最稳。
    copyChanged = Signal()

    def __init__(self, blueprint_name: str, *, max_production_limit: int) -> None:
        super().__init__(blueprint_name, title="加入拷贝规划")
        self._limit = max(1, int(max_production_limit or 1))
        self._copies = 1
        self._runs_per_copy = self._limit

    runsLimit = Property(int, lambda self: self._limit, constant=True)
    copies = Property(int, lambda self: self._copies, notify=copyChanged)
    runsPerCopy = Property(int, lambda self: self._runs_per_copy, notify=copyChanged)

    @Slot(int)
    def setCopies(self, value: int) -> None:
        self._copies = max(1, min(1000, int(value)))
        self.copyChanged.emit()

    @Slot(int)
    def setRunsPerCopy(self, value: int) -> None:
        self._runs_per_copy = max(1, min(self._limit, int(value)))
        self.copyChanged.emit()

    @Slot()
    def accept(self) -> None:
        data = self._common_data(ACTIVITY_COPYING)
        data.update({"copies": self._copies, "runs_per_copy": self._runs_per_copy})
        self._result = data
        self.accepted.emit()


class CopyPlanDialogQmlDialog(QmlDialog):
    """QML 版「加入拷贝规划」。`CopyPlanDialog(...)` 的调用方原样可用。"""

    def __init__(self, blueprint_name: str, *, max_production_limit: int, parent: Any = None) -> None:
        bridge = CopyPlanBridge(blueprint_name, max_production_limit=max_production_limit)
        super().__init__(_COPY_QML, bridge, parent=parent, size=(500, 400))
        self._copy_bridge = bridge

    def result_data(self) -> dict[str, Any] | None:
        return self._copy_bridge.result_data()


# ══════════════════════════════════════════════════════════════
#  发明计划
# ══════════════════════════════════════════════════════════════


class _OutcomeCombo:
    """`outcome_combo()` 的返回物 —— 冒充原 QComboBox 的三招。

    原版返回一个真 `QComboBox`，调用点只用它的 `count()` / `itemData(i)` /
    `setCurrentIndex(i)`（把右键选中的那张产物预先选中）。QML 里没有 QComboBox，
    这里给出同样三招的小适配器，调用点除了换类名之外一行都不用改。
    """

    def __init__(self, bridge: InventionPlanBridge) -> None:
        self._bridge = bridge

    def count(self) -> int:
        return self._bridge.outcome_count()

    def itemData(self, index: int) -> dict[str, Any] | None:
        return self._bridge.outcome_at(index)

    def setCurrentIndex(self, index: int) -> None:
        self._bridge.setOutcomeIndex(index)


class InventionPlanBridge(_ResearchBridgeBase):
    """发明计划：产物选择 + 解码器 + 预期成功率 + 尝试次数。"""

    #: 发明专属字段变化（与父类 `fieldsChanged` 分开，语义不同也不易混淆）
    inventionChanged = Signal()

    def __init__(
        self,
        t1_blueprint_name: str,
        *,
        outcomes: list[dict[str, Any]],
        base_runs_by_outcome: dict[int, int],
        default_probability: dict[int, float],
    ) -> None:
        super().__init__(t1_blueprint_name, title="加入发明规划")
        self._t1_name = str(t1_blueprint_name)
        self._outcomes = list(outcomes)
        self._base_runs = dict(base_runs_by_outcome)
        # 原版把它存下却没读过（真实基础成功率走产物自带的 base_probability），
        # 这里保留入参以免调用点改签名，行为同样不使用。
        self._default_prob = dict(default_probability)

        self._outcome_index = 0
        # 索引 0 = 「不使用」，其余按 DECRYPTORS 的顺序映射到各自 type_id
        self._decryptor_ids: list[int | None] = [None, *DECRYPTORS.keys()]
        self._decryptor_index = 0
        self._rate = 0.0
        self._hint = ""
        self._attempts = 1
        self._refresh_probability()

    # ── 选项（标签在 Python 侧拼好，格式化逻辑可单测）──────

    outcomeLabels = Property(
        list,
        lambda self: [f"{oc['name']}（基础成功率 {oc['base_probability'] * 100:.0f}%）" for oc in self._outcomes],
        constant=True,
    )
    decryptorLabels = Property(
        list,
        lambda self: (
            ["不使用"] + [f"{d.name}（成功率 ×{d.prob_mult:g}，流程 {d.runs_mod:+d}）" for d in DECRYPTORS.values()]
        ),
        constant=True,
    )
    outcomeSummary = Property(
        str,
        lambda self: f"由「{self._t1_name}」发明，共 {len(self._outcomes)} 种可能",
        constant=True,
    )

    # ── 可编辑字段 ───────────────────────────────────────────

    outcomeIndex = Property(int, lambda self: self._outcome_index, notify=inventionChanged)
    decryptorIndex = Property(int, lambda self: self._decryptor_index, notify=inventionChanged)
    rate = Property(float, lambda self: self._rate, notify=inventionChanged)
    rateHint = Property(str, lambda self: self._hint, notify=inventionChanged)
    attempts = Property(int, lambda self: self._attempts, notify=inventionChanged)

    @Slot(int)
    def setOutcomeIndex(self, index: int) -> None:
        if not 0 <= index < len(self._outcomes):
            return
        self._outcome_index = index
        self._refresh_probability()

    @Slot(int)
    def setDecryptorIndex(self, index: int) -> None:
        if not 0 <= index < len(self._decryptor_ids):
            return
        self._decryptor_index = index
        self._refresh_probability()

    @Slot(float)
    def setRate(self, value: float) -> None:
        """用户在微调框里手改成功率 —— 只存值，不触发重算（原版 blockSignals 的等价物）。"""
        self._rate = float(value)
        self.inventionChanged.emit()

    @Slot(int)
    def setAttempts(self, value: int) -> None:
        self._attempts = max(1, min(10000, int(value)))
        self.inventionChanged.emit()

    # ── 计算 ─────────────────────────────────────────────────

    def _current_outcome(self) -> dict[str, Any]:
        if 0 <= self._outcome_index < len(self._outcomes):
            return self._outcomes[self._outcome_index] or {}
        return {}

    def _current_decryptor(self) -> Decryptor | None:
        if not 0 <= self._decryptor_index < len(self._decryptor_ids):
            return None
        tid = self._decryptor_ids[self._decryptor_index]
        return DECRYPTORS.get(int(tid)) if tid else None

    def _refresh_probability(self) -> None:
        """换产物/换解码器时重算预期成功率与提示（逐条对齐原 `_refresh_probability`）。"""
        oc = self._current_outcome()
        decryptor = self._current_decryptor()
        base = float(oc.get("base_probability") or 0.0)
        mult = decryptor.prob_mult if decryptor else 1.0
        computed = min(1.0, base * mult)
        # 原版是 QDoubleSpinBox(decimals=1)：setValue 会按 1 位小数取整，
        # 而取值时读的也是取整后的值 —— 这里同步取整，success_rate 才逐位一致。
        self._rate = round(max(0.01, computed * 100), 1)
        runs = self._base_runs.get(int(oc.get("blueprint_type_id") or 0), 10)
        out_runs = max(1, runs + (decryptor.runs_mod if decryptor else 0))
        hint = f"按技能算的基础成功率 {base * 100:.0f}%"
        if decryptor:
            hint += f" × 解码器 {mult:g}"
        hint += f" → {computed * 100:.1f}%；成功一次产出 {out_runs} 流程的 BPC"
        self._hint = hint
        self.inventionChanged.emit()

    # ── 与调用点对齐的访问器 ─────────────────────────────────

    def outcome_count(self) -> int:
        return len(self._outcomes)

    def outcome_at(self, index: int) -> dict[str, Any] | None:
        if 0 <= index < len(self._outcomes):
            return self._outcomes[index]
        return None

    def outcome_combo(self) -> _OutcomeCombo:
        return _OutcomeCombo(self)

    @Slot()
    def accept(self) -> None:
        oc = self._current_outcome()
        decryptor = self._current_decryptor()
        data = self._common_data(ACTIVITY_INVENTION)
        data.update(
            {
                "product_blueprint_type_id": int(oc.get("blueprint_type_id") or 0),
                "product_name": oc.get("name") or "",
                "decryptor_type_id": int(decryptor.type_id) if decryptor else None,
                "success_rate": round(self._rate / 100.0, 4),
                "attempts": self._attempts,
            }
        )
        self._result = data
        self.accepted.emit()


class InventionPlanDialogQmlDialog(QmlDialog):
    """QML 版「加入发明规划」。`InventionPlanDialog(...)` 的调用方原样可用。"""

    def __init__(
        self,
        t1_blueprint_name: str,
        *,
        outcomes: list[dict[str, Any]],
        base_runs_by_outcome: dict[int, int],
        default_probability: dict[int, float],
        parent: Any = None,
    ) -> None:
        bridge = InventionPlanBridge(
            t1_blueprint_name,
            outcomes=outcomes,
            base_runs_by_outcome=base_runs_by_outcome,
            default_probability=default_probability,
        )
        super().__init__(_INVENTION_QML, bridge, parent=parent, size=(560, 480))
        self._inv_bridge = bridge

    def result_data(self) -> dict[str, Any] | None:
        return self._inv_bridge.result_data()

    def outcome_combo(self) -> _OutcomeCombo:
        """产物下拉 —— 调用方按右键选中的那张蓝图预选时用（同原版的三招适配器）。"""
        return self._inv_bridge.outcome_combo()


# ══════════════════════════════════════════════════════════════
#  效率研究计划
# ══════════════════════════════════════════════════════════════


class ResearchPlanBridge(_ResearchBridgeBase):
    """效率研究计划：ME / TE 二选一 + 目标等级。"""

    #: (活动名, 下拉标签) —— 与 Widgets 版逐字一致
    _KINDS: list[tuple[str, str]] = [
        (ACTIVITY_RESEARCH_ME, "材料效率（ME，降低材料需求）"),
        (ACTIVITY_RESEARCH_TE, "时间效率（TE，缩短制造时间）"),
    ]

    #: 研究专属字段变化（理由同 `CopyPlanBridge.copyChanged`）
    researchChanged = Signal()

    def __init__(self, blueprint_name: str) -> None:
        super().__init__(blueprint_name, title="加入效率研究规划")
        self._kind_index = 0
        self._level = 1

    kindOptions = Property(list, lambda self: [label for _value, label in self._KINDS], constant=True)
    kindIndex = Property(int, lambda self: self._kind_index, notify=researchChanged)
    level = Property(int, lambda self: self._level, notify=researchChanged)

    @Slot(int)
    def setKindIndex(self, index: int) -> None:
        if 0 <= index < len(self._KINDS):
            self._kind_index = index
            self.researchChanged.emit()

    @Slot(int)
    def setLevel(self, value: int) -> None:
        self._level = max(1, min(10, int(value)))
        self.researchChanged.emit()

    @Slot()
    def accept(self) -> None:
        data = self._common_data(self._KINDS[self._kind_index][0])
        data.update({"target_level": self._level})
        self._result = data
        self.accepted.emit()


class ResearchPlanDialogQmlDialog(QmlDialog):
    """QML 版「加入效率研究规划」。`ResearchPlanDialog(name, parent=...)` 的调用方原样可用。"""

    def __init__(self, blueprint_name: str, *, parent: Any = None) -> None:
        bridge = ResearchPlanBridge(blueprint_name)
        super().__init__(_RESEARCH_QML, bridge, parent=parent, size=(500, 400))
        self._research_bridge = bridge

    def result_data(self) -> dict[str, Any] | None:
        return self._research_bridge.result_data()

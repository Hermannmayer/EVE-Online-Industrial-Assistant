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
    Decryptor,
    clamp_research_target,
    decryptor_ids,
    decryptor_labels,
    get_decryptor,
    invention_output_me_te,
    invention_output_runs,
    invention_probability,
    research_level_cap,
)
from services import inventory_manager
from services.plan_job_kinds import ACTIVITY_MANUFACTURING, normalize
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.theme.registry import SPACING_MD, SPACING_SM

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

# ── 「编辑生产计划」对话框的尺寸常量（px）────────────────────────────
#
# 宿主 `QmlDialog` 用 `setMinimumSize` 定死下限（见 `dialog_host.py`），所以尺寸写死一大块
# 会让隐藏行的地方留一大片空白：拷贝行没有 ME/TE、没有解码器、没有预期面板，实测空出 170px。
# 于是改成按**可见行数**算。
#
# `_ROW_H` 是 Fluent 样式下 FSpinBox/FComboBox/FTextField 的实测高，**不随 fontScale 变**
# （控件高由样式决定，只有文字与标签宽度跟缩放走）；`_PANEL_H` 是 PlanEditDialog.qml 里
# `expectPanel` 的实测高。改对话框的行数或面板高，这三个常量要一起对 —— 核对方式是出图
# 看有没有裁切（`tests/test_qml_dialogs.py` 那套 `grabFramebuffer()`）。
_DLG_WIDTH = 480
_ROW_H = 30
_BUTTON_H = 32
_PANEL_H = 62


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

        # 研究行的 runs 就是目标等级 → 按游戏上限夹紧（旧数据里可能存过 ME 50 这种）
        self._runs = clamp_research_target(activity, int(self._plan.get("runs", 1) or 1))
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

        #: 评分链算出的发明口径（base_runs / base_probability / 三个技能等级），预期面板重算用
        self._bd = dict(self._plan.get("breakdown") or {})

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

    def _runs_max(self) -> int:
        """流程数 / 目标等级输入框的上限：研究活动有游戏硬上限（ME 10 / TE 20），其余 99999。"""
        return research_level_cap(self._activity) or 99999

    runsMax = Property(int, lambda self: self._runs_max(), constant=True)

    # ── 发明预期结果（只读展示，随 runs / parallels / 解码器实时重算）──────
    #
    # 全部走 domain.research 的纯函数；**不调用** services.plan_metrics.invention_plan_cost
    # （那个要价格与 DB）。所需口径由评分链写进 breakdown，见 scoring_service 的 extra。

    def _current_decryptor(self) -> Decryptor | None:
        if 0 <= self._decryptor_index < len(self._decryptor_ids):
            return get_decryptor(self._decryptor_ids[self._decryptor_index])
        return None

    def _expect_runs_per_bpc(self) -> int:
        """一次成功产出的 T2 BPC 流程数（随解码器流程修正变）。"""
        return invention_output_runs(int(self._bd.get("base_runs") or 1), self._current_decryptor())

    def _expect_rate(self) -> float:
        """预期成功率 0~1。

        手填过成功率时**不乘解码器倍率** —— 与 plan_metrics 的 `success_rate_override`
        同口径：覆盖优先，解码器只改产出流程与 ME/TE。
        """
        override = self._plan.get("success_rate")
        if override is not None:
            try:
                return min(1.0, max(0.0, float(override)))
            except (TypeError, ValueError):
                return 0.0
        dec = self._current_decryptor()
        return invention_probability(
            float(self._bd.get("base_probability") or 0.0),
            int(self._bd.get("science_skill_1") or 0),
            int(self._bd.get("science_skill_2") or 0),
            int(self._bd.get("encryption_skill") or 0),
            prob_mult=dec.prob_mult if dec else 1.0,
        )

    def _expect_bpc_count(self) -> int:
        """预期成功次数 = 总尝试 × 成功率（每次成功产 1 张 BPC）—— 期望值口径。"""
        return round(self._runs * self._parallels * self._expect_rate())

    def expect_visible(self) -> bool:
        """只有发明行、且拿得到评分口径（base_runs）时才显示预期面板。"""
        return self._activity == ACTIVITY_INVENTION and bool(self._bd.get("base_runs"))

    def dialog_row_count(self) -> int:
        """对话框实际会画出几行：ME/TE 行只有制造有、解码器行只有发明有。"""
        return 3 + int(self._activity == ACTIVITY_MANUFACTURING) + int(self._activity == ACTIVITY_INVENTION)

    # 计算全在普通方法里，`Property` 只做转发 —— PySide6 的 `Property` 在 mypy 眼里是
    # 描述符对象而不是返回值，属性体里写 `self.expectXxx` 会被判成「int * Property」。
    expectVisible = Property(bool, lambda self: self.expect_visible(), notify=fieldsChanged)
    expectRate = Property(float, lambda self: self._expect_rate(), notify=fieldsChanged)
    expectBpcCount = Property(int, lambda self: self._expect_bpc_count(), notify=fieldsChanged)
    expectRateText = Property(str, lambda self: f"{self._expect_rate() * 100:.1f}%", notify=fieldsChanged)
    expectRunsPerBpcText = Property(str, lambda self: f"{self._expect_runs_per_bpc()} 流程", notify=fieldsChanged)
    #: 产出 T2 BPC 的等级（基准 ME2 / TE4 + 解码器修正）
    expectMeTeText = Property(
        str,
        lambda self: "ME{} / TE{}".format(*invention_output_me_te(self._current_decryptor())),
        notify=fieldsChanged,
    )
    expectBpcText = Property(str, lambda self: f"约 {self._expect_bpc_count()} 张", notify=fieldsChanged)
    #: 合计流程（放分组标题行右侧，不额外占高度）
    expectTotalRunsText = Property(
        str,
        lambda self: f"合计约 {self._expect_bpc_count() * self._expect_runs_per_bpc()} 流程",
        notify=fieldsChanged,
    )

    @Slot(int)
    def setRuns(self, value: int) -> None:
        self._runs = max(1, min(self._runs_max(), int(value)))
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
        super().__init__(_QML_FILE, bridge, parent=parent, size=(_DLG_WIDTH, self._height_for(bridge)))

    @staticmethod
    def _height_for(bridge: PlanEditBridge) -> int:
        """按可见行数算高度 —— 隐藏的行不占位，别让它们变成空白。

        恒定 3 行：流程×并行 / 人物+备注 / 材料+产出机库；ME/TE 行只有制造有、
        解码器行与预期面板只有发明有。校验提示平时 `visible: false`（不参与布局），
        所以不预留；中间那个 `Layout.fillHeight` 弹簧的 implicitHeight 是 0。
        """
        rows = bridge.dialog_row_count()
        panel = bridge.expect_visible()
        children = rows + 1 + int(panel)  # 「+1」= 按钮行
        return 2 * SPACING_MD + rows * _ROW_H + _BUTTON_H + (children - 1) * SPACING_SM + (_PANEL_H if panel else 0)

    def get_updated_data(self) -> dict:
        return self.bridge.data()  # type: ignore[no-any-return]

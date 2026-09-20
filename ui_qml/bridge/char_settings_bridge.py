"""人物设置对话框的桥（阶段 4b）：多角色 / 技能 / 增效体 / 市场费率。

对照 Widgets 版 `ui_pyside6/views/char_settings_view.CharSettingsDialog` 与
`ui_pyside6/views/char_settings_pages.py`（`SkillsPage` / `ImplantsPage` / `MarketPage` /
`SkillSlider`）。

**三个 Tab 页做成了三个从属桥**（`SkillsBridge` / `ImplantsBridge` / `MarketBridge`），
由 `CharSettingsBridge` 以 QML 属性暴露给三个组件（`FSkillsTab` / `FImplantsTab` /
`FMarketTab`）。这样既保住了「一页一个内嵌控件」的结构，也不需要一个几百行的上帝桥。

`core/char_settings_common.py` 原样复用（纯逻辑，无 QtWidgets）：
技能分类表、交易中心表与四条费率公式都从那里来，**不在桥里重算**。

两处刻意的模型差异（都是为了避免「编辑到一半控件被重建」）：

- 技能行只在**换分类 / 换角色**时重建：拖动滑杆只更新等级并单独发 `skillsChanged`。
  否则每拖一格都会重建整张列表，正在拖的那个滑杆会被删掉。
- 市场费率拆成 `hubs`（身份 + 声望初值）与 `results`（算出来的文案）两个属性：
  改声望只让 `results` 重算，$QDoubleSpinBox 不会被重建、输入不丢焦点。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.char_settings_common import (
    ALL_SKILLS,
    SKILL_CATEGORIES,
    TRADE_HUBS,
    calc_broker_fee,
    calc_max_orders,
    calc_relist_discount,
    calc_sales_tax,
    format_pct,
    merge_esi_skill_levels,
    union_skill_levels,
)
from services.char_config_resolver import load_all_data, save_all_data
from services.implant_loader import load_implants
from ui_qml import icons
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.workers.esi_skill_worker import EsiSkillImportWorker
from ui_qml.workers.lifecycle import detach_worker

__all__ = [
    "CharSettingsBridge",
    "CharSettingsQmlDialog",
    "ImplantsBridge",
    "MarketBridge",
    "SkillsBridge",
]

_QML_FILE = "dialogs/CharSettingsDialog.qml"

#: 技能滑杆上限（原 `QSlider.setRange(0, 5)`）
_MAX_SKILL_LEVEL = 5

#: 技能名列的对齐宽度区间（原 `_on_category_changed` 里 `max(120, min(w, 280))`）
_NAME_WIDTH_MIN = 120
_NAME_WIDTH_MAX = 280

#: 三个增效体插槽的标题（原 `ImplantsPage` 里的 `slot_names`）
_SLOT_TITLES = ["插槽 A — 生产与研究", "插槽 B — 精炼与采矿", "插槽 C — 通用"]

#: 新角色的出厂内容（原 `_on_add_character` 里那份 dict，一字不改）
_DEFAULT_MARKET = {hub_key: {"faction_standing": 5.0, "corp_standing": 5.0} for hub_key, *_ in TRADE_HUBS}


def _new_character() -> dict:
    return {"skills": {}, "implants": [None, None, None], "market": {k: dict(v) for k, v in _DEFAULT_MARKET.items()}}


def _matched_count(skills: dict, esi: dict[str, int]) -> int:
    """有多少个技能真的拿到了 ESI 等级（结果摘要用）。

    不等于技能总数：面板里那几个「玩家习惯名」在 SDE 里没有对应技能
    （见 `tests/test_terminology_consistency.py` 的 KNOWN_NON_SDE），
    ESI 永远匹配不上，会一直是 0。
    """
    return sum(1 for name in skills if name in esi)


class SkillsBridge(QObject):
    """「技能」Tab：左侧分类 + 右侧滑杆行。"""

    changed = Signal()
    #: 某个技能等级变了 —— 市场页据此重算费率（原 `slider.changed → _on_skill_for_market`）
    skillsChanged = Signal()

    def __init__(self, skills_data: dict | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, int] = dict(skills_data or {})
        self._row_names: list[str] = []
        self._category_index = 0
        self._rebuild_rows()

    # ── QML 读 ────────────────────────────────────────────────

    #: 分类 [{name, icon}]；icon 是 Phosphor SVG 文件名（经 `icons.ICON_MAP` 语义键映射）
    categories = Property(
        list,
        lambda self: [
            {"name": name, "icon": icons.ICON_MAP.get(icon_key, icon_key)}
            for name, icon_key, _skills in SKILL_CATEGORIES
        ],
        constant=True,
    )

    @Property(int, notify=changed)
    def categoryIndex(self) -> int:
        return self._category_index

    @Property(str, notify=changed)
    def categoryTitle(self) -> str:
        if 0 <= self._category_index < len(SKILL_CATEGORIES):
            return str(SKILL_CATEGORIES[self._category_index][0])
        return "选择左侧分类"

    @Property(list, notify=changed)
    def rows(self) -> list[dict]:
        return [{"name": name, "level": int(self._data.get(name, 0))} for name in self._row_names]

    maxLevel = Property(int, lambda self: _MAX_SKILL_LEVEL, constant=True)
    nameWidthMin = Property(int, lambda self: _NAME_WIDTH_MIN, constant=True)
    nameWidthMax = Property(int, lambda self: _NAME_WIDTH_MAX, constant=True)

    # ── QML 写 ────────────────────────────────────────────────

    @Slot(int)
    def setCategory(self, index: int) -> None:
        if not 0 <= index < len(SKILL_CATEGORIES) or index == self._category_index:
            return
        self._category_index = index
        self._rebuild_rows()
        self.changed.emit()

    @Slot(int, int)
    def setSkillLevel(self, row: int, level: int) -> None:
        """滑杆拖动 → 只记等级，**不重建行**（重建会把正在拖的滑杆删掉）。

        越界行号直接忽略：QML 的 `Repeater` 在换分类的瞬间可能还持有旧行号。
        """
        if not 0 <= row < len(self._row_names):
            return
        self._data[self._row_names[row]] = max(0, min(int(level), _MAX_SKILL_LEVEL))
        self.skillsChanged.emit()

    # ── 给宿主桥 / Python 调用方 ──────────────────────────────

    def skills_data(self) -> dict[str, int]:
        """当前角色的技能等级（原 `SkillsPage.get_data`）。"""
        return dict(self._data)

    def set_skills_data(self, skills_data: dict | None) -> None:
        """换角色：重置等级与分类回到第一页（原 `_rebuild_pages` 新建 `SkillsPage`）。"""
        self._data = dict(skills_data or {})
        self._category_index = 0
        self._rebuild_rows()
        self.changed.emit()
        self.skillsChanged.emit()

    def _rebuild_rows(self) -> None:
        if 0 <= self._category_index < len(SKILL_CATEGORIES):
            self._row_names = list(SKILL_CATEGORIES[self._category_index][2])
        else:
            self._row_names = []


class ImplantsBridge(QObject):
    """「增效体」Tab：三个插槽下拉。"""

    slotsChanged = Signal()

    def __init__(self, implant_ids: list | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._implants = load_implants()
        self._selected: list[Any] = [None, None, None]
        self.set_implant_ids(implant_ids or [])

    @Property(list, notify=slotsChanged)
    def slots(self) -> list[dict]:
        """三个插槽 [{title, options, index}]。

        `options` 首项固定是「-- 无 --」（typeId=None），与 `index` 一一对应 ——
        原版用 `findData` 反查下标，这里在 Python 侧就把下标算好，QML 少一层映射。
        """
        return self._slot_data()

    def _slot_data(self) -> list[dict]:
        """`slots` 的取值实现。

        单独留一个普通方法给 Python 侧调用：直接读 `self.slots` 在 mypy 眼里是
        `Property` 描述符而不是 list（PySide 的桩没把描述符协议建模出来），
        同 `DialogBridge.title_text` 的理由。
        """
        options = [{"label": "-- 无 --", "typeId": None, "bonusDesc": ""}]
        for imp in self._implants:
            label = f"{imp['zh_name']} ({imp['bonus_desc']})" if imp["bonus_desc"] else imp["zh_name"]
            options.append({"label": label, "typeId": imp["type_id"], "bonusDesc": imp["bonus_desc"]})
        out = []
        for i, title in enumerate(_SLOT_TITLES):
            tid = self._selected[i]
            index = 0
            for j, opt in enumerate(options):
                if opt["typeId"] is not None and opt["typeId"] == tid:
                    index = j
                    break
            out.append({"title": title, "options": [dict(o) for o in options], "index": index})
        return out

    @Slot(int, int)
    def setSlotIndex(self, slot: int, index: int) -> None:
        """记住选择。**不发信号**：QML 的下拉自己已经显示新值，重建会把刚合上的弹窗再弹一次。"""
        if not 0 <= slot < len(self._selected):
            return
        options = self._slot_data()
        if not 0 <= index < len(options[slot]["options"]):
            return
        self._selected[slot] = options[slot]["options"][index]["typeId"]

    def set_implant_ids(self, implant_ids: list) -> None:
        self._selected = [implant_ids[i] if i < len(implant_ids) else None for i in range(3)]
        self.slotsChanged.emit()

    def data(self) -> list:
        """三个插槽的 type_id（None = 未装），原 `ImplantsPage.get_data`。"""
        return list(self._selected)


class MarketBridge(QObject):
    """「市场费率」Tab：4 大交易中心的声望 + 自动算出的费率文案。"""

    changed = Signal()
    hubsChanged = Signal()

    def __init__(
        self, skills_data: dict | None = None, market_data: dict | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._skills: dict = dict(skills_data or {})
        self._values: dict[str, dict[str, float]] = {}
        self._results: list[str] = []
        self.set_data(skills_data or {}, market_data or {})

    # ── QML 读 ────────────────────────────────────────────────

    @Property(list, notify=hubsChanged)
    def hubs(self) -> list[dict]:
        """交易中心的身份与声望初值。**只在换角色时重建**（见模块 docstring）。"""
        out = []
        for hub_key, hub_name, faction_name, corp_name in TRADE_HUBS:
            values = self._values.get(hub_key, {"faction_standing": 5.0, "corp_standing": 5.0})
            out.append(
                {
                    "key": hub_key,
                    "name": hub_name,
                    "factionLabel": f"派系声望 ({faction_name}):",
                    "corpLabel": f"军团声望 ({corp_name}):",
                    "faction": float(values["faction_standing"]),
                    "corp": float(values["corp_standing"]),
                }
            )
        return out

    @Property(list, notify=changed)
    def results(self) -> list[str]:
        return list(self._results)

    #: 声望范围（原 `QDoubleSpinBox.setRange(-10.0, 10.0)`）
    standingMin = Property(float, lambda self: -10.0, constant=True)
    standingMax = Property(float, lambda self: 10.0, constant=True)

    # ── QML 写 ────────────────────────────────────────────────

    @Slot(int, float)
    def setFactionStanding(self, hub: int, value: float) -> None:
        self._set_standing(hub, "faction_standing", value)

    @Slot(int, float)
    def setCorpStanding(self, hub: int, value: float) -> None:
        self._set_standing(hub, "corp_standing", value)

    def _set_standing(self, hub: int, field: str, value: float) -> None:
        if not 0 <= hub < len(TRADE_HUBS):
            return
        hub_key = TRADE_HUBS[hub][0]
        self._values.setdefault(hub_key, {"faction_standing": 5.0, "corp_standing": 5.0})[field] = float(value)
        self._recompute()

    # ── 给宿主桥 / Python 调用方 ──────────────────────────────

    def set_skills_data(self, skills_data: dict) -> None:
        """技能变了 → 重算费率（原 `MarketPage.set_skills_data`，连触发方式都一致）。"""
        self._skills = dict(skills_data)
        self._recompute()

    def set_data(self, skills_data: dict, market_data: dict) -> None:
        """换角色：声望初值与费率一起换。"""
        self._skills = dict(skills_data)
        self._values = {
            hub_key: {
                "faction_standing": float(market_data.get(hub_key, {}).get("faction_standing", 5.0)),
                "corp_standing": float(market_data.get(hub_key, {}).get("corp_standing", 5.0)),
            }
            for hub_key, *_ in TRADE_HUBS
        }
        self._recompute()
        self.hubsChanged.emit()

    def data(self) -> dict:
        """{hub_key: {faction_standing, corp_standing}}，原 `MarketPage.get_data`。"""
        return {
            hub_key: {
                "faction_standing": self._values.get(hub_key, {}).get("faction_standing", 5.0),
                "corp_standing": self._values.get(hub_key, {}).get("corp_standing", 5.0),
            }
            for hub_key, *_ in TRADE_HUBS
        }

    def _recompute(self) -> None:
        """四条公式全部复用的 `char_settings_common`，与 Widgets 版同一份实现。"""
        skills = self._skills
        sales_tax = calc_sales_tax(skills)
        relist = calc_relist_discount(skills)
        max_orders = calc_max_orders(skills)
        self._results = []
        for hub_key, *_ in TRADE_HUBS:
            values = self._values.get(hub_key, {"faction_standing": 5.0, "corp_standing": 5.0})
            broker = calc_broker_fee(skills, float(values["faction_standing"]), float(values["corp_standing"]))
            self._results.append(
                f"经纪人费率: {format_pct(broker)} | "
                f"销售税率: {format_pct(sales_tax)} | "
                f"改单折扣: {relist:.0f}% | "
                f"最大订单: {max_orders}"
            )
        self.changed.emit()


class CharSettingsBridge(DialogBridge):
    """人物设置对话框的桥。"""

    stateChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("人物设置")

        self._all_data: dict = load_all_data()
        characters = self._all_data.setdefault("characters", {})
        if not characters:
            # 兜底：原版这里会 `list(...)[0]` 直接 IndexError。空配置下给一个默认角色，
            # 让对话框至少能打开并让用户新建（正常流程里 load_char_config 已保证非空）。
            characters["main"] = _new_character()

        self._skills = SkillsBridge(parent=self)
        self._implants = ImplantsBridge(parent=self)
        self._market = MarketBridge(parent=self)
        # 技能变化 → 市场费率重算（原 `_rebuild_pages` 里的 `slider.changed` 连线）
        self._skills.skillsChanged.connect(self._on_skills_changed)

        current = str(self._all_data.get("current", "main"))
        self._current = current if current in characters else next(iter(characters))

        #: 正在跑的 ESI 导入线程（`stop()` 里要停它）
        self._esi_worker: Any = None
        self._esi_busy = False
        self._esi_status = ""

        self._load_current()

    # ── 三个 Tab 的从属桥 ─────────────────────────────────────

    skills = Property(QObject, lambda self: self._skills, constant=True)
    implants = Property(QObject, lambda self: self._implants, constant=True)
    market = Property(QObject, lambda self: self._market, constant=True)

    # ── 顶部角色栏 ────────────────────────────────────────────

    @Property(list, notify=stateChanged)
    def characterNames(self) -> list[str]:
        return self._character_names()

    def _character_names(self) -> list[str]:
        """`characterNames` 的取值实现（理由同 `ImplantsBridge._slot_data`）。"""
        return list(self._all_data["characters"].keys())

    @Property(int, notify=stateChanged)
    def characterIndex(self) -> int:
        names = self._character_names()
        return names.index(self._current) if self._current in names else -1

    @Property(str, notify=stateChanged)
    def characterName(self) -> str:
        return self._current

    @Property(bool, notify=stateChanged)
    def canDelete(self) -> bool:
        """只剩一个角色时禁掉「删除」（原版是 `setEnabled(False)`）。"""
        return len(self._all_data["characters"]) > 1

    # ── 顶部角色栏的写 ────────────────────────────────────────

    @Slot(int)
    def switchCharacter(self, index: int) -> None:
        names = self._character_names()
        if not 0 <= index < len(names) or names[index] == self._current:
            return
        self._current = names[index]
        self._load_current()

    @Slot()
    def addCharacter(self) -> None:
        """新建角色并选中它（原名从「新角色」往后找空位）。"""
        base = "新角色"
        name = base
        i = 1
        while name in self._all_data["characters"]:
            i += 1
            name = f"{base}{i}"
        self._all_data["characters"][name] = _new_character()
        self._current = name
        self._load_current()

    @Slot()
    def deleteCharacter(self) -> None:
        """删除当前角色 —— 确认框走 `FMessageDialog.question`（返回 `bool`）。"""
        if not self.canDelete:
            return
        if not FMessageDialog.question(
            self.host_widget(),
            "确认删除",
            f"确定要删除角色「{self._current}」吗？",
        ):
            return
        characters = self._all_data["characters"]
        characters.pop(self._current, None)
        self._current = next(iter(characters))
        self._load_current()

    # ── 从 ESI 导入 ──────────────────────────────────────────
    #
    # 手工填写与 ESI 拉取并存：这个按钮只做「用 ESI 的真实数据覆盖已有技能名的
    # 等级」，不改变手工挑选的技能集，也不覆盖用户自建的配置档。

    @Property(bool, notify=stateChanged)
    def esiBusy(self) -> bool:
        return self._esi_busy

    @Property(str, notify=stateChanged)
    def esiStatus(self) -> str:
        """最近一次导入的结果摘要（空串 = 还没导过）。"""
        return self._esi_status

    @Slot()
    def importFromEsi(self) -> None:
        """「刷新当前角色」：已有绑定就静默刷新（不弹浏览器），否则开浏览器授权。"""
        self._start_esi_worker(force_browser=False)

    @Slot()
    def addCharacterFromEsi(self) -> None:
        """「从 ESI 添加角色」：**总是**开浏览器让用户选角色。

        一账号多角色必须走这个入口。少了它，导完角色 A 之后 `current` 就是 A，
        再点「刷新当前角色」只会静默刷 A —— 用户永远没机会选 B，表现成
        「导入一次之后就不让继续导入了」。
        """
        self._start_esi_worker(force_browser=True)

    def _start_esi_worker(self, *, force_browser: bool) -> None:
        if self._esi_busy:
            return
        self._esi_busy = True
        self._esi_status = "正在等待浏览器授权…" if force_browser else "正在从 ESI 获取…"
        self.stateChanged.emit()

        worker = EsiSkillImportWorker(self._current, force_browser=force_browser)
        worker.result_signal.connect(self._on_esi_result)
        worker.finished_signal.connect(self._on_esi_finished)
        self._esi_worker = worker
        worker.start()

    def _on_esi_result(self, payload: dict) -> None:
        """合并 ESI 数据并落盘。

        合并策略见 `core.char_settings_common.merge_esi_skill_levels`：只刷新
        **已有技能名**的等级 —— ESI 返回几百个技能，全写进来会把配置撑爆。
        """
        char_name = str(payload.get("character_name") or "")
        if not char_name:
            return
        esi_skills = dict(payload.get("skills") or {})

        # 下面要切到被导入的角色，先把三个 Tab 里正在编辑的内容收回内存 ——
        # 不收就等于把用户刚拖的技能滑杆丢掉。
        self._flush_current()

        characters = self._all_data["characters"]
        if char_name in characters:
            old_skills = dict(characters[char_name].get("skills") or {})
            merged = merge_esi_skill_levels(old_skills, esi_skills, ALL_SKILLS)
            characters[char_name]["skills"] = merged
            note = f"已更新「{char_name}」：{_matched_count(merged, esi_skills)}/{len(merged)} 个技能拿到等级"
        else:
            data = _new_character()
            # 新角色没有自己的技能集可刷新 → 面板全集做骨架，等级用 ESI 填
            data["skills"] = union_skill_levels(characters, esi_skills, ALL_SKILLS)
            characters[char_name] = data
            note = f"已添加角色「{char_name}」：{_matched_count(data['skills'], esi_skills)}/{len(data['skills'])} 个技能拿到等级"

        slots, unknown = self._implants_to_slots([int(t) for t in (payload.get("implants") or [])])
        if any(slot is not None for slot in slots):
            characters[char_name]["implants"] = slots
        note += f"；{sum(1 for slot in slots if slot is not None)} 个增效体"
        if unknown:
            note += f"（{len(unknown)} 个不属于本应用可选的工业增效体，已忽略）"

        self._current = char_name
        self._all_data["current"] = char_name
        save_all_data(self._all_data)
        self._load_current()
        self._esi_status = note
        self.stateChanged.emit()
        FMessageDialog.information(self.host_widget(), "从 ESI 导入完成", note)

    def _implants_to_slots(self, type_ids: list[int]) -> tuple[list, list[int]]:
        """ESI 的植入体 type_id → 本应用那三个**自造**插槽。

        三个插槽不是 EVE 的真实槽位（见 `_SLOT_TITLES`），归类规则在
        `services.implant_loader._implant_slot`。同槽多个只留第一个。
        返回 (三槽, 不在可选清单里的 type_id) —— 后者不算错（纯属性植入体本应用用不上）。
        """
        catalog = {int(imp["type_id"]): str(imp["slot"]) for imp in load_implants()}
        by_slot: dict[str, int] = {}
        unknown: list[int] = []
        for tid in type_ids:
            slot = catalog.get(tid)
            if slot is None:
                unknown.append(tid)
            else:
                by_slot.setdefault(slot, tid)
        return [by_slot.get(key) for key in ("A", "B", "C")], unknown

    def _on_esi_finished(self, ok: bool, message: str) -> None:
        self._esi_busy = False
        # ⚠️ 这里**不要**把 `self._esi_worker` 置 None。`finished_signal` 是在
        # `run()` 内部发出的，槽可能在 `run()` 尚未返回时就跑到 —— 那一刻丢掉
        # QThread 的最后一个 Python 引用会让 Qt 直接 abort()（本仓记录过的崩溃）。
        # 引用留到下次导入覆盖，或 `stop()` 里由 `detach_worker` 安全收尾。
        if not ok:
            self._esi_status = ""
            self.set_error(message)
            FMessageDialog.warning(self.host_widget(), "从 ESI 导入失败", message)
        self.stateChanged.emit()

    def stop(self) -> None:
        """关窗收尾：中断回环等待并等它收尾。

        `detach_worker` 只等 500ms，而 worker 里回环 `handle_request()` 的超时是
        0.5s —— 检查点刚好够密，不用额外的中断机制。
        """
        detach_worker(self._esi_worker)
        self._esi_worker = None

    # ── 保存 ──────────────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        """「保存」：把三页数据写回当前角色并落盘（原 `_on_save`）。"""
        self._flush_current()
        save_all_data(self._all_data)
        FMessageDialog.information(self.host_widget(), "保存成功", "角色配置已保存")
        self.accepted.emit()

    # ── 内部 ──────────────────────────────────────────────────

    def _flush_current(self) -> None:
        """把三个 Tab 的当前编辑写回内存（不落盘）。

        换角色前必须做：子桥里的编辑不收回 `_all_data` 就会被 `_load_current`
        覆盖掉。`accept()` 与 ESI 导入都要走这一步。
        """
        char_data = self._all_data["characters"].setdefault(self._current, {})
        char_data["skills"] = self._skills.skills_data()
        char_data["implants"] = self._implants.data()
        char_data["market"] = self._market.data()

    def _load_current(self) -> None:
        """把当前角色的数据灌进三个从属桥（原 `_rebuild_pages`）。"""
        char_data = self._all_data["characters"].get(self._current, {})
        skills = char_data.get("skills", {})
        self._skills.set_skills_data(skills)
        self._implants.set_implant_ids(char_data.get("implants", [None, None, None]))
        self._market.set_data(skills, char_data.get("market", {}))
        self.stateChanged.emit()

    def _on_skills_changed(self) -> None:
        self._market.set_skills_data(self._skills.skills_data())


class CharSettingsQmlDialog(QmlDialog):
    """QML 版人物设置。`CharSettingsDialog(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        bridge = CharSettingsBridge()
        super().__init__(_QML_FILE, bridge, parent=parent, size=(750, 600))
        self._char_bridge = bridge

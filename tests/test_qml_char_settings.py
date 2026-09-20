"""人物设置（技能 / 增效体 / 市场费率）的 QML 桥业务契约（阶段 4b）。

只放**业务契约**：三个 Tab 各自的数据形状与写回、跨页联动（技能→费率）、
多角色的增删改与保存。「QML 能否加载 / 有没有告警」是统一护栏的事，不在本文件重复。

配置读写与植入体都打桩：前者避免污染 `data/char_config.json`，
后者避免依赖 `reference.db` 里到底装了几个增效体。
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

import ui_qml.bridge.char_settings_bridge as csb
from core.char_settings_common import ALL_SKILLS, SKILL_CATEGORIES, TRADE_HUBS
from ui_qml import icons
from ui_qml.workers import esi_skill_worker as esw

pytestmark = pytest.mark.ui


class _QMessageBox:
    """`FMessageDialog` 替身：记下答复与提示，不碰真 Qt 类（静态方法在 PySide 上不好打桩）。

    `question` 现在返回 **`bool`**（对齐 `FMessageDialog` 的形状）。旧版返回
    `StandardButton.Yes` 那个对象，桥里 `if not stub.question(...)` 会因对象恒真
    永远走「是」分支 —— 那是「点否也照删」的静默失效，故 stub 必须给裸 bool。
    """

    def __init__(self, reply: str = "no") -> None:
        self.reply = reply
        self.informed: list[tuple[str, str]] = []

    def question(self, parent, title, text, *args, **kwargs) -> bool:
        return self.reply == "yes"

    def information(self, parent, title, text, *args, **kwargs):
        self.informed.append((title, text))


_CONFIG = {
    "current": "甲",
    "characters": {
        "甲": {
            "skills": {"会计学": 5, "工业理论": 3},
            "implants": [None, 1001, None],
            "market": {"jita": {"faction_standing": 8.0, "corp_standing": 2.0}},
        },
        "乙": {"skills": {}, "implants": [None, None, None], "market": {}},
    },
}


@pytest.fixture
def harness(qapp, monkeypatch):
    written: dict = {}
    box = _QMessageBox()
    monkeypatch.setattr(csb, "load_all_data", lambda: deepcopy(_CONFIG))
    monkeypatch.setattr(csb, "save_all_data", lambda data: written.update(deepcopy(data)))
    monkeypatch.setattr(
        csb,
        "load_implants",
        lambda: [{"type_id": 1001, "zh_name": "工业增效体", "bonus_desc": "制造时间 -4%", "slot": "A"}],
    )
    monkeypatch.setattr(csb, "FMessageDialog", box)
    return SimpleNamespace(bridge=csb.CharSettingsBridge(), written=written, box=box)


# ── 技能页 ───────────────────────────────────────────────────


def test_categories_reuse_the_shared_table_and_icon_map(harness):
    """分类名与图标必须来自 `char_settings_common.SKILL_CATEGORIES` + `icons.ICON_MAP`。"""
    categories = harness.bridge.skills.categories

    assert [c["name"] for c in categories] == [name for name, _icon, _skills in SKILL_CATEGORIES]
    assert [c["icon"] for c in categories] == [
        icons.ICON_MAP.get(icon_key, icon_key) for _name, icon_key, _skills in SKILL_CATEGORIES
    ]
    # 语义键要换成 Phosphor 文件名（QML 侧直接拼 image://phosphor/<name>），不是原样透传
    assert categories[0]["icon"] == icons.ICON_MAP["settings"] != "settings"


def test_switching_category_rebuilds_rows_and_keeps_levels(harness):
    skills = harness.bridge.skills
    assert [r["name"] for r in skills.rows] == list(SKILL_CATEGORIES[0][2])
    assert next(r for r in skills.rows if r["name"] == "工业理论")["level"] == 3

    skills.setCategory(1)
    assert skills.categoryIndex == 1
    assert skills.categoryTitle == SKILL_CATEGORIES[1][0]
    assert [r["name"] for r in skills.rows] == list(SKILL_CATEGORIES[1][2])
    # 未记过的技能取 0（原版 `self._data.get(skill_name, 0)`）
    assert all(r["level"] == 0 for r in skills.rows)


def test_out_of_range_category_is_ignored(harness):
    skills = harness.bridge.skills
    skills.setCategory(999)
    assert skills.categoryIndex == 0


def test_dragging_a_slider_records_the_level_without_rebuilding_rows(harness):
    """拖滑杆只发 `skillsChanged`，**不发** `changed`。

    发 `changed` 会让 QML 重建整张技能行 —— 正在拖的那个滑杆会被删掉、拖动中断
    （`Repeater` 的 model 被换成新数组就是一次重置）。这条是滑杆能用的前提。
    """
    skills = harness.bridge.skills
    changed: list[int] = []
    dragged: list[int] = []
    skills.changed.connect(lambda: changed.append(1))
    skills.skillsChanged.connect(lambda: dragged.append(1))

    skills.setSkillLevel(0, 5)

    assert skills.skills_data()["工业理论"] == 5
    assert dragged == [1]
    assert changed == []


def test_skill_level_is_clamped_and_bad_rows_are_ignored(harness):
    skills = harness.bridge.skills
    skills.setSkillLevel(0, 99)
    assert skills.skills_data()["工业理论"] == skills.maxLevel

    skills.setSkillLevel(999, 3)  # 换分类瞬间 QML 可能还拿着旧行号
    assert len(skills.skills_data()) == 2


# ── 跨页联动：技能 → 市场费率 ────────────────────────────────


def test_skill_change_triggers_a_market_recompute(harness):
    bridge = harness.bridge
    recomputed: list[int] = []
    bridge.market.changed.connect(lambda: recomputed.append(1))

    bridge.skills.setSkillLevel(0, 4)

    assert recomputed == [1], "技能变化必须让市场页重算费率（原 `_on_skill_for_market`）"


def test_market_fees_follow_the_accounting_skill(harness):
    """费率公式来自 `char_settings_common`（本项目只有这一份实现）。"""
    bridge = harness.bridge
    bridge.market.set_skills_data({"会计学": 0})
    assert "销售税率: 2.00%" in bridge.market.results[0]

    bridge.market.set_skills_data({"会计学": 5})
    assert "销售税率: 1.70%" in bridge.market.results[0]


# ── 市场页 ───────────────────────────────────────────────────


def test_market_hubs_reuse_the_shared_hub_table(harness):
    hubs = harness.bridge.market.hubs
    assert [h["key"] for h in hubs] == [hub_key for hub_key, *_ in TRADE_HUBS]

    jita = hubs[0]
    assert jita["faction"] == 8.0 and jita["corp"] == 2.0  # 甲 存过的声望
    assert "加达里" in jita["factionLabel"] and "加达里海军" in jita["corpLabel"]
    # 没存过声望的中心走默认 5.0/5.0
    assert hubs[1]["faction"] == 5.0


def test_market_standing_edits_round_trip(harness):
    market = harness.bridge.market
    before = list(market.results)

    market.setFactionStanding(0, 10.0)
    market.setCorpStanding(0, 10.0)

    assert market.data()["jita"] == {"faction_standing": 10.0, "corp_standing": 10.0}
    assert market.results[0] != before[0], "改了声望，费率文案要跟着变"
    assert market.results[1] == before[1], "只动 jita，其他中心不受影响"


def test_market_ignores_out_of_range_hubs(harness):
    market = harness.bridge.market
    market.setFactionStanding(99, 1.0)
    assert market.data()["jita"]["faction_standing"] == 8.0


# ── 增效体页 ─────────────────────────────────────────────────


def test_implant_options_lead_with_none_and_carry_the_bonus(harness):
    slots = harness.bridge.implants.slots
    assert len(slots) == 3

    options = slots[1]["options"]
    assert options[0]["label"] == "-- 无 --" and options[0]["typeId"] is None
    assert options[1]["typeId"] == 1001
    assert options[1]["label"] == "工业增效体 (制造时间 -4%)"
    assert options[1]["bonusDesc"] == "制造时间 -4%"
    # 存过的插槽直接给出下标，QML 不用再 findData 反查
    assert [s["index"] for s in slots] == [0, 1, 0]


def test_implant_selection_maps_back_to_type_ids(harness):
    implants = harness.bridge.implants
    assert implants.data() == [None, 1001, None]

    implants.setSlotIndex(1, 0)
    assert implants.data() == [None, None, None]

    implants.setSlotIndex(0, 1)
    assert implants.data() == [1001, None, None]


# ── 多角色 ───────────────────────────────────────────────────


def test_switching_character_reloads_all_three_tabs(harness):
    bridge = harness.bridge
    bridge.skills.setSkillLevel(0, 4)  # 先改脏当前角色

    bridge.switchCharacter(1)

    assert bridge.characterName == "乙"
    assert bridge.characterIndex == 1
    assert bridge.skills.skills_data() == {}, "换角色要丢掉上一个人的技能改动"
    assert bridge.implants.data() == [None, None, None]
    assert bridge.market.data()["jita"]["faction_standing"] == 5.0


def test_add_character_picks_a_free_name_and_selects_it(harness):
    bridge = harness.bridge
    bridge.addCharacter()
    assert bridge.characterName == "新角色"
    assert bridge.canDelete is True

    bridge.addCharacter()
    assert bridge.characterNames == ["甲", "乙", "新角色", "新角色2"]
    assert bridge.characterIndex == 3


def test_delete_character_asks_first(harness):
    bridge = harness.bridge
    harness.box.reply = "no"
    bridge.deleteCharacter()
    assert bridge.characterNames == ["甲", "乙"], "答复否时不许动配置"

    harness.box.reply = "yes"
    bridge.deleteCharacter()
    assert bridge.characterNames == ["乙"]
    assert bridge.characterName == "乙", "删完要落到第一个可用角色上"


def test_last_character_cannot_be_deleted(harness):
    bridge = harness.bridge
    harness.box.reply = "yes"
    bridge.switchCharacter(1)
    bridge.deleteCharacter()
    assert bridge.characterNames == ["甲"]
    assert bridge.canDelete is False
    bridge.deleteCharacter()  # 再点一次（QML 里按钮是禁用的，这里守 Python 侧）
    assert bridge.characterNames == ["甲"]


# ── 保存 ─────────────────────────────────────────────────────


def test_save_writes_all_three_pages_and_the_current_character(harness):
    bridge = harness.bridge
    closed: list[bool] = []
    bridge.accepted.connect(lambda: closed.append(True))

    bridge.skills.setSkillLevel(0, 4)
    bridge.implants.setSlotIndex(2, 1)
    bridge.market.setFactionStanding(0, 9.0)
    bridge.accept()

    saved = harness.written
    assert saved["current"] == "甲"
    assert saved["characters"]["甲"]["skills"] == bridge.skills.skills_data()
    assert saved["characters"]["甲"]["implants"] == [None, 1001, 1001]
    assert saved["characters"]["甲"]["market"]["jita"]["faction_standing"] == 9.0
    assert saved["characters"]["乙"] == _CONFIG["characters"]["乙"], "没动过的角色要保持原样"
    assert harness.box.informed and harness.box.informed[0][0] == "保存成功"
    assert closed == [True]


# ── 宿主对话框的构造签名 ─────────────────────────────────────


def test_dialog_keeps_the_original_constructor_signature(harness):
    """`CharSettingsDialog(parent)` 的调用方只换类名就能用。"""
    dialog = csb.CharSettingsQmlDialog(None)
    try:
        assert dialog.ok()
        assert dialog.bridge.characterName == "甲"
        assert len(dialog.bridge.skills.categories) == len(SKILL_CATEGORIES)
    finally:
        dialog.deleteLater()


# ── 从 ESI 导入（QThread + Signal 端到端）─────────────────────

#: 打桩的 ESI 结果。`会计学` / `工业理论` 是 `_CONFIG["甲"]` 里**已有**的名字，
#: `贸易学` 是 ESI 独有的 —— 它不该被写进配置（合并策略只管已有名字）。
_ESI_PAYLOAD = {
    "character_id": 2112625428,
    "character_name": "甲",
    "skills": {"会计学": 3, "工业理论": 5, "贸易学": 5},
    "implants": [1001, 999999],
}


def test_esi_import_merges_only_existing_names_and_saves(harness, monkeypatch, qtbot):
    """点「从 ESI 导入」→ 线程回数据 → 桥合并落盘。

    覆盖整条接线：worker 起线程、发信号、主线程槽合并、写回 `save_all_data`。
    授权与网络换成固定载荷 —— 真 SSO / 真 ESI 不该进单测。
    """

    async def _fake_import(self: object) -> dict:
        return dict(_ESI_PAYLOAD)

    monkeypatch.setattr(csb.EsiSkillImportWorker, "_import", _fake_import)
    bridge = harness.bridge

    bridge.importFromEsi()
    assert bridge.esiBusy is True, "点下去就该进忙碌态（按钮据此禁用）"
    qtbot.waitUntil(lambda: not bridge.esiBusy, timeout=5000)

    saved = harness.written["characters"]["甲"]
    # ⭐ 回归：面板能显示的技能必须**全部**落盘。先前只写「char_config 里手填过
    # 的名字」，于是造船/冶金/研究那一大片永远是 0，看起来像没导入。
    assert set(ALL_SKILLS) <= set(saved["skills"])
    # 已有名字被 ESI 的真实等级刷新（手工填的 5 → ESI 上的 3）
    assert saved["skills"]["会计学"] == 3
    assert saved["skills"]["工业理论"] == 5
    # ESI 独有的、不属于面板的技能不进配置
    assert "贸易学" not in saved["skills"]
    # 增效体：1001 在可选清单里（stub 归 A 槽）；999999 不在清单里 → 忽略
    assert saved["implants"] == [1001, None, None]
    assert harness.box.informed and harness.box.informed[0][0] == "从 ESI 导入完成"
    assert bridge.esiStatus != ""


def test_esi_import_keeps_manual_implants_when_esi_returns_none(harness, monkeypatch, qtbot):
    """ESI 没带回任何可用增效体时，**不覆盖**用户手填的那几个。

    这是「两种方式并存」的边界：ESI 的空结果不等于「角色没装植入体」，
    更不该把用户手工挑的抹掉。
    """

    async def _fake_import(self: object) -> dict:
        return {"character_id": 1, "character_name": "甲", "skills": {"会计学": 2}, "implants": [999999]}

    monkeypatch.setattr(csb.EsiSkillImportWorker, "_import", _fake_import)
    bridge = harness.bridge

    bridge.importFromEsi()
    qtbot.waitUntil(lambda: not bridge.esiBusy, timeout=5000)

    assert harness.written["characters"]["甲"]["implants"] == _CONFIG["characters"]["甲"]["implants"]


@pytest.mark.parametrize(("force_browser", "expected"), [(True, "browser"), (False, "silent")])
def test_add_from_esi_always_opens_browser(qapp, monkeypatch, force_browser, expected):
    """⭐ 回归：一账号多角色必须能**连续**导入。

    复现的缺陷：导完角色 A 之后 `current` 就是 A，再点导入会命中 A 的绑定走静默
    刷新，浏览器根本不打开 —— 用户没机会在 CCP 页面上选角色 B，表现成
    「导入成功一次之后就不让继续导入了」。

    所以「+ 从 ESI」必须强制走浏览器；只有「刷新技能」才允许静默刷新已有绑定。
    """
    calls: list[str] = []
    # 过期时间戳 → 绑定存在但需要刷新，这样两条分支才都走得到
    monkeypatch.setattr(
        esw,
        "load_token_row",
        lambda name: {
            "character_id": 1,
            "character_name": name,
            "refresh_token": "r",
            "access_token": "old",
            "access_expires_at": "2000-01-01T00:00:00Z",
        },
    )

    async def fake_browser(self: object, client: object) -> tuple[str, int, str]:
        calls.append("browser")
        return "a", 1, "甲"

    async def fake_refresh(self: object, client: object, row: dict) -> tuple[str, int, str]:
        calls.append("silent")
        return "a", 1, "甲"

    monkeypatch.setattr(esw.EsiSkillImportWorker, "_browser_authorize", fake_browser)
    monkeypatch.setattr(esw.EsiSkillImportWorker, "_refresh", fake_refresh)

    worker = esw.EsiSkillImportWorker("甲", force_browser=force_browser)

    assert asyncio.run(worker._obtain_token(None)) == ("a", 1, "甲")
    assert calls == [expected]

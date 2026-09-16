"""人物设置（技能 / 增效体 / 市场费率）的 QML 桥业务契约（阶段 4b）。

只放**业务契约**：三个 Tab 各自的数据形状与写回、跨页联动（技能→费率）、
多角色的增删改与保存。「QML 能否加载 / 有没有告警」是统一护栏的事，不在本文件重复。

配置读写与植入体都打桩：前者避免污染 `data/char_config.json`，
后者避免依赖 `reference.db` 里到底装了几个增效体。
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import ui_qml.bridge.char_settings_bridge as csb
from core.char_settings_common import SKILL_CATEGORIES, TRADE_HUBS
from ui_qml import icons

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
        lambda: [{"type_id": 1001, "zh_name": "工业增效体", "bonus_desc": "制造时间 -4%"}],
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

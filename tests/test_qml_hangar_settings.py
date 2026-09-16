"""机库设置对话框（QML）的业务契约测试。

只锁业务：列表标签、编辑区装载 / 改件互斥、两步删除、默认机库（含「已删除的机库」保留原值
这条回归）、保存时的校验与落库，外加「宿主签名与原类一致」这条契约。
**不放**「加载无告警」那条 —— 由主流程在 `tests/test_qml_dialogs.py` 统一加。

与 Widgets 版 `ui_pyside6/views/hangar_settings_view.py` 逐条对齐。
"""

from __future__ import annotations

import inspect
from typing import cast

from ui_qml.bridge import hangar_settings_bridge as hsb
from ui_qml.bridge.hangar_settings_bridge import HangarSettingsBridge, HangarSettingsQmlDialog

#: 与 Widgets 版同名测试文件里的 DEFAULT_CFG 同形（未配置任何设施）
DEFAULT_CFG: dict = {
    "structure_mat_saving": 1.0,
    "structure_time_mod": 1.0,
    "structure_cost_mult": 1.0,
    "facility_tax": None,
    "facility_type": None,
    "rig_ids": [],
}

MOCK_HANGARS: list[dict] = [
    {
        "id": 1,
        "name": "制造仓",
        "notes": "",
        "solar_system_id": None,
        "facility_type": None,
        "facility_tax": None,
        "rigs": None,
    }
]

#: 莱塔卢可装配的改件目录：装备组两个（材料 / 时间，同类别互斥）+ 弹药组一个
CATALOG: list[dict] = [
    {
        "type_id": 1816,
        "zh_name": "装备材料钻机",
        "en_name": "Equipment Rig",
        "category_key": "equipment",
        "category_label": "装备制造",
        "effect": "mat",
        "mat_bonus": -2.0,
        "time_bonus": 0.0,
    },
    {
        "type_id": 1819,
        "zh_name": "装备时间钻机",
        "en_name": "Equipment Time Rig",
        "category_key": "equipment",
        "category_label": "装备制造",
        "effect": "time",
        "mat_bonus": 0.0,
        "time_bonus": -20.0,
    },
    {
        "type_id": 1820,
        "zh_name": "弹药材料钻机",
        "en_name": "Ammo Rig",
        "category_key": "ammunition",
        "category_label": "弹药制造",
        "effect": "mat",
        "mat_bonus": -1.0,
        "time_bonus": 0.0,
    },
]


def _install(
    monkeypatch,
    *,
    hangars: list[dict] | None = None,
    cfg: dict | None = None,
    catalog: list[dict] | None = None,
    systems: dict[int, str] | None = None,
    settings: dict | None = None,
    references: list[str] | None = None,
    problems: list[str] | None = None,
) -> dict[str, list]:
    """打桩机库 / 配置解析 / 改件目录 / 星系名 / settings / 校验，返回落库调用记录。

    `delete` 记录成 `(机库 id, repoint_to)`；无引用那条路径**不带该关键字**，用 `"缺省"`
    哨兵区分 —— 原版两条分支的调用形状不同（一条带 repoint_to、一条不带）。
    """
    calls: dict[str, list] = {
        "config": [],
        "system": [],
        "defaults": [],
        "delete": [],
        "create": [],
        "rename": [],
    }
    hangar_list = [dict(h) for h in (hangars if hangars is not None else MOCK_HANGARS)]

    def _record_config(hid, facility_type, tax, rigs):
        calls["config"].append((hid, facility_type, tax, list(rigs or [])))

    def _record_system(hid, sid):
        calls["system"].append((hid, sid))

    def _record_rename(hid, name):
        calls["rename"].append((hid, name))

    def _record_delete(hid, **kw):
        # 记录成 `(机库 id, repoint_to)`；无引用那条路径**不带该关键字**，用 `"缺省"` 哨兵
        # 区分 —— 原版两条分支的调用形状不同（一条带 repoint_to、一条不带）。
        calls["delete"].append((hid, kw.get("repoint_to", "缺省")))

    monkeypatch.setattr(hsb.inventory_manager, "get_hangars", lambda: [dict(h) for h in hangar_list])
    monkeypatch.setattr(hsb.inventory_manager, "update_hangar_config", _record_config)
    monkeypatch.setattr(hsb.inventory_manager, "update_hangar_system", _record_system)
    monkeypatch.setattr(hsb.inventory_manager, "rename_hangar", _record_rename)
    monkeypatch.setattr(hsb.inventory_manager, "delete_hangar", _record_delete)
    monkeypatch.setattr(hsb.inventory_manager, "hangar_references", lambda hid: list(references or []))
    monkeypatch.setattr(hsb, "resolve_hangar_industry_config", lambda hid: dict(cfg or DEFAULT_CFG))
    # 目录按设施类型给：NPC / 未选设施没有可装配目录（与真实 `get_rig_catalog` 同判据，
    # 否则「换 NPC 之后改件区该空掉」这条会假通过）
    monkeypatch.setattr(
        hsb,
        "get_rig_catalog",
        lambda facility_type: (
            [dict(c) for c in (catalog or [])]
            if hsb.STRUCTURE_BASE.get(facility_type or "npc", {}).get("rig_size")
            else []
        ),
    )
    monkeypatch.setattr(hsb, "resolve_system_display_names_batch", lambda sids: dict(systems or {}))
    monkeypatch.setattr(hsb, "validate_rig_set", lambda rigs, facility_type: list(problems or []))
    monkeypatch.setattr(hsb.user_settings, "load_settings", lambda: dict(settings or {}))
    monkeypatch.setattr(
        hsb.user_settings,
        "set_default_hangar_id",
        lambda key, hid: calls["defaults"].append((key, hid)),
    )
    return calls


def _two_hangars() -> list[dict]:
    return [dict(MOCK_HANGARS[0]), {**MOCK_HANGARS[0], "id": 2, "name": "矿仓"}]


# `bridge.rigGroups` / `bridge.defaultRows` 在 mypy 眼里是 `Property` 描述符而不是 list
# （同 `DialogBridge.title_text` 里注明的理由），测试要当 list 用就显式 cast 一次。
def _rig_items(bridge: HangarSettingsBridge) -> list[dict]:
    groups = cast("list[dict]", bridge.rigGroups)
    return [item for group in groups for item in group["items"]]


def _default_row(bridge: HangarSettingsBridge, key: str) -> dict:
    return next(row for row in cast("list[dict]", bridge.defaultRows) if row["key"] == key)


# ════════════════════════════════════════════════════════════════
#  纯函数：文案与展示规则
# ════════════════════════════════════════════════════════════════


def test_rig_label_formats_bonuses():
    """改件文案：材料/时间各按原格式，两者都没有时给「加成未拉取」而不是 0%。"""
    assert hsb.rig_label(CATALOG[0]) == "装备材料钻机  [材料 -2.0%]"
    assert hsb.rig_label(CATALOG[1]) == "装备时间钻机  [时间 -20%]"
    assert hsb.rig_label({**CATALOG[0], "mat_bonus": 0.0}) == "装备材料钻机  [加成未拉取（运行数据初始化）]"


def test_base_bonus_text_covers_npc_and_structures():
    assert hsb.base_bonus_text(None) == "NPC 空间站无结构本体加成，不可装配改装件"
    assert hsb.base_bonus_text("npc") == "NPC 空间站无结构本体加成，不可装配改装件"
    assert hsb.base_bonus_text("raitaru") == "材料 0.99 / 成本 0.97 / 时间 0.85（NPC=1.0）"


def test_summary_text_wording():
    """底部汇总的拼接顺序与「跟随默认」措辞逐字对齐原 `_update_summary`。"""
    base = {
        "structure_mat_saving": 0.99,
        "structure_time_mod": 0.85,
        "structure_cost_mult": 0.97,
        "facility_tax": None,
    }
    assert hsb.summary_text(base) == "当前加成: 材料 0.99 / 时间 0.85 / 安装费 0.97 | 设施税 跟随默认"
    assert hsb.summary_text({**base, "facility_tax": 0.25}).endswith("| 设施税 0.25")


# ════════════════════════════════════════════════════════════════
#  列表与编辑区装载
# ════════════════════════════════════════════════════════════════


def test_hangar_labels_carry_the_system_suffix(qapp, monkeypatch):
    """机库列表条目带星系中英对照后缀，编辑区显示同一个名字。"""
    hangars = [{**MOCK_HANGARS[0], "solar_system_id": 30000142}]
    _install(monkeypatch, hangars=hangars, systems={30000142: "吉他 (Jita)"})

    bridge = HangarSettingsBridge()
    assert bridge.hangarLabels == ["制造仓 (吉他 (Jita))"]
    assert bridge.currentRow == 0
    assert bridge.hasHangars is True
    assert bridge.systemText == "吉他 (Jita)"


def test_editor_loads_the_stored_config(qapp, monkeypatch):
    """装载：设施类型 / 设施税（不跟随默认）/ 已配置改件勾选 / 本体加成 / 汇总。"""
    cfg = {
        **DEFAULT_CFG,
        "facility_type": "raitaru",
        "facility_tax": 0.5,
        "rig_ids": [1816, 1820],
    }
    _install(monkeypatch, cfg=cfg, catalog=CATALOG)

    bridge = HangarSettingsBridge()
    assert bridge.facilityIndex == 1  # _FACILITY_ORDER 里 raitaru 排第二
    assert bridge.taxFollowDefault is False
    assert bridge.taxValue == 0.5
    assert bridge.baseBonusText == "材料 0.99 / 成本 0.97 / 时间 0.85（NPC=1.0）"
    assert [item["checked"] for item in _rig_items(bridge)] == [True, False, True]
    assert [g["label"] for g in bridge.rigGroups] == ["装备制造", "弹药制造"]


def test_editor_defaults_when_unconfigured(qapp, monkeypatch):
    """未配置过的机库：NPC 设施、税跟随默认（且微调框留在原版的 0.25）、没有改件。"""
    _install(monkeypatch)

    bridge = HangarSettingsBridge()
    assert bridge.facilityIndex == 0
    assert bridge.taxFollowDefault is True
    assert bridge.taxValue == 0.25
    assert bridge.rigGroups == []
    assert bridge.baseBonusText == "NPC 空间站无结构本体加成，不可装配改装件"
    assert bridge.summaryText.endswith("| 设施税 跟随默认")


def test_no_hangars_leaves_the_editor_empty(qapp, monkeypatch):
    _install(monkeypatch, hangars=[])

    bridge = HangarSettingsBridge()
    assert bridge.hasHangars is False
    assert bridge.currentRow == -1
    assert bridge.hangarLabels == []
    assert bridge.rigGroups == []
    assert bridge.systemText == "未设置"


# ════════════════════════════════════════════════════════════════
#  改件互斥 / 设施切换
# ════════════════════════════════════════════════════════════════


def test_rigs_are_mutually_exclusive_within_a_category(qapp, monkeypatch):
    """同制造类别互斥：勾第二个时第一个自动取消；不同类别互不影响。"""
    cfg = {**DEFAULT_CFG, "facility_type": "raitaru", "rig_ids": [1816]}
    _install(monkeypatch, cfg=cfg, catalog=CATALOG)

    bridge = HangarSettingsBridge()
    assert [item["checked"] for item in _rig_items(bridge)] == [True, False, False]

    bridge.setRigChecked(1819, True)  # 同属「装备制造」
    assert [item["checked"] for item in _rig_items(bridge)] == [False, True, False]

    bridge.setRigChecked(1820, True)  # 另一个类别 → 共存
    assert [item["checked"] for item in _rig_items(bridge)] == [False, True, True]

    bridge.setRigChecked(1819, False)
    assert [item["checked"] for item in _rig_items(bridge)] == [False, False, True]


def test_unknown_rig_id_is_ignored(qapp, monkeypatch):
    """目录里没有的 id（旧配置残留）不该被勾上，也不该动到别的勾选。"""
    cfg = {**DEFAULT_CFG, "facility_type": "raitaru", "rig_ids": [1820]}
    _install(monkeypatch, cfg=cfg, catalog=CATALOG)

    bridge = HangarSettingsBridge()
    bridge.setRigChecked(9999, True)
    assert [item["checked"] for item in _rig_items(bridge)] == [False, False, True]


def test_switching_facility_clears_the_rigs(qapp, monkeypatch):
    """换设施类型 → 已勾改件清空（原版重建改件区后不会回勾），NPC 连汇总文案都换掉。"""
    cfg = {**DEFAULT_CFG, "facility_type": "raitaru", "rig_ids": [1816]}
    _install(monkeypatch, cfg=cfg, catalog=CATALOG)

    bridge = HangarSettingsBridge()
    bridge.setFacilityIndex(0)  # NPC 空间站
    assert bridge.facilityIndex == 0
    assert bridge.rigGroups == []
    assert bridge.summaryText == "NPC 空间站无结构改装件"
    assert bridge.baseBonusText == "NPC 空间站无结构本体加成，不可装配改装件"

    # 再换回莱塔卢：原先勾的改件不该自己冒出来
    bridge.setFacilityIndex(1)
    assert [item["checked"] for item in _rig_items(bridge)] == [False, False, False]


def test_switching_facility_keeps_tax_and_caches_the_catalog_per_facility(qapp, monkeypatch):
    """换设施不该动设施税；改件目录按设施类型分别取，同一类型只查一次。"""
    cfg = {**DEFAULT_CFG, "facility_type": "raitaru", "facility_tax": 1.5}
    _install(monkeypatch, cfg=cfg, catalog=CATALOG)
    fetched: list[str] = []
    monkeypatch.setattr(hsb, "get_rig_catalog", lambda facility_type: fetched.append(facility_type) or [])

    bridge = HangarSettingsBridge()
    assert bridge.taxValue == 1.5 and bridge.taxFollowDefault is False
    assert bridge.rigGroups == []  # 装载读一次 → 查 raitaru
    bridge.setFacilityIndex(2)  # 阿兹贝尔
    _ = bridge.rigGroups
    bridge.setFacilityIndex(3)  # 索迪约
    _ = bridge.rigGroups
    _ = bridge.rigGroups  # 同一类型不重复查
    assert bridge.taxValue == 1.5
    assert fetched == ["raitaru", "azbel", "sotiyo"]


def test_editor_key_changes_on_hangar_switch(qapp, monkeypatch):
    """编辑区重建键：换机库 / 重载列表时变（QML 靠它重建控件、重建被打断的绑定）。"""
    _install(monkeypatch, hangars=_two_hangars())

    bridge = HangarSettingsBridge()
    first = bridge.editorKey
    bridge.selectHangar(1)
    assert bridge.currentRow == 1
    assert bridge.editorKey != first

    same = bridge.editorKey
    bridge.selectHangar(1)  # 同一行 → 不动
    bridge.selectHangar(9)  # 越界 → 不动
    assert bridge.editorKey == same


# ════════════════════════════════════════════════════════════════
#  星系
# ════════════════════════════════════════════════════════════════


def test_pick_system_writes_and_updates_the_label(qapp, monkeypatch):
    """「选择星系…」复用已迁好的星系搜索对话框，选中即落库并刷新列表后缀。"""
    calls = _install(monkeypatch)

    class _FakeSearch:
        def __init__(self, parent=None, title: str = "") -> None: ...

        def exec(self) -> int:
            return 1

        def get_selected(self) -> tuple[int, str] | None:
            return (30000142, "吉他 (Jita)")

    monkeypatch.setattr("ui_qml.bridge.system_search_bridge.SystemSearchQmlDialog", _FakeSearch)

    bridge = HangarSettingsBridge()
    bridge.pickSystem()
    assert calls["system"] == [(1, 30000142)]
    assert bridge.systemText == "吉他 (Jita)"
    assert bridge.hangarLabels == ["制造仓 (吉他 (Jita))"]


def test_clear_system_removes_it(qapp, monkeypatch):
    calls = _install(
        monkeypatch, hangars=[{**MOCK_HANGARS[0], "solar_system_id": 30000142}], systems={30000142: "吉他 (Jita)"}
    )

    bridge = HangarSettingsBridge()
    bridge.clearSystem()
    assert calls["system"] == [(1, None)]
    assert bridge.systemText == "未设置"
    assert bridge.hangarLabels == ["制造仓"]


# ════════════════════════════════════════════════════════════════
#  增 / 改 / 删
# ════════════════════════════════════════════════════════════════


def _stub_prompt(monkeypatch, value: str, ok: bool = True) -> None:
    monkeypatch.setattr("ui_qml.bridge.input_dialog.InputQmlDialog.get_text", lambda *a, **kw: (value, ok))


def test_new_hangar_creates_and_selects_it(qapp, monkeypatch):
    calls = _install(monkeypatch)
    hangar_list = [dict(MOCK_HANGARS[0])]

    def _create(name: str) -> int:
        calls["create"].append(name)
        hangar_list.append({**MOCK_HANGARS[0], "id": 99, "name": name})
        return 99

    monkeypatch.setattr(hsb.inventory_manager, "get_hangars", lambda: [dict(h) for h in hangar_list])
    monkeypatch.setattr(hsb.inventory_manager, "create_hangar", _create)
    _stub_prompt(monkeypatch, "  装配仓  ")

    bridge = HangarSettingsBridge()
    bridge.newHangar()
    assert calls["create"] == ["装配仓"]  # 首尾空白已 strip
    assert bridge.hangarLabels == ["制造仓", "装配仓"]
    assert bridge.currentRow == 1  # 选中新建的那个
    assert bridge.error == ""


def test_new_hangar_duplicate_name_reports_error(qapp, monkeypatch):
    """重名：`create_hangar` 返回 -1 → 走桥的错误通道提示（原版是 QMessageBox.warning）。"""
    calls = _install(monkeypatch)
    monkeypatch.setattr(hsb.inventory_manager, "create_hangar", lambda name: -1)
    _stub_prompt(monkeypatch, "制造仓")

    bridge = HangarSettingsBridge()
    bridge.newHangar()
    assert bridge.error == "机库名已存在"
    assert calls["create"] == []
    assert bridge.hangarLabels == ["制造仓"]


def test_new_hangar_cancelled_does_nothing(qapp, monkeypatch):
    calls = _install(monkeypatch)
    monkeypatch.setattr(hsb.inventory_manager, "create_hangar", lambda name: calls["create"].append(name) or 5)
    _stub_prompt(monkeypatch, "装配仓", ok=False)

    bridge = HangarSettingsBridge()
    bridge.newHangar()
    assert calls["create"] == []


def test_rename_hangar_keeps_the_row_selected(qapp, monkeypatch):
    calls = _install(monkeypatch, hangars=_two_hangars())
    _stub_prompt(monkeypatch, "新矿仓")

    bridge = HangarSettingsBridge()
    bridge.selectHangar(1)
    bridge.renameHangar()
    assert calls["rename"] == [(2, "新矿仓")]
    assert bridge.currentRow == 1
    assert bridge.hangarLabels[1] == "矿仓"  # 列表未刷新的桩数据；重点是选中行没跳回 0


def test_rename_with_unchanged_name_is_a_no_op(qapp, monkeypatch):
    """名字没改（含只点了确定）→ 不落库、不重载。"""
    calls = _install(monkeypatch)
    _stub_prompt(monkeypatch, "制造仓")

    bridge = HangarSettingsBridge()
    before = bridge.editorKey
    bridge.renameHangar()
    assert calls["rename"] == []
    assert bridge.editorKey == before


def test_delete_without_references_asks_once_then_deletes(qapp, monkeypatch):
    """无引用：确认条只问一句、不给改指下拉；确认后按原版**不带** repoint_to 调删除。"""
    calls = _install(monkeypatch)

    bridge = HangarSettingsBridge()
    bridge.requestDelete()
    assert bridge.confirmVisible is True
    assert bridge.confirmTitle == "删除机库「制造仓」及其所有物品？"
    assert bridge.confirmReferences == []
    assert bridge.showRepoint is False
    assert bridge.confirmNote == ""

    bridge.confirmDelete()
    assert calls["delete"] == [(1, "缺省")]
    assert bridge.confirmVisible is False
    assert bridge.confirmTitle == ""


def test_delete_can_be_cancelled(qapp, monkeypatch):
    calls = _install(monkeypatch)

    bridge = HangarSettingsBridge()
    bridge.requestDelete()
    bridge.cancelDelete()
    assert bridge.confirmVisible is False
    assert calls["delete"] == []


def test_delete_with_references_offers_repoint(qapp, monkeypatch):
    """有引用：列出明细 + 给出「改指到哪个机库」，确认后带 repoint_to 落库。"""
    calls = _install(monkeypatch, hangars=_two_hangars(), references=["默认材料机库", "2 条计划的材料机库"])

    bridge = HangarSettingsBridge()
    bridge.requestDelete()
    assert bridge.confirmVisible is True
    assert bridge.confirmTitle == "「制造仓」正被以下位置引用："
    assert bridge.confirmReferences == ["默认材料机库", "2 条计划的材料机库"]
    assert bridge.showRepoint is True
    assert "不可撤销" in bridge.confirmNote
    # 下拉：不修改 + 除自己以外的机库
    assert [o["label"] for o in bridge.repointOptions] == ["不修改（保留原引用）", "矿仓"]
    assert bridge.repointIndex == 0
    assert bridge.repoint_to() is None

    bridge.setRepointIndex(1)
    assert bridge.repoint_to() == 2

    bridge.confirmDelete()
    assert calls["delete"] == [(1, 2)]
    assert bridge.confirmVisible is False


def test_delete_requires_a_selected_hangar(qapp, monkeypatch):
    calls = _install(monkeypatch, hangars=[])

    bridge = HangarSettingsBridge()
    bridge.requestDelete()
    assert bridge.confirmVisible is False
    assert calls["delete"] == []


def test_confirm_delete_without_a_pending_request_is_a_no_op(qapp, monkeypatch):
    calls = _install(monkeypatch)

    bridge = HangarSettingsBridge()
    bridge.confirmDelete()
    assert calls["delete"] == []


# ════════════════════════════════════════════════════════════════
#  默认机库
# ════════════════════════════════════════════════════════════════


def test_default_rows_cover_the_four_keys(qapp, monkeypatch):
    _install(monkeypatch)

    bridge = HangarSettingsBridge()
    assert [row["key"] for row in bridge.defaultRows] == [
        "default_research_hangar_id",
        "default_mat_hangar_id",
        "default_deposit_hangar_id",
        "default_trade_hangar_id",
    ]
    row = _default_row(bridge, "default_mat_hangar_id")
    assert [o["label"] for o in row["options"]] == ["未设置", "制造仓"]
    assert row["index"] == 0  # 未配置 → 停在「未设置」


def test_stale_default_hangar_is_not_silently_cleared(qapp, monkeypatch):
    """回归：默认机库指向已删除的机库时，保存不得静默清空该设置。

    场景：机库被删/重建后 id 变化 → 下拉解析不到 → 旧实现会写回 None，
    用户感知为「默认机库设置老是丢失」。
    """
    calls = _install(monkeypatch, settings={"default_mat_hangar_id": 42})

    bridge = HangarSettingsBridge()
    row = _default_row(bridge, "default_mat_hangar_id")
    assert row["index"] == 2  # 停在保留下来那一项上，而不是回落「未设置」
    assert row["options"][2] == {"label": "（已删除的机库 #42）", "id": 42}

    bridge.accept()
    written = dict(calls["defaults"])
    assert written["default_mat_hangar_id"] == 42


def test_stale_default_row_survives_a_hangar_reload(qapp, monkeypatch):
    """新建 / 删除机库触发的重载同样要留住那个「已删除」项。"""
    calls = _install(monkeypatch, settings={"default_mat_hangar_id": 42})
    hangar_list = [dict(MOCK_HANGARS[0])]

    def _create(name: str) -> int:
        calls["create"].append(name)
        hangar_list.append({**MOCK_HANGARS[0], "id": 7, "name": name})
        return 7

    monkeypatch.setattr(hsb.inventory_manager, "get_hangars", lambda: [dict(h) for h in hangar_list])
    monkeypatch.setattr(hsb.inventory_manager, "create_hangar", _create)
    _stub_prompt(monkeypatch, "装配仓")

    bridge = HangarSettingsBridge()
    bridge.newHangar()
    row = _default_row(bridge, "default_mat_hangar_id")
    assert row["options"][-1] == {"label": "（已删除的机库 #42）", "id": 42}
    assert row["index"] == len(row["options"]) - 1


def test_default_selection_round_trips_to_settings(qapp, monkeypatch):
    calls = _install(monkeypatch, hangars=_two_hangars())

    bridge = HangarSettingsBridge()
    bridge.setDefaultIndex("default_mat_hangar_id", 2)  # 矿仓
    assert _default_row(bridge, "default_mat_hangar_id")["index"] == 2

    bridge.accept()
    assert dict(calls["defaults"]) == {
        "default_research_hangar_id": None,
        "default_mat_hangar_id": 2,
        "default_deposit_hangar_id": None,
        "default_trade_hangar_id": None,
    }


def test_default_index_out_of_range_is_ignored(qapp, monkeypatch):
    _install(monkeypatch)

    bridge = HangarSettingsBridge()
    bridge.setDefaultIndex("default_mat_hangar_id", 9)
    bridge.setDefaultIndex("不存在的键", 0)
    assert _default_row(bridge, "default_mat_hangar_id")["index"] == 0


# ════════════════════════════════════════════════════════════════
#  保存
# ════════════════════════════════════════════════════════════════


def test_accept_writes_every_hangar_not_just_the_visible_one(qapp, monkeypatch):
    """两个机库：只改了第 2 个的设施，保存时**两个**都要落库（各自的工作状态都在桥里）。"""
    calls = _install(monkeypatch, hangars=_two_hangars(), catalog=CATALOG)
    accepted: list[bool] = []

    bridge = HangarSettingsBridge()
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.selectHangar(1)
    bridge.setFacilityIndex(3)  # 索迪约
    bridge.accept()

    assert calls["config"] == [
        (1, "npc", None, []),
        (2, "sotiyo", None, []),
    ]
    assert accepted == [True]
    assert bridge.error == ""


def test_accept_writes_tax_and_rigs_of_the_edited_hangar(qapp, monkeypatch):
    cfg = {**DEFAULT_CFG, "facility_type": "raitaru"}
    calls = _install(monkeypatch, cfg=cfg, catalog=CATALOG)

    bridge = HangarSettingsBridge()
    bridge.setTaxFollowDefault(False)
    bridge.setTaxValue(0.75)
    bridge.setRigChecked(1820, True)
    bridge.accept()

    assert calls["config"] == [(1, "raitaru", 0.75, [1820])]


def test_accept_blocks_on_any_invalid_hangar(qapp, monkeypatch):
    """任一机库校验不过 → 一个库都不写、不关窗，错误行给出前 5 条违规。"""
    calls = _install(
        monkeypatch,
        hangars=_two_hangars(),
        problems=["制造类别「装备制造」最多装配 1 个改件"],
    )
    accepted: list[bool] = []

    bridge = HangarSettingsBridge()
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.accept()

    assert accepted == []
    assert calls["config"] == []
    assert bridge.error == "机库配置有误：\n制造类别「装备制造」最多装配 1 个改件"


def test_accept_clears_a_previous_error(qapp, monkeypatch):
    """先重名报错、再正常保存：错误行要被清掉（否则会一直挂在那里）。"""
    _install(monkeypatch)
    monkeypatch.setattr(hsb.inventory_manager, "create_hangar", lambda name: -1)
    _stub_prompt(monkeypatch, "制造仓")

    bridge = HangarSettingsBridge()
    bridge.newHangar()
    assert bridge.error == "机库名已存在"

    bridge.accept()
    assert bridge.error == ""


# ════════════════════════════════════════════════════════════════
#  宿主契约
# ════════════════════════════════════════════════════════════════


def test_qml_dialog_keeps_original_signature():
    """构造签名保持 `(main_window, parent=None)` —— 调用方原样可用。

    原断言是拿 Widgets 版 `HangarSettingsDialog` 逐个参数对比；那个类随批次 6.2
    删掉了，改成**直接钉住契约本身**（参数名与默认值），意图不变。
    """
    params = inspect.signature(HangarSettingsQmlDialog.__init__).parameters
    assert list(params) == ["self", "main_window", "parent"]
    assert params["parent"].default is None


# ════════════════════════════════════════════════════════════════
#  布局护栏（静态读数）
# ════════════════════════════════════════════════════════════════


def test_config_tab_left_column_pins_all_three_widths():
    """「机库配置」页左栏宽度必须 preferred / minimum / maximum **三个都钉死**。

    只写 `Layout.preferredWidth` 时，右侧编辑区会被挤成几个像素宽 ——
    看起来就像「右边栏整个没了」，而业务断言全绿、也不报任何 QML 警告，
    只有量布局才看得出来。同一坑 `LauncherWindow.qml` 的动作槽已经踩过并写了注释，
    这里是回归护栏：读源码即可，因为失败形态是布局塌缩，没有可断言的业务量。
    """
    from ui_qml.host import QML_ROOT

    text = (QML_ROOT / "dialogs" / "HangarSettingsDialog.qml").read_text(encoding="utf-8")
    for line in (
        "Layout.preferredWidth: paneWidth",
        "Layout.minimumWidth: paneWidth",
        "Layout.maximumWidth: paneWidth",
    ):
        assert line in text, f"左栏没钉死宽度（缺 `{line}`）——右侧编辑区会被挤没"

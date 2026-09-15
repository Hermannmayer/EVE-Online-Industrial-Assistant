"""「加入制造计划」对话框（`AddPlanDialog`）的业务契约测试。

只钉对外取值契约：`result_data()` 的字段、评分摘要行的格式化、各微调框的上下限。
「QML 能加载 / 无告警」那类护栏不在这里。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.ui

_SCORE = {"score": 12.34, "profit_per_run": 12345.6, "margin_pct": 7.8}


@pytest.fixture
def stub_lookups(monkeypatch):
    """角色 / 机库列表都打桩，别让对话框摸真库。"""
    from services import inventory_manager

    monkeypatch.setattr(
        inventory_manager,
        "get_hangars",
        lambda: [{"id": 1, "name": "吉他 - 装配厂"}, {"id": 2, "name": "佩尼尔 - 工业中心"}],
    )
    monkeypatch.setattr("services.char_config_resolver.get_character_list", lambda: ["守夜人", "小号"])


def test_add_plan_result_data_fields(qapp, stub_lookups):
    from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

    dlg = AddPlanDialogQmlDialog("渡鸦级", _SCORE)
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.result_data() is None, "没点确定前不该有结果"

        bridge = dlg.bridge
        bridge.setRuns(9)
        bridge.setParallels(2)
        bridge.setMe(3)
        bridge.setTe(7)
        bridge.setFacility("  自制站  ")
        bridge.accept()

        assert dlg.result_data() == {
            "runs": 9,
            "parallels": 2,
            "me": 3,
            "te": 7,
            "char": "守夜人",
            "fac": "自制站",  # 设施名两端空白被 strip 掉
        }
    finally:
        dlg.deleteLater()


def test_add_plan_score_label_formatting(qapp, stub_lookups):
    """评分摘要行 = 原 `AddPlanDialog` 里那条 QLabel 的格式。"""
    from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

    dlg = AddPlanDialogQmlDialog("渡鸦级", _SCORE)
    try:
        assert dlg.bridge.scoreLabel == "12.3 | 利润: 12,346 ISK | 利润率: 7.8%"
    finally:
        dlg.deleteLater()


def test_add_plan_score_label_defaults_on_missing_keys(qapp, stub_lookups):
    """score_result 缺字段时按 0 渲染（原版 `dict.get(..., 0)` 的语义）。"""
    from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

    dlg = AddPlanDialogQmlDialog("渡鸦级", {})
    try:
        assert dlg.bridge.scoreLabel == "0.0 | 利润: 0 ISK | 利润率: 0.0%"
    finally:
        dlg.deleteLater()


def test_add_plan_spinboxes_clamp_to_original_ranges(qapp, stub_lookups):
    """上下限沿用原 QSpinBox 的 range：流程 1-10000 / 并行 1-100 / ME 0-10 / TE 0-20。"""
    from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

    dlg = AddPlanDialogQmlDialog("渡鸦级", _SCORE)
    try:
        bridge = dlg.bridge
        bridge.setRuns(-5)
        bridge.setParallels(-5)
        bridge.setMe(-1)
        bridge.setTe(-1)
        assert (bridge.runs, bridge.parallels, bridge.me, bridge.te) == (1, 1, 0, 0)

        bridge.setRuns(99999)
        bridge.setParallels(99999)
        bridge.setMe(99)
        bridge.setTe(99)
        assert (bridge.runs, bridge.parallels, bridge.me, bridge.te) == (10000, 100, 10, 20)
    finally:
        dlg.deleteLater()


def test_add_plan_falls_back_to_main_char(qapp, stub_lookups, monkeypatch):
    """没配角色时退回 "main"（原版 `addItem("main")`）。"""
    monkeypatch.setattr("services.char_config_resolver.get_character_list", lambda: [])
    from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

    dlg = AddPlanDialogQmlDialog("渡鸦级", _SCORE)
    try:
        assert dlg.bridge.charOptions == ["main"]
        dlg.bridge.accept()
        assert (dlg.result_data() or {})["char"] == "main"
    finally:
        dlg.deleteLater()

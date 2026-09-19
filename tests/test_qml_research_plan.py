"""科研计划对话框（拷贝 / 发明 / 研究）的业务契约测试。

只钉**对外取值契约**：`result_data()` 的字段与取值规则、发明那个
`outcome_combo()` 适配器的预选行为、成功率随解码器的重算与取整。
「QML 能加载 / 无告警」那类护栏不在这里（那是 `tests/test_qml_dialogs.py` 的活）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.ui


@pytest.fixture
def stub_lookups(monkeypatch):
    """机库 / 角色列表都打桩，别让对话框摸真库。"""
    from services import inventory_manager

    monkeypatch.setattr(
        inventory_manager,
        "get_hangars",
        lambda: [
            {"id": 1, "name": "吉他 - 装配厂"},
            {"id": 2, "name": "佩尼尔 - 工业中心"},
        ],
    )
    monkeypatch.setattr(inventory_manager, "get_hangar_system_id", lambda hangar_id: 30000142 if hangar_id else None)
    monkeypatch.setattr("services.char_config_resolver.get_character_list", lambda: ["守夜人", "小号"])


def _outcomes() -> list[dict]:
    return [
        {"blueprint_type_id": 3001, "name": "渡鸦级", "base_probability": 0.34},
        {"blueprint_type_id": 3002, "name": "乌鸦级", "base_probability": 0.4},
    ]


def _invention_dialog():
    from ui_qml.bridge.research_plan_bridge import InventionPlanDialogQmlDialog

    return InventionPlanDialogQmlDialog(
        "渡鸦级蓝图",
        outcomes=_outcomes(),
        base_runs_by_outcome={3001: 10, 3002: 20},
        default_probability={3001: 0.34, 3002: 0.4},
    )


# ══════════════════════════════════════════════════════════════
#  拷贝
# ══════════════════════════════════════════════════════════════


def test_copy_plan_merges_common_and_specific_fields(qapp, stub_lookups):
    from ui_qml.bridge.research_plan_bridge import CopyPlanDialogQmlDialog

    dlg = CopyPlanDialogQmlDialog("渡鸦级蓝图", max_production_limit=10)
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.result_data() is None, "没点确定前不该有结果"

        bridge = dlg.bridge
        bridge.setCopies(3)
        bridge.setRunsPerCopy(7)
        bridge.setMatIndex(1)
        bridge.setOutIndex(2)
        bridge.accept()

        assert dlg.result_data() == {
            "activity": "copying",
            "char_name": "守夜人",
            "mat_hangar_id": 1,
            "deposit_hangar_id": 2,
            "solar_system_id": 30000142,
            "copies": 3,
            "runs_per_copy": 7,
        }
    finally:
        dlg.deleteLater()


def test_copy_plan_clamps_copies_and_runs(qapp, stub_lookups):
    """份数上限 1000、每份流程上限 = 蓝图拷贝上限（原 QSpinBox 的 range 语义）。"""
    from ui_qml.bridge.research_plan_bridge import CopyPlanDialogQmlDialog

    dlg = CopyPlanDialogQmlDialog("渡鸦级蓝图", max_production_limit=10)
    try:
        bridge = dlg.bridge
        assert bridge.runsLimit == 10
        assert bridge.copies == 1 and bridge.runsPerCopy == 10, "原版默认每份流程取满上限"

        bridge.setCopies(0)
        bridge.setRunsPerCopy(0)
        assert bridge.copies == 1 and bridge.runsPerCopy == 1

        bridge.setCopies(99999)
        bridge.setRunsPerCopy(99999)
        assert bridge.copies == 1000 and bridge.runsPerCopy == 10
    finally:
        dlg.deleteLater()


def test_copy_plan_mat_hangar_default_from_settings(qapp, stub_lookups, monkeypatch):
    """默认材料机库取自 settings；未设的输出机库落到「未设置」→ None。"""
    monkeypatch.setattr(
        "services.user_settings.get_default_hangar_id",
        lambda key: 2 if key == "default_mat_hangar_id" else None,
    )
    from ui_qml.bridge.research_plan_bridge import CopyPlanDialogQmlDialog

    dlg = CopyPlanDialogQmlDialog("渡鸦级蓝图", max_production_limit=5)
    try:
        bridge = dlg.bridge
        assert bridge.matIndex == 2, "索引 0 是「未设置」，命中 id=2 应落在索引 2"
        assert bridge.outIndex == 0
        bridge.accept()
        data = dlg.result_data() or {}
        assert data["mat_hangar_id"] == 2
        assert data["deposit_hangar_id"] is None, "未设置（-1）必须落成 None"
    finally:
        dlg.deleteLater()


# ══════════════════════════════════════════════════════════════
#  发明
# ══════════════════════════════════════════════════════════════


def test_outcome_combo_adapter_preselects_by_blueprint(qapp, stub_lookups):
    """复刻调用点的写法：按右键选中的蓝图在产物下拉里预选（`count/itemData/setCurrentIndex`）。"""
    dlg = _invention_dialog()
    try:
        combo = dlg.outcome_combo()
        assert combo.count() == 2
        assert combo.itemData(0)["blueprint_type_id"] == 3001

        target = 3002
        for i in range(combo.count()):
            outcome = combo.itemData(i) or {}
            if int(outcome.get("blueprint_type_id") or 0) == target:
                combo.setCurrentIndex(i)
                break

        dlg.bridge.accept()
        data = dlg.result_data() or {}
        assert data["product_blueprint_type_id"] == 3002
        assert data["product_name"] == "乌鸦级"
    finally:
        dlg.deleteLater()


def test_invention_probability_follows_decryptor(qapp, stub_lookups):
    """换解码器重算成功率与产出流程数。"""
    dlg = _invention_dialog()
    try:
        bridge = dlg.bridge
        assert bridge.rate == 34.0, "基础成功率 0.34 → 34.0%"
        assert bridge.rateHint == ("SDE 基础成功率 34%（未取到角色技能） → 34.0%；成功一次产出 10 流程的 T2 蓝图拷贝")

        # 解码器索引 2 = 34202「获取装置解码器」（×1.8，流程 +4）
        bridge.setDecryptorIndex(2)
        assert bridge.rate == 61.2
        assert "解码器 1.8" in bridge.rateHint
        assert "成功一次产出 14 流程的 T2 蓝图拷贝" in bridge.rateHint

        bridge.accept()
        data = dlg.result_data() or {}
        assert data["decryptor_type_id"] == 34202
        # 没手改过 → 落 NULL，评分链按当前角色的技能现算（而不是写死对话框算的值）
        assert data["success_rate"] is None
    finally:
        dlg.deleteLater()


def test_invention_runs_times_parallels_drive_summary(qapp, stub_lookups):
    """流程 × 并行 = 总尝试：落库两个值，预期结果块按乘积算。"""
    dlg = _invention_dialog()
    try:
        bridge = dlg.bridge
        bridge.setAttempts(3)
        bridge.setParallels(2)
        bridge.accept()
        data = dlg.result_data() or {}
        assert data["attempts"] == 3
        assert data["parallels"] == 2

        summary = bridge.expectedSummary
        assert "总尝试次数：3 × 2 = 6 次" in summary
        assert "需要输入：2 张 T1 蓝图拷贝，每张至少 3 流程" in summary
        assert "单次成功产出：10 流程的 T2 蓝图拷贝（ME2/TE4）" in summary
    finally:
        dlg.deleteLater()


def test_invention_manual_rate_overrides_computed(qapp, stub_lookups):
    """手改成功率后，落库用的是手改值（原版 blockSignals 后读 value() 的等价物）。"""
    dlg = _invention_dialog()
    try:
        dlg.bridge.setRate(55.5)
        dlg.bridge.setAttempts(4)
        dlg.bridge.accept()
        data = dlg.result_data() or {}
        assert data["success_rate"] == 0.555
        assert data["attempts"] == 4
        assert data["activity"] == "invention"
    finally:
        dlg.deleteLater()


def test_invention_labels_are_preformatted(qapp, stub_lookups):
    """下拉标签的格式化留在 Python 侧（可单测），QML 只显示字符串。"""
    dlg = _invention_dialog()
    try:
        bridge = dlg.bridge
        assert bridge.outcomeLabels[0] == "渡鸦级（基础成功率 34%）"
        assert bridge.outcomeSummary == "由「渡鸦级蓝图」发明，共 2 种可能"
        assert bridge.decryptorLabels[0] == "不使用"
        assert bridge.decryptorLabels[1] == "加速装置解码器（成功率 ×1.2，流程 +1）"
    finally:
        dlg.deleteLater()


# ══════════════════════════════════════════════════════════════
#  效率研究
# ══════════════════════════════════════════════════════════════


def test_research_plan_activity_and_target_level(qapp, stub_lookups):
    from ui_qml.bridge.research_plan_bridge import ResearchPlanDialogQmlDialog

    dlg = ResearchPlanDialogQmlDialog("渡鸦级蓝图")
    try:
        bridge = dlg.bridge
        assert bridge.kindOptions == ["材料效率（ME，降低材料需求）", "时间效率（TE，缩短制造时间）"]

        bridge.setKindIndex(1)
        bridge.setLevel(5)
        bridge.accept()
        data = dlg.result_data() or {}
        assert data["activity"] == "researching_time_efficiency"
        assert data["target_level"] == 5
    finally:
        dlg.deleteLater()


def test_research_plan_defaults_to_material_efficiency(qapp, stub_lookups):
    from ui_qml.bridge.research_plan_bridge import ResearchPlanDialogQmlDialog

    dlg = ResearchPlanDialogQmlDialog("渡鸦级蓝图")
    try:
        bridge = dlg.bridge
        bridge.accept()
        data = dlg.result_data() or {}
        assert data["activity"] == "researching_material_efficiency"
        assert data["target_level"] == 1
        assert data["char_name"] == "守夜人"
    finally:
        dlg.deleteLater()

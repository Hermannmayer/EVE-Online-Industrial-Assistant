"""QML 对话框的运行时护栏（阶段 4）。

阶段 4 要把约 44 个对话框逐个迁到 QML，这里放**每个对话框都要过一遍**的两条：
  - `QmlDialog` 能加载（`ok()`）；
  - 加载 + 布局不给 Qt 刷告警（`textRole` / 位置绑定 / import 缺失这几类坑
    在页面迁移时都真实踩过）。

各对话框自己的业务契约仍写在各自的测试文件里（如
`tests/test_batch_edit_preserves_runs.py`），这里只管「宿主是否健康」。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, QtMsgType, Signal, qInstallMessageHandler
from PySide6.QtGui import qAlpha

import ui_pyside6.theme as theme

pytestmark = pytest.mark.ui


def _spin(ms: int = 120) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _assert_loads_and_quiet(make_dialog, label: str) -> None:
    """共用的两条护栏。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        dialog = make_dialog()
        try:
            assert dialog.ok(), f"{label} 的 QML 没加载起来：" + "; ".join(str(e) for e in dialog._host.errors())
            dialog.resize(520, 460)
            _spin(250)
        finally:
            dialog.deleteLater()
            _spin(60)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, f"{label} 产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))


@pytest.fixture
def plan_edit_factory(qapp, monkeypatch):
    """「编辑生产计划」对话框的工厂（机库与角色列表都打桩）。"""
    from services import inventory_manager

    monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
    monkeypatch.setattr("ui_pyside6.views.char_settings_view.services_get_character_list", lambda: ["甲"])

    from ui_qml.bridge.plan_edit_bridge import PlanEditQmlDialog

    def _make(plan: dict | None = None, **kwargs):
        return PlanEditQmlDialog(None, plan or {"product_name": "渡鸦级", "runs": 3, "parallels": 2}, **kwargs)

    return _make


def test_plan_edit_dialog_loads_without_warnings(plan_edit_factory):
    _assert_loads_and_quiet(plan_edit_factory, "编辑生产计划")


def test_plan_edit_dialog_batch_mode_loads(plan_edit_factory):
    _assert_loads_and_quiet(
        lambda: plan_edit_factory({"_selected_rows": [0, 1], "runs": 5, "parallels": 1}, batch_mode=True, row_count=2),
        "批量编辑生产计划",
    )


def test_plan_edit_labels_follow_the_activity_kind(plan_edit_factory):
    """科研行的 runs 语义不同：标签随活动类型走（与 Widgets 版逐条对齐）。"""
    dialog = plan_edit_factory({"product_name": "x", "activity": "invention"})
    try:
        bridge = dialog.bridge
        assert bridge.runsLabel == "尝试次数"
        assert bridge.parallelLabel == "并行数"
    finally:
        dialog.deleteLater()

    copy_dialog = plan_edit_factory({"product_name": "x", "activity": "copying"})
    try:
        assert copy_dialog.bridge.parallelLabel == "产出份数"
    finally:
        copy_dialog.deleteLater()


def test_plan_edit_dialog_title_comes_from_the_bridge(plan_edit_factory):
    dialog = plan_edit_factory({"product_name": "渡鸦级"})
    try:
        assert "渡鸦级" in dialog.windowTitle()
    finally:
        dialog.deleteLater()


@pytest.fixture
def partial_start_factory(qapp):
    from ui_qml.bridge.partial_start_bridge import PartialStartQmlDialog

    return lambda total=4: PartialStartQmlDialog("渡鸦级", total)


@pytest.fixture
def invention_factory(qapp):
    from ui_qml.bridge.invention_outcome_bridge import InventionOutcomeQmlDialog

    return lambda **kw: InventionOutcomeQmlDialog(
        **{"plan_name": "渡鸦级", "expected_runs": 10, "attempts": 3, "runs_per_bpc": 2, **kw}
    )


@pytest.fixture
def complete_plans_factory(qapp, monkeypatch):
    monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
    from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog

    return lambda: CompletePlansQmlDialog(
        [{"id": 1, "product_name": "渡鸦级", "runs": 2, "parallels": 3, "deposit_hangar_id": None}],
        [{"id": 1, "name": "矿仓"}],
        None,
    )


def test_partial_start_dialog_loads_without_warnings(partial_start_factory):
    _assert_loads_and_quiet(partial_start_factory, "部分启动")


def test_invention_outcome_dialog_loads_without_warnings(invention_factory):
    _assert_loads_and_quiet(invention_factory, "发明结果回填")


def test_complete_plans_dialog_loads_without_warnings(complete_plans_factory):
    _assert_loads_and_quiet(complete_plans_factory, "下线确认")


def test_invention_hint_follows_the_value(invention_factory):
    """提示三种状态：失败 / 与期望差太多 / 正常 —— 与 Widgets 版同一判据。"""
    dialog = invention_factory()
    try:
        bridge = dialog.bridge
        assert bridge.actualRuns == 10
        assert "成功后产出 10 流程" in bridge.hintText

        bridge.markFailed()
        assert bridge.actualRuns == 0
        assert "发明失败" in bridge.hintText

        bridge.setActualRuns(2)  # 与期望 10 差 8 > max(1, 10//5)
        assert "相差较大" in bridge.hintText
    finally:
        dialog.deleteLater()


def test_invention_outcome_is_none_until_accepted(invention_factory):
    dialog = invention_factory()
    try:
        assert dialog.outcome() is None
        dialog.bridge.setActualRuns(4)
        dialog.bridge.accept()
        assert dialog.outcome() == 4
    finally:
        dialog.deleteLater()


@pytest.fixture
def output_factory(qapp, monkeypatch):
    import services.industry_dialog_queries as q

    monkeypatch.setattr(
        q,
        "get_output_summary",
        lambda db: [
            {
                "plan_name": "渡鸦级",
                "product_type_id": 2001,
                "total_qty": 10,
                "plan_value": 1_500_000.0,
                "material_cost": 1_000_000.0,
                "profit": 500_000.0,
                "margin_pct": 50.0,
                "overflow_text": "—",
                "status": "ready",
                "has_overflow": False,
            }
        ],
    )
    from ui_qml.bridge.output_dialog_bridge import OutputSummaryQmlDialog

    return OutputSummaryQmlDialog


@pytest.fixture
def char_usage_factory(qapp, monkeypatch):
    import services.industry_dialog_queries as q

    monkeypatch.setattr(q, "get_character_usage", lambda db: [("甲", 5, "渡鸦级 x2"), ("乙", 1, "—")])
    from ui_qml.bridge.char_usage_bridge import CharacterUsageQmlDialog

    return CharacterUsageQmlDialog


@pytest.fixture
def materials_factory(qapp, monkeypatch):
    import services.industry_dialog_queries as q

    monkeypatch.setattr(
        q,
        "get_materials_summary",
        lambda db: {
            "materials": {34: {"name": "三钛合金", "total_qty": 1000, "_level": 0, "volume": 0.01}},
            "inventory": {34: 200},
            "prices": {34: {"sell": 5.0}},
        },
    )
    from ui_qml.bridge.materials_dialog_bridge import MaterialsSummaryQmlDialog

    return MaterialsSummaryQmlDialog


def test_output_summary_dialog_loads_without_warnings(output_factory):
    _assert_loads_and_quiet(output_factory, "产出总表")


def test_char_usage_dialog_loads_without_warnings(char_usage_factory):
    _assert_loads_and_quiet(char_usage_factory, "人物占用情况")


def test_materials_dialog_loads_without_warnings(materials_factory):
    _assert_loads_and_quiet(materials_factory, "填料总表")


def test_output_summary_colours_profit_and_status(output_factory):
    """利润按正负染色、状态按语义染色、溢出标橙 —— 与 Widgets 版同一组规则。"""
    dialog = output_factory()
    try:
        cells = dialog.bridge.rows[0]["cells"]
        assert cells[5]["color"] != ""  # 利润为正 → 绿
        assert cells[8]["color"] != ""  # ready → 橙
        assert "1.50M" in cells[3]["text"]  # ISK 缩写
        assert "1 个计划" in dialog.bridge.statusText
    finally:
        dialog.deleteLater()


def test_char_usage_colours_by_load(qapp, monkeypatch):
    """活跃计划数越多越警示（≥5 红、≥3 黄、其余绿）。"""
    import services.industry_dialog_queries as q

    monkeypatch.setattr(q, "get_character_usage", lambda db: [("甲", 5, ""), ("乙", 3, ""), ("丙", 1, "")])
    from ui_qml.bridge.char_usage_bridge import CharacterUsageQmlDialog, _load_token

    # 阈值规则本身（与主题具体色值解耦）
    assert _load_token(5) == "ACCENT_RED"
    assert _load_token(3) == "ACCENT_YELLOW"
    assert _load_token(1) == "ACCENT_GREEN"

    dialog = CharacterUsageQmlDialog()
    try:
        colors = [row["cells"][1]["color"] for row in dialog.bridge.rows]
        assert all(colors), "每行都应有颜色（token 解析不出来会得到空串）"
        assert "3 个角色" in dialog.bridge.statusText
        assert "9 个活跃计划" in dialog.bridge.statusText
    finally:
        dialog.deleteLater()


def test_materials_copy_row_and_copy_all(materials_factory):
    """行内复制「名称 + 需购量」，一键复制走 `名称* 数量`（与原版同一格式）。"""
    from PySide6.QtWidgets import QApplication

    dialog = materials_factory()
    try:
        bridge = dialog.bridge
        assert bridge.hasActionColumn is True
        assert bridge.topActionText == "一键复制全部"
        bridge.copyRow(0)
        assert QApplication.clipboard().text() == "三钛合金\t800"
        assert "已复制" in bridge.error

        bridge.topAction()
        assert QApplication.clipboard().text() == "三钛合金* 800"
        assert "1 种待采购材料" in bridge.error
    finally:
        dialog.deleteLater()


def test_materials_reports_all_ready(materials_factory, monkeypatch):
    """全部到位时一键复制只给提示，不改剪贴板。"""
    import services.industry_dialog_queries as q

    monkeypatch.setattr(
        q,
        "get_materials_summary",
        lambda db: {
            "materials": {34: {"name": "三钛合金", "total_qty": 100, "_level": 0, "volume": 0.01}},
            "inventory": {34: 500},
            "prices": {34: {"sell": 5.0}},
        },
    )
    from ui_qml.bridge.materials_dialog_bridge import MaterialsSummaryQmlDialog

    dialog = MaterialsSummaryQmlDialog()
    try:
        dialog.bridge.topAction()
        assert "无需采购" in dialog.bridge.error
    finally:
        dialog.deleteLater()


class _BrokenDb:
    """连不上的库 —— 用来验证对话框在取数失败时仍能打开并给出说明行。"""

    def connect(self, *args: object) -> object:
        raise RuntimeError("no db in tests")


def test_research_cost_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.research_cost_bridge import ResearchCostQmlDialog

    _assert_loads_and_quiet(
        lambda: ResearchCostQmlDialog(_BrokenDb(), 691, "渡鸦级蓝图"),
        "研究分析",
    )


def test_research_cost_reports_failure_instead_of_crashing():
    """取数失败时给一行说明，而不是把异常抛给调用方（原 Widgets 版会直接崩）。"""
    from ui_qml.bridge.research_cost_bridge import ResearchCostBridge

    bridge = ResearchCostBridge(_BrokenDb(), 691, "渡鸦级蓝图")
    bridge.reload()
    assert len(bridge.fields) == 1
    assert bridge.fields[0]["label"] == "说明"
    assert "读取失败" in bridge.fields[0]["value"]


def test_research_cost_formats_duration():
    from ui_qml.bridge.research_cost_bridge import _fmt_duration

    assert _fmt_duration(0) == "—"
    assert _fmt_duration(90) == "1m"
    assert _fmt_duration(3700) == "1h1m"
    assert _fmt_duration(90000) == "1d1h0m"


@pytest.fixture
def blueprint_requirements_factory(qapp, monkeypatch):
    import services.industry_dialog_queries as q

    monkeypatch.setattr(
        q,
        "get_blueprint_requirements",
        lambda db: {
            "status": "ok",
            "needed": {
                1001: {"name": "渡鸦级蓝图", "needed_runs": 20},
                1002: {"name": "三钛合金蓝图", "needed_runs": 5},
                1003: {"name": "缺少的蓝图", "needed_runs": 1},
            },
            "bp_inv": {
                1001: {"is_bpo": True, "best_me": 10, "best_te": 20},
                1002: {"available_runs": 3, "best_me": 0, "best_te": 0},
            },
        },
    )
    from ui_qml.bridge.blueprint_dialog_bridge import BlueprintRequirementsQmlDialog

    return BlueprintRequirementsQmlDialog


def test_blueprint_requirements_dialog_loads_without_warnings(blueprint_requirements_factory):
    _assert_loads_and_quiet(blueprint_requirements_factory, "所需蓝图清单")


def test_blueprint_requirements_three_state_status(blueprint_requirements_factory):
    """三色状态：BPO 无限=足够、可用不足=不足、无库存=缺少；状态行给出三种计数。"""
    dialog = blueprint_requirements_factory()
    try:
        bridge = dialog.bridge
        by_name = {row["cells"][0]["text"]: row["cells"] for row in bridge.rows}
        assert by_name["渡鸦级蓝图"][1]["text"] == "BPO"
        assert by_name["渡鸦级蓝图"][5]["text"] == "无限"
        assert by_name["渡鸦级蓝图"][6]["text"] == "足够"
        assert by_name["三钛合金蓝图"][6]["text"] == "不足"
        assert by_name["缺少的蓝图"][6]["text"] == "缺少"
        # 三种状态各自的颜色互不相同
        colors = {by_name[n][6]["color"] for n in by_name}
        assert len(colors) == 3
        assert "共 3 类蓝图" in bridge.statusText
        assert "足够 1 种" in bridge.statusText
        assert "不足 1 种" in bridge.statusText
        assert "缺少 1 种" in bridge.statusText
    finally:
        dialog.deleteLater()


def test_blueprint_requirements_empty_states(monkeypatch, qapp):
    """没有活跃计划 / 没有蓝图需求时只给状态文案，不建表。"""
    import services.industry_dialog_queries as q
    from ui_qml.bridge.blueprint_dialog_bridge import BlueprintRequirementsQmlDialog

    for status, hint in (("no_active", "没有活跃计划"), ("no_needed", "没有蓝图需求")):
        monkeypatch.setattr(q, "get_blueprint_requirements", lambda db, s=status: {"status": s})
        dialog = BlueprintRequirementsQmlDialog()
        try:
            assert dialog.bridge.rowCount == 0
            assert dialog.bridge.statusText == hint
        finally:
            dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  子项并行配置 / 子项大规模产线并行（阶段 4-4 的子项部分）
# ════════════════════════════════════════════════════════════════


class _DialogFactory:
    """造对话框，并握住它的桥需要的桩（如落库用的 plan_repo）。

    用类而不是 lambda：测试要断言写入内容，lambda 上挂属性过不了 mypy。
    """

    def __init__(self, qml_cls, plans, **stubs):
        self.qml_cls = qml_cls
        self.plans = plans
        for name, value in stubs.items():
            setattr(self, name, value)

    def __call__(self):
        return self.qml_cls(self.plans)


def _build_parallel_ref(db_manager):
    """并行类对话框要的最小 ref 库：件名 / 蓝图产出 / 蓝图工时。"""
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1001,'碳纤维','Carbon Fiber')")
        conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven')")
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',7200)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',3600)")


def _parallel_plans() -> list[dict]:
    """一个母项 + 一个子项（子项带 v12 的 demand 列）。"""
    return [
        {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
        {
            "id": 11,
            "product_type_id": 1001,
            "sub_level": 1,
            "runs": 1,
            "parallels": 1,
            "demand": 2,
            "blueprint_type_id": 3002,
        },
    ]


@pytest.fixture
def child_parallel_factory(db_manager, monkeypatch, qapp):
    from types import SimpleNamespace

    from ui_qml.bridge.child_parallel_bridge import ChildParallelQmlDialog

    _build_parallel_ref(db_manager)
    monkeypatch.setattr(
        "ui_qml.bridge.child_parallel_bridge.get_container",
        lambda: SimpleNamespace(db=db_manager, plan_repo=MagicMock()),
    )
    return _DialogFactory(ChildParallelQmlDialog, _parallel_plans())


@pytest.fixture
def mass_parallel_factory(db_manager, monkeypatch, qapp):
    from types import SimpleNamespace

    from ui_qml.bridge.mass_parallel_bridge import MassParallelQmlDialog

    _build_parallel_ref(db_manager)
    repo = MagicMock()
    monkeypatch.setattr(
        "ui_qml.bridge.mass_parallel_bridge.get_container",
        lambda: SimpleNamespace(db=db_manager, plan_repo=repo),
    )
    return _DialogFactory(MassParallelQmlDialog, _parallel_plans(), repo=repo)


def test_child_parallel_dialog_loads_without_warnings(child_parallel_factory):
    _assert_loads_and_quiet(child_parallel_factory, "子项并行配置")


def test_mass_parallel_dialog_loads_without_warnings(mass_parallel_factory):
    _assert_loads_and_quiet(mass_parallel_factory, "子项大规模产线并行")


def test_mass_parallel_preview_then_apply(mass_parallel_factory):
    """算预览 → 出六列表 → 应用只写 parallels（runs 不动）。"""
    dialog = mass_parallel_factory()
    try:
        bridge = dialog.bridge
        assert bridge.hasPreview is False
        # 没算过预览就点「确认应用」→ 一句提示，不落库
        bridge.accept()
        assert bridge.error != ""
        assert mass_parallel_factory.repo.update_batch.call_count == 0

        bridge.setParamValue(10)
        bridge.computePreview()

        assert bridge.hasPreview is True
        assert len(bridge.rows) == 1
        cells = bridge.rows[0]["cells"]
        assert cells[0]["text"] == "碳纤维"
        assert cells[1]["text"] == "2"  # 母项需求
        assert cells[3]["text"] == "10"  # 调整后并行 = 单子项吃掉全部 9 条余量 + 1
        assert cells[5]["text"] == "✓"
        assert bridge.anyShort is False

        bridge.accept()
        assert mass_parallel_factory.repo.update_batch.call_args[0][0] == [(11, {"parallels": 10})]
    finally:
        dialog.deleteLater()


def test_mass_parallel_mode_switch_resets_param(mass_parallel_factory):
    """换模式：上限与单位跟着变，参数回到 10（与 Widgets 版一致）。"""
    dialog = mass_parallel_factory()
    try:
        bridge = dialog.bridge
        assert bridge.paramSuffix == " 条产线"
        assert bridge.paramMax == 1000

        bridge.setParamValue(999)
        bridge.setModeIndex(1)
        assert bridge.paramValue == 10
        assert bridge.paramSuffix == " 天"
        assert bridge.paramMax == 3650
        assert bridge.hasPreview is False  # 换模式清掉旧预览
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  绑定库存蓝图（阶段 4）
# ════════════════════════════════════════════════════════════════


class _PickerHarness:
    """造「绑定库存蓝图」对话框，并握住写库与占用状态两处桩。

    选项固定 4 条，覆盖四种行态：
      0) 自己已绑定（默认勾选、可勾）
      1) 原图（BPO，可用流程视为无限）
      2) 被其他活跃计划占用（禁勾）
      3) 流程不足（黄字提示但仍可勾）
    """

    OPTIONS = [
        {"id": 1, "is_bpo": False, "available_runs": 10, "me_level": 10, "te_level": 20, "hangar_name": "组件仓"},
        {"id": 2, "is_bpo": True, "me_level": 0, "te_level": 0, "hangar_name": "矿仓"},
        {"id": 3, "is_bpo": False, "available_runs": 99, "me_level": 0, "te_level": 0, "hangar_name": "矿仓"},
        {"id": 4, "is_bpo": False, "available_runs": 1, "me_level": 0, "te_level": 0, "hangar_name": ""},
    ]

    def __init__(self, qml_cls, state, writes, bind_ok=True):
        self.qml_cls = qml_cls
        self.state = state
        self.writes = writes
        self.bind_ok = bind_ok

    def __call__(self):
        return self.qml_cls({"id": 7, "product_type_id": 1001, "product_name": "碳纤维", "runs": 3, "parallels": 2})


@pytest.fixture
def blueprint_picker_factory(qapp, monkeypatch):
    from types import SimpleNamespace

    import services.industry_dialog_queries as q
    import services.plan_execution as pe

    state = {"bound": [1], "need": 2, "runs": 3}
    writes: list[list[int]] = []

    monkeypatch.setattr(pe, "get_plan_binding_state", lambda plan_id: dict(state))
    monkeypatch.setattr(pe, "get_occupied_blueprint_ids", lambda db, exclude_plan_id=None: {3})
    monkeypatch.setattr(
        q, "get_blueprint_picker_data", lambda db, pid: (3002, [dict(o) for o in _PickerHarness.OPTIONS])
    )
    monkeypatch.setattr("ui_qml.bridge.blueprint_picker_bridge.get_container", lambda: SimpleNamespace(db=None))

    def _bind(plan_id: int, ids: list[int]) -> bool:
        writes.append(list(ids))
        state["bound"] = list(ids)
        return True

    monkeypatch.setattr(pe, "bind_blueprints", _bind)

    from ui_qml.bridge.blueprint_picker_bridge import BlueprintPickerQmlDialog

    return _PickerHarness(BlueprintPickerQmlDialog, state, writes)


def test_blueprint_picker_dialog_loads_without_warnings(blueprint_picker_factory):
    _assert_loads_and_quiet(blueprint_picker_factory, "绑定库存蓝图")


def test_picker_row_states(blueprint_picker_factory):
    """四种行态：自己绑定可勾、原图无限、占用禁勾、流程不足可勾但标黄。"""
    dialog = blueprint_picker_factory()
    try:
        rows = dialog.bridge.rows
        assert len(rows) == 4

        assert rows[0]["checked"] is True and rows[0]["checkable"] is True
        assert rows[0]["cells"][0]["text"] == "拷贝"
        assert rows[0]["cells"][1]["text"] == "10"  # ME
        assert rows[0]["cells"][4]["text"] == "组件仓"

        assert rows[1]["cells"][0]["text"] == "原图"
        assert rows[1]["cells"][3]["text"] == "无限"

        assert rows[2]["checkable"] is False
        assert rows[2]["disabled"] is True
        assert rows[2]["cells"][5]["text"] == "占用中"

        assert rows[3]["checkable"] is True
        assert rows[3]["cells"][5]["text"] == "流程不足"
    finally:
        dialog.deleteLater()


def test_picker_writes_through_and_caps_at_need(blueprint_picker_factory):
    """勾选即落库；满额后再勾回滚并给橙色提示，且不再写库。"""
    dialog = blueprint_picker_factory()
    try:
        bridge = dialog.bridge
        # 构建期已按 DB 现状落一次库（自己绑定 1 张，需 2 张）
        assert blueprint_picker_factory.writes[-1] == [1]
        assert bridge.selectedBlueprintIds == [1]
        assert bridge.statusToken == "ACCENT_RED"
        assert "还差 1 张" in bridge.statusText

        bridge.toggle(1, True)
        assert blueprint_picker_factory.writes[-1] == [1, 2]
        assert bridge.statusToken == "GREEN"
        assert "已选 2 / 需 2 张" in bridge.statusText

        writes_before = len(blueprint_picker_factory.writes)
        bridge.toggle(3, True)  # 第 3 张 → 超需，回滚
        assert bridge.rows[3]["checked"] is False
        assert bridge.statusToken == "ACCENT_ORANGE"
        assert "按需取前 2 张" in bridge.statusText
        assert len(blueprint_picker_factory.writes) == writes_before, "回滚不该再写库"
    finally:
        dialog.deleteLater()


def test_picker_batch_actions_and_accept(blueprint_picker_factory):
    """右键批量：仅保留所选；绑定不足时「完成」要先本地确认一次。"""
    dialog = blueprint_picker_factory()
    try:
        bridge = dialog.bridge
        bridge.checkRows([1, 3])  # 批量勾选（占用行 2 会被 _bulk 跳过）
        assert bridge.rows[1]["checked"] is True
        assert bridge.rows[3]["checked"] is True
        assert bridge.rows[2]["checked"] is False

        bridge.onlyKeep([0])  # 参数是**行号**（QML 的 selRows），返回值才是蓝图 id
        assert bridge.selectedBlueprintIds == [1]
        assert bridge.rows[1]["checked"] is False
        assert bridge.rows[3]["checked"] is False

        accepted: list[bool] = []
        bridge.accepted.connect(lambda: accepted.append(True))
        bridge.accept()  # 1 < 需 2 → 只提示，不关闭
        assert accepted == []
        assert "仍要关闭请再点一次" in bridge.error
        bridge.accept()
        assert accepted == [True]
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  查看核算（成本明细，阶段 4）
# ════════════════════════════════════════════════════════════════


def _breakdown_metrics(activity: str = "manufacturing") -> dict:
    """一条算得出来的指标结果（材料两种：单件不受 ME 影响 + 受 ME 影响）。"""
    return {
        "material_cost": 1_234.5,
        "profit": 500.0,
        "margin": 12.5,
        "score": 42.0,
        "iskph": 3_000_000.0,
        "calculated_time": 7200.0,
        "daily_output": 8.0,
        "status": "",
        "structure_mat_saving": 1.0,
        "materials": [
            {"name": "碳纤维", "base_qty": 1, "wastefactor": 10, "type_id": 1001, "unit_price": 500.0},
            {"name": "三钛合金", "base_qty": 100, "wastefactor": 10, "type_id": 34, "unit_price": 5.0},
        ],
        "breakdown": {
            "eiv": 1_000.0,
            "system_cost": 10.0,
            "installation_fee": 20.0,
            "facility_tax": 1.5,
            "scc_surcharge": 4.0,
            "broker_init": 3.0,
            "broker_relist": 0.5,
            "sales_tax": 2.0,
            "revenue": 2_000.0,
            "sci": 0.01,
            "activity": activity,
            "research_cost": 7.0,
            "copies": 3,
            "runs_per_copy": 10,
            "max_production_limit": 100,
            "per_copy_cost": 1_200.0,
        },
    }


@pytest.fixture
def cost_breakdown_factory(qapp, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    svc = MagicMock()
    svc.calculate_plan_metrics.side_effect = lambda plan, cfg, **kw: _breakdown_metrics(
        plan.get("_activity", "manufacturing")
    )
    monkeypatch.setattr(
        "ui_qml.bridge.cost_breakdown_bridge.get_container",
        lambda: SimpleNamespace(db=MagicMock(), scoring_service=lambda: svc),
    )
    from ui_qml.bridge.cost_breakdown_bridge import CostBreakdownQmlDialog

    def _make(activity: str = "manufacturing"):
        plan = {"product_type_id": 2001, "product_name": "渡鸦级", "runs": 2, "parallels": 1, "_activity": activity}
        return CostBreakdownQmlDialog(plan, char_config={})

    return _make


def test_cost_breakdown_dialog_loads_without_warnings(cost_breakdown_factory):
    _assert_loads_and_quiet(cost_breakdown_factory, "查看核算")


def test_cost_breakdown_renders_materials_and_summary(cost_breakdown_factory):
    """材料两行 + 三块明细；作业费与市场费用合计加粗，利润按正负染色。"""
    dialog = cost_breakdown_factory()
    try:
        bridge = dialog.bridge
        assert "评分 42.0" in bridge.statusText
        assert "利润率 12.5%" in bridge.statusText
        assert len(bridge.materialRows) == 2
        assert bridge.materialRows[0]["cells"][0]["text"] == "碳纤维"
        assert bridge.materialRows[0]["cells"][1]["text"] == "1"
        assert bridge.materialRows[1]["cells"][1]["text"] == "100"

        job = {f["label"]: f for f in bridge.jobFields}
        assert job["制造作业费:"]["strong"] is True
        assert job["制造作业费:"]["value"] == "40"  # 20 × 2 总流程
        assert "SCI=1.0000%" in job["系统成本 (SCI × EIV):"]["value"]
        # 制造行只有一行「拷贝/发明研究成本」，没有科研专属那三行
        assert "发明成功率:" not in job
        assert job["拷贝/发明研究成本:"]["value"] == "14"  # 7 × 2

        mkt = {f["label"]: f for f in bridge.marketFields}
        assert mkt["市场费用合计:"]["strong"] is True
        assert mkt["市场费用合计:"]["value"] == "11"  # (3 + 0.5 + 2) × 2

        summ = {f["label"]: f for f in bridge.summaryFields}
        assert summ["利润:"]["value"] == "500"
        assert summ["利润:"]["color"] == str(theme.GREEN), "正利润该染主题绿"
        assert summ["总成本:"]["value"] == "1,234.50"
    finally:
        dialog.deleteLater()


def test_cost_breakdown_science_activity_fields(cost_breakdown_factory):
    """科研行换成专属明细（成功率 / 作业量 / 蓝图单位成本），不再显示单一研究成本行。"""
    dialog = cost_breakdown_factory("copying")
    try:
        labels = [f["label"] for f in dialog.bridge.jobFields]
        assert "发明成功率:" in labels
        assert "尝试次数 / 作业量:" in labels
        assert "产出蓝图单位成本:" in labels
        values = {f["label"]: f["value"] for f in dialog.bridge.jobFields}
        assert "3 份 × 10 流程" in values["尝试次数 / 作业量:"]
        assert values["产出蓝图单位成本:"] == "1,200 ISK / 份（单份成本）"
    finally:
        dialog.deleteLater()


# ══════════════════════════════════════════════════════════════
# 阶段 4 收尾：从已 QML 化页面里弹出来的三个残留对话框
# （合同详情 / 蓝图 NPC 卖家 / 星系搜索）
# ══════════════════════════════════════════════════════════════


class _FakeItemsWorker(QObject):
    """合同物品加载线程的同步替身（不碰 DB）。"""

    finished_signal = Signal(list)

    def __init__(self, contract_id: int, parent=None) -> None:
        super().__init__(parent)
        self._contract_id = contract_id

    def start(self) -> None:
        self.finished_signal.emit(
            [
                {
                    "type_id": 2001,
                    "zh_name": "渡鸦级",
                    "en_name": "Raven",
                    "quantity": 3,
                    "is_blueprint_copy": True,
                    "material_efficiency": 10,
                },
                {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "quantity": 100, "is_included": False},
            ]
        )

    def isRunning(self) -> bool:
        return False


class _FakeNpcWorker(QObject):
    """ESI 拉单线程的同步替身。"""

    result = Signal(list, str)

    def __init__(self, region_id: int, blueprint_type_id: int, parent=None) -> None:
        super().__init__(parent)
        self.region_id = region_id
        self.blueprint_type_id = blueprint_type_id

    def start(self) -> None:
        self.result.emit([], "")

    def isRunning(self) -> bool:
        return False


@pytest.fixture
def contract_detail_factory(qapp, monkeypatch):
    monkeypatch.setattr(
        "ui_pyside6.workers.contract_workers.ContractItemsLoadWorker",
        _FakeItemsWorker,
    )
    from ui_qml.bridge.contract_detail_bridge import ContractDetailQmlDialog

    contract = {
        "contract_id": 99001,
        "title": "渡鸦级整机一批",
        "type": "item_exchange",
        "status": "outstanding",
        "price": 1234567.89,
        "collateral": 0.0,
        "volume": 2500.0,
        "days_completed": 3,
        "date_issued": "2026-09-01",
        "for_corporation": True,
    }
    return lambda **kw: ContractDetailQmlDialog({**contract, **kw})


@pytest.fixture
def npc_seller_factory(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.npc_seller_bridge.NpcOrderWorker", _FakeNpcWorker)
    from ui_qml.bridge.npc_seller_bridge import NpcSellerQmlDialog

    return lambda name="渡鸦级蓝图": NpcSellerQmlDialog(1160, name)


@pytest.fixture
def system_search_factory(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.system_search_bridge.has_solar_system_data", lambda db: True)
    monkeypatch.setattr(
        "ui_qml.bridge.system_search_bridge.search_solar_systems",
        lambda query, db: [(30000142, "吉他", 0.9), (30002187, "艾玛", 1.0)],
    )
    from ui_qml.bridge.system_search_bridge import SystemSearchQmlDialog

    return lambda: SystemSearchQmlDialog(None, "设置设施星系")


def test_contract_detail_dialog_loads_without_warnings(contract_detail_factory):
    _assert_loads_and_quiet(contract_detail_factory, "合同详情")


def test_npc_seller_dialog_loads_without_warnings(npc_seller_factory):
    _assert_loads_and_quiet(npc_seller_factory, "蓝图 NPC 卖家")


def test_system_search_dialog_loads_without_warnings(system_search_factory):
    _assert_loads_and_quiet(system_search_factory, "星系搜索")


def test_contract_detail_renders_fields_and_items(contract_detail_factory):
    dialog = contract_detail_factory()
    try:
        bridge = dialog.bridge
        assert bridge.headerText == "#99001  渡鸦级整机一批"
        assert "物品交换" in bridge.detailText and "进行中" in bridge.detailText
        assert "1,234,567.89 ISK" in bridge.detailText
        assert "企业合同: 是" in bridge.datesText

        assert bridge.rowCount == 2
        assert bridge.statusText == "共 2 件物品"
        first = bridge.rows[0]["cells"]
        assert [c["text"] for c in first] == ["2001", "渡鸦级", "Raven", "3", "是", "是", "10", "—"]
        assert first[3]["color"] != "", "数量列该用主题色（对齐 Widgets 版的 ForegroundRole）"
        second = bridge.rows[1]["cells"]
        assert second[1]["text"] == "三钛合金"
        assert second[5]["text"] == "否", "is_included=False 该显示「否」"
    finally:
        dialog.deleteLater()


def test_contract_detail_empty_state_after_load(contract_detail_factory):
    """加载完成但一件物品都没有时，空表提示要换掉「正在加载」。"""
    dialog = contract_detail_factory()
    try:
        dialog.bridge._on_items_loaded([])
        assert dialog.bridge.emptyText == "合同内没有物品"
        assert dialog.bridge.statusText == "共 0 件物品"
    finally:
        dialog.deleteLater()


def test_npc_seller_result_states(npc_seller_factory):
    """三种返回：有单 / 无单（给解释性提示，不是错误）/ 真错误。"""
    dialog = npc_seller_factory()
    try:
        bridge = dialog.bridge
        assert bridge.rowCount == 0
        assert "没有 NPC 直售单" in bridge.statusText

        bridge._on_result([{"corp": "核心统合部", "location": "吉他 IV（吉他）", "price": 1234.5, "volume": 7}], "")
        assert bridge.statusText == "共 1 条 NPC 直售单"
        cells = bridge.rows[0]["cells"]
        assert [c["text"] for c in cells] == ["核心统合部", "吉他 IV（吉他）", "1,234.50", "7"]

        bridge._on_result([], "拉取失败：超时")
        assert bridge.statusText == "拉取失败：超时"
        assert bridge.rowCount == 0
    finally:
        dialog.deleteLater()


def test_npc_seller_hub_switch_refetches(npc_seller_factory):
    dialog = npc_seller_factory()
    try:
        bridge = dialog.bridge
        assert [h["label"] for h in bridge.hubs][0] == "吉他 (Jita)"
        bridge.setHub(2)
        assert bridge.hubIndex == 2
        assert bridge.loading is False, "同步替身已在 start() 里回结果"
    finally:
        dialog.deleteLater()


def test_system_search_returns_the_picked_system(system_search_factory):
    dialog = system_search_factory()
    try:
        bridge = dialog.bridge
        assert bridge.rowCount == 2
        assert bridge.statusText == "共 2 个星系"
        assert bridge.hasSelection is False

        # 没选就不让关：给出原因而不是静默无反应（Widgets 版是点了没反应）
        bridge.accept()
        assert "请先选择一个星系" in bridge.error
        assert dialog.result() == 0

        bridge.selectRow(1)
        assert bridge.hasSelection is True
        assert dialog.get_selected() == (30002187, "艾玛")

        bridge.accept()
        assert dialog.result() == 1  # QDialog.Accepted
    finally:
        dialog.deleteLater()


def test_system_search_rerun_clears_stale_selection(system_search_factory):
    """换了搜索词就该丢掉上次的选择 —— 否则「确定」会把上一个星系名落库。"""
    dialog = system_search_factory()
    try:
        bridge = dialog.bridge
        bridge.selectRow(0)
        assert dialog.get_selected() == (30000142, "吉他")

        bridge.setQuery("艾玛")
        bridge.runSearch()  # 防抖在测试里跳过：直接跑
        assert bridge.hasSelection is False
        assert dialog.get_selected() is None
    finally:
        dialog.deleteLater()


def test_system_search_without_data_disables_search(qapp, monkeypatch):
    """SDE 扩展数据没跑过时：搜索框禁用 + 给一句可执行的提示（原逻辑照搬）。"""
    monkeypatch.setattr("ui_qml.bridge.system_search_bridge.has_solar_system_data", lambda db: False)
    from ui_qml.bridge.system_search_bridge import SystemSearchBridge

    bridge = SystemSearchBridge("设置机库星系")
    assert bridge.dataReady is False
    assert "数据初始化" in bridge.statusText
    bridge.setQuery("吉他")
    bridge.runSearch()
    assert bridge.rowCount == 0


class _SlowItemsWorker(QObject):
    """一直「在跑」的加载线程替身 —— 用来验证关窗时确实做了收尾。"""

    finished_signal = Signal(list)

    def __init__(self, contract_id: int, parent=None) -> None:
        super().__init__(parent)
        self.interrupted = False
        self.waited = 0

    def start(self) -> None: ...

    def isRunning(self) -> bool:
        return True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited = ms
        return True


def test_closing_a_dialog_finishes_its_worker(qapp, monkeypatch):
    """关窗必须让在跑的后台线程收尾。

    不收尾的话，线程是桥的子对象、桥随对话框一起销毁 —— `QThread` 在运行时被析构
    Qt 直接 `abort()`，整个进程静默死掉（实测退出码 127、一行日志都没有，
    `ui_snapshot.py --dialog contract_detail` 就是这么挂的）。
    """
    monkeypatch.setattr("ui_pyside6.workers.contract_workers.ContractItemsLoadWorker", _SlowItemsWorker)
    from ui_qml.bridge.contract_detail_bridge import ContractDetailQmlDialog

    dialog = ContractDetailQmlDialog({"contract_id": 1})
    try:
        worker = dialog.bridge._worker
        assert worker.isRunning(), "替身应当一直说自己在跑"

        dialog.done(0)  # 确定 / 取消 / Esc 都走这里
        assert worker.interrupted and worker.waited > 0, "关窗该请求中断并等线程收尾"
    finally:
        dialog.deleteLater()


# ══════════════════════════════════════════════════════════════
# 批次 1（仓库链路）：取值对话框 / 物品搜索 / 材料覆盖
# ══════════════════════════════════════════════════════════════


def _input_dialog(mode: str = "text", **kw):
    from ui_qml.bridge.input_dialog import InputBridge, InputQmlDialog

    return InputQmlDialog(InputBridge("标题", "标签", mode, **kw))


def test_input_dialog_loads_without_warnings():
    """四种形态各加载一次 —— `mode` 决定显示哪个输入控件，只有实际加载才验得到。"""
    _assert_loads_and_quiet(lambda: _input_dialog("text", text="甲"), "取值对话框(文本)")
    _assert_loads_and_quiet(lambda: _input_dialog("int", value=5, minimum=0, maximum=100), "取值对话框(整数)")
    _assert_loads_and_quiet(lambda: _input_dialog("double", value=1.5), "取值对话框(小数)")
    _assert_loads_and_quiet(lambda: _input_dialog("choice", choices=["甲库", "乙库"]), "取值对话框(下拉)")


def test_input_dialog_returns_the_typed_value(qapp):
    """确定时按 mode 定格的类型要分开 —— 整数不能被当小数吐回来。"""
    from ui_qml.bridge.input_dialog import MODE_CHOICE, MODE_DOUBLE, MODE_INT, MODE_TEXT

    dlg = _input_dialog(MODE_TEXT, text="手输")
    try:
        dlg.bridge.setText("改过")
        dlg.bridge.accept()
        assert dlg.bridge.text_value() == "改过"
    finally:
        dlg.deleteLater()

    dlg = _input_dialog(MODE_INT, value=3)
    try:
        dlg.bridge.setValue(7.6)  # 四舍五入成 8，且必须是 int
        dlg.bridge.accept()
        assert dlg.bridge.integer() == 8
        assert isinstance(dlg.bridge.integer(), int)
    finally:
        dlg.deleteLater()

    dlg = _input_dialog(MODE_DOUBLE, value=1.0)
    try:
        dlg.bridge.setValue(2.25)
        dlg.bridge.accept()
        assert dlg.bridge.number() == 2.25
    finally:
        dlg.deleteLater()

    dlg = _input_dialog(MODE_CHOICE, choices=["甲库", "乙库"], choice_index=0)
    try:
        dlg.bridge.setChoiceIndex(1)
        dlg.bridge.accept()
        assert dlg.bridge.text_value() == "乙库"
    finally:
        dlg.deleteLater()


def test_input_dialog_value_is_empty_until_accepted(qapp):
    """没点确定就不该有返回值 —— 调用方全靠 `ok` 分支，这里错了会静默写坏数据。"""
    dlg = _input_dialog("text", text="初始")
    try:
        dlg.bridge.setText("改了但没确定")
        dlg.reject()
        assert dlg.bridge.text_value() == "", "取消后不该把编辑中的内容当结果"
    finally:
        dlg.deleteLater()


def test_input_bridge_rejects_out_of_range_choice(qapp):
    dlg = _input_dialog("choice", choices=["甲", "乙"])
    try:
        dlg.bridge.setChoiceIndex(9)
        assert dlg.bridge.choiceIndex == 0, "越界下标应被忽略，而不是把 currentIndex 弄成 -1"
    finally:
        dlg.deleteLater()


# ── 物品搜索（FPickList 与星系搜索共用一份布局）──


@pytest.fixture
def item_search_factory(qapp, monkeypatch):
    """搜索源按词返回不同结果 —— 这样才分得出「选择跟着新结果走」还是「留着旧行号」。"""

    def _find(text: str) -> list[dict]:
        if "三钛" in text:
            return [
                {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium"},
                {"type_id": 35, "zh_name": "类晶体胶矿", "en_name": "Pyerite"},
            ]
        return [{"type_id": 36, "zh_name": "同位聚合体", "en_name": "Mexallon"}]

    monkeypatch.setattr("ui_qml.bridge.item_search_bridge.find_items", _find)
    from ui_qml.bridge.item_search_bridge import ItemSearchQmlDialog

    return lambda: ItemSearchQmlDialog(None, "搜索匹配物品")


def test_item_search_dialog_loads_without_warnings(item_search_factory):
    _assert_loads_and_quiet(item_search_factory, "物品搜索")


def test_item_search_returns_the_picked_item(item_search_factory):
    dialog = item_search_factory()
    try:
        bridge = dialog.bridge
        assert bridge.selected_item() is None
        bridge.setQuery("三钛")
        bridge.runSearch()  # 防抖在测试里跳过
        assert len(bridge.rows) == 2

        bridge.selectRow(1)
        assert bridge.hasSelection is True
        assert dialog.selected_item() == {"type_id": 35, "zh_name": "类晶体胶矿", "en_name": "Pyerite"}

        bridge.accept()
        assert dialog.result() == 1
    finally:
        dialog.deleteLater()


def test_item_search_only_result_is_adopted_without_clicking(qapp, monkeypatch):
    """只搜到一条时「选定」直接采用它 —— 原 Widgets 版的便利行为，必须保住。"""
    monkeypatch.setattr(
        "ui_qml.bridge.item_search_bridge.find_items",
        lambda text: [{"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium"}],
    )
    from ui_qml.bridge.item_search_bridge import ItemSearchBridge

    bridge = ItemSearchBridge()
    bridge.setQuery("三钛")
    bridge.runSearch()
    assert len(bridge.rows) == 1
    bridge.accept()
    assert bridge.selected_item() == {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium"}


def test_item_search_rerun_resets_to_the_first_result(item_search_factory):
    """换搜索词后选择要跟着重置到新结果的第一条，不能留着上一次的行号。

    留着行号就是**指向另一个物品**（结果集已经换了），「选定」会把错的东西落库。
    对齐 Widgets 版：它每次重建模型顺带清掉，这里由 `runSearch` 显式重置。
    """
    dialog = item_search_factory()
    try:
        bridge = dialog.bridge
        bridge.setQuery("三钛")
        bridge.runSearch()
        bridge.selectRow(1)
        assert dialog.selected_item()["zh_name"] == "类晶体胶矿"

        bridge.setQuery("同位")
        bridge.runSearch()
        selected = dialog.selected_item()
        assert selected is not None, "搜到结果就该选中第一条"
        assert selected["zh_name"] == "同位聚合体", "选择必须跟着新结果走，不能停在旧行号上"
    finally:
        dialog.deleteLater()


# ── 材料覆盖 ──


@pytest.fixture
def coverage_factory(qapp, monkeypatch):
    import services.plan_execution as pe

    monkeypatch.setattr(
        pe,
        "get_plans_for_mat_hangar",
        lambda hangar_id: [{"product_name": "渡鸦级", "status": "pending"}],
    )
    monkeypatch.setattr(
        pe,
        "aggregate_material_requirements",
        lambda plans, hangar_id: [
            {"name": "三钛合金", "need": 1000, "owned": 400, "missing": 600},
            {"name": "类晶体胶矿", "need": 50, "owned": 50, "missing": 0},
        ],
    )
    from ui_qml.bridge.material_coverage_bridge import MaterialCoverageQmlDialog

    return lambda: MaterialCoverageQmlDialog(7, "矿仓")


def test_material_coverage_dialog_loads_without_warnings(coverage_factory):
    _assert_loads_and_quiet(coverage_factory, "材料覆盖")


def test_material_coverage_rows_and_summary(coverage_factory):
    dialog = coverage_factory()
    try:
        bridge = dialog.bridge
        assert bridge.headerText == "「渡鸦级」(待生产) · 共 1 条计划"
        assert bridge.statusText == "缺 1 种 / 共 600 件"
        assert bridge.rowCount == 2
        first = bridge.rows[0]["cells"]
        assert [c["text"] for c in first] == ["三钛合金", "1,000", "400", "600"]
        assert first[3]["color"] != "", "缺口 > 0 该标红"
        assert bridge.rows[1]["cells"][3]["color"] == "", "缺口为 0 不该标红"
    finally:
        dialog.deleteLater()


def test_material_coverage_empty_state(qapp, monkeypatch):
    """该机库没被任何计划用作材料机库时：空表提示要说明原因，不是「没有数据」。"""
    import services.plan_execution as pe

    monkeypatch.setattr(pe, "get_plans_for_mat_hangar", lambda hangar_id: [])
    from ui_qml.bridge.material_coverage_bridge import MaterialCoverageBridge

    bridge = MaterialCoverageBridge(7, "矿仓")
    bridge.reload()
    assert bridge.rowCount == 0
    assert bridge.emptyText == "该机库未被任何计划用作材料机库"
    assert bridge.statusText == "关联计划 0 条"


# ── 机库三个对话框（编辑数量 / 批量成本价 / 手动添加）──


def test_edit_qty_dialog_loads_without_warnings():
    from ui_qml.bridge.hangar_dialogs import EditQtyQmlDialog

    _assert_loads_and_quiet(lambda: EditQtyQmlDialog("三钛合金", 100), "编辑数量")


def test_batch_cost_price_dialog_loads_without_warnings():
    from ui_qml.bridge.hangar_dialogs import BatchCostPriceQmlDialog

    _assert_loads_and_quiet(BatchCostPriceQmlDialog, "批量设置成本价")


def test_add_item_dialog_loads_without_warnings(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.item_search_bridge.find_items", lambda text: [])
    from ui_qml.bridge.hangar_dialogs import AddItemQmlDialog

    _assert_loads_and_quiet(lambda: AddItemQmlDialog("矿仓"), "手动添加物品")


def test_edit_qty_returns_the_spun_value(qapp):
    """整数微调框：输入不出非法值，所以 quantity() 恒为有效值（原版是文本框，非数字返回 -1）。"""
    from ui_qml.bridge.hangar_dialogs import EditQtyQmlDialog

    dlg = EditQtyQmlDialog("三钛合金", 100)
    try:
        assert dlg.quantity() == 100, "初值该是当前数量"
        dlg.bridge.setValue(250)
        dlg.bridge.accept()
        assert dlg.quantity() == 250
    finally:
        dlg.deleteLater()


def test_add_item_returns_type_qty_cost(qapp, monkeypatch):
    monkeypatch.setattr(
        "ui_qml.bridge.item_search_bridge.find_items",
        lambda text: [{"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium"}],
    )
    monkeypatch.setattr("ui_qml.bridge.hangar_dialogs.get_item_price", lambda type_id: 5.5)
    from ui_qml.bridge.hangar_dialogs import AddItemQmlDialog

    dlg = AddItemQmlDialog("矿仓")
    try:
        assert dlg.result_data() is None, "还没选物品时不该有结果"
        dlg.bridge.setQuery("三钛")
        dlg.bridge.runSearch()
        # 选中时按市场价带出成本价（原 `_on_row_selected` 的行为）
        assert dlg.bridge.cost == 5.5
        dlg.bridge.setQuantity(7)
        dlg.bridge.accept()
        assert dlg.result_data() == (34, 7, 5.5)
    finally:
        dlg.deleteLater()


# ── 母项拆解（阶段 4a 收尾）──


def test_parent_decompose_dialog_loads_without_warnings(qapp):
    """空态那条分支：没有可拆母项时不该碰 DB，QML 也要能干净加载。

    `qapp` 是**必须**的：别的护栏测试经由各自的工厂 fixture 间接拿到它，
    这里直接构造对话框，漏了就会在没有 QApplication 的情况下建 QWidget ——
    Qt 的致命消息经本测试装的消息处理器绕一圈，表现为**挂死**而不是报错
    （实测：整条命令卡住、无输出）。
    """
    from ui_qml.bridge.parent_decompose_bridge import ParentDecomposeQmlDialog

    _assert_loads_and_quiet(lambda: ParentDecomposeQmlDialog([]), "母项拆解(空态)")


def test_parent_decompose_line_cells_marks_missing_blueprint_and_loss():
    """行装配的配色规则：无蓝图标红、利润为负标红、其余默认。"""
    from ui_qml.bridge.parent_decompose_bridge import line_cells

    line = {
        "product_type_id": 1001,
        "sub_level": 1,
        "demand": 10,
        "runs": 2,
        "parallels": 5,
        "me_level": 0,
        "te_level": 0,
        "has_blueprint": False,
    }
    cells = line_cells(7, line, "碳纤维", -1200.0)
    assert [c["text"] for c in cells[:9]] == ["7", "碳纤维", "1", "10", "2", "5", "0-0", "-1,200", "无蓝图"]
    assert cells[7]["color"] != "", "负利润该标红"
    assert cells[8]["color"] != "", "无蓝图该标红"

    ok = line_cells(7, {**line, "has_blueprint": True}, "碳纤维", 500.0)
    assert ok[7]["color"] == "" and ok[8]["color"] == ""

    unknown = line_cells(7, line, "碳纤维", None)
    assert unknown[7]["text"] == "—", "算不出利润时显示破折号而不是 0"


# ── 表行命中：ListView 与 TableView 的坐标口径不同（回归）──


def _qml_child(item, predicate):
    """在 QML 对象树里找第一个满足 predicate 的子项（深度优先）。"""
    for child in item.childItems():
        if predicate(child):
            return child
        found = _qml_child(child, predicate)
        if found is not None:
            return found
    return None


def test_summary_table_row_hit_accounts_for_listview_scroll(qapp):
    """`FSummaryTable` 的行命中必须补上 `ListView` 的 `contentY`。

    内联子项在两种表里的坐标口径**不一样**：

    - `TableView`：挂在 `contentItem` 上 → 事件已是内容坐标，补 0
    - `ListView`：挂在表本体上 → 事件是**视口**坐标，必须加 `contentY`

    少补这一次，滚过之后点第 N 行就会算成第 N−已滚行数 行 —— 实测修前
    `contentY=200` 时点视口 `y=25` 报第 1 行、应为第 11 行。这正是用户最早报的
    「点的这行、选的另外一行」，所以在同一个组件里把两种情况都锁住。
    """
    from ui_qml.bridge.summary_dialog import SummaryTableBridge, cell
    from ui_qml.dialog_host import QmlDialog

    bridge = SummaryTableBridge(title="滚动命中", columns=[{"title": "列", "width": 0}])
    bridge.set_content([{"cells": [cell(f"r{i}")]} for i in range(50)], "")

    dialog = QmlDialog("dialogs/SummaryTableDialog.qml", bridge, size=(240, 120))
    try:
        root = dialog._host.rootObject()
        assert root is not None
        view = _qml_child(root, lambda it: it.metaObject().className().startswith("QQuickListView"))
        assert view is not None, "SummaryTableDialog 里的行区应当是个 ListView"
        area = _qml_child(root, lambda it: it.objectName() == "summaryClickArea")
        assert area is not None

        assert area.rowAt(25.0) == 1, "没滚动时视口 y=25 落在第 1 行"

        # 用**实际行高**滚整数行：行高随字号缩放（出厂值下是 24 不是 20），
        # 写死像素数会把「滚了 8.3 行」当成「滚了 10 行」，断言就假失败了
        row_h = float(area.property("rowHeight"))
        base = area.rowAt(25.0)
        view.setProperty("contentY", 10 * row_h)
        _spin(60)
        assert view.property("contentY") == 10 * row_h
        assert area.rowAt(25.0) == base + 10, "同一视口位置，滚过 10 行后行号必须正好 +10"
    finally:
        dialog.deleteLater()


# ── 批次 1 收尾：导入审查 / 蓝图导入 / 移库（含二级弹出）──


def test_import_review_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.review_bridge import ImportReviewQmlDialog

    _assert_loads_and_quiet(lambda: ImportReviewQmlDialog([], "测试机库", 1), "导入审查")


def test_import_change_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.review_bridge import ImportChangeQmlDialog

    _assert_loads_and_quiet(lambda: ImportChangeQmlDialog([], added=0, moved=0, hangar_name="测试机库"), "导入变动汇总")


def test_hangar_pick_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.review_bridge import HangarPickQmlDialog

    _assert_loads_and_quiet(lambda: HangarPickQmlDialog([]), "选择来源机库物品")


def test_blueprint_import_review_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.blueprint_import_bridge import BlueprintImportReviewQmlDialog

    _assert_loads_and_quiet(lambda: BlueprintImportReviewQmlDialog([], "测试机库"), "蓝图导入预览")


def test_blueprint_import_change_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.blueprint_import_bridge import BlueprintImportChangeQmlDialog

    _assert_loads_and_quiet(
        lambda: BlueprintImportChangeQmlDialog([], added=0, removed=0, hangar_name="测试机库"),
        "蓝图导入变动汇总",
    )


def test_transfer_dialog_loads_without_warnings(qapp, monkeypatch):
    import ui_qml.bridge.transfer_bridge as tb

    monkeypatch.setattr(tb, "get_hangars", lambda: [{"id": 1, "name": "源仓"}, {"id": 2, "name": "目标仓"}])
    monkeypatch.setattr(tb, "get_items", lambda hid: [])
    monkeypatch.setattr(tb, "get_hangar_stock", lambda hid: {})
    from ui_qml.bridge.transfer_bridge import HangarTransferQmlDialog

    _assert_loads_and_quiet(lambda: HangarTransferQmlDialog([], 2, "目标仓"), "移库")


# ── 批次 2（查询链路）：订单弹窗 / 价格走势图 ──


class _StubHistoryWorker(QObject):
    """价格历史拉取线程的同步替身（不联网）。

    签名与信号**照抄** `ui_pyside6.views.price_chart.PriceHistoryWorker` ——
    少一个信号，桥在 connect 时就会 AttributeError。
    """

    finished_signal = Signal(int, list)
    error_signal = Signal(int, str)

    def __init__(self, type_id: int, region_id: int = 10000002, parent=None) -> None:
        super().__init__(parent)

    def start(self) -> None:
        self.finished_signal.emit(0, [])

    def isRunning(self) -> bool:
        return False


def test_order_popup_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.order_popup_bridge import OrderPopupQmlDialog

    _assert_loads_and_quiet(lambda: OrderPopupQmlDialog(), "订单弹窗")


def test_price_chart_dialog_loads_without_warnings(qapp, monkeypatch):
    monkeypatch.setattr("ui_pyside6.views.price_chart.PriceHistoryWorker", _StubHistoryWorker)
    from ui_qml.bridge.price_chart_bridge import PriceChartQmlDialog

    _assert_loads_and_quiet(lambda: PriceChartQmlDialog(34, "三钛合金"), "价格走势图")


def test_batch_price_dialog_loads_without_warnings(qapp, monkeypatch):
    import ui_qml.bridge.batch_price_bridge as bp

    monkeypatch.setattr(bp, "BatchPriceWorker", _StubHistoryWorker)
    from ui_qml.bridge.batch_price_bridge import BatchPriceQmlDialog

    _assert_loads_and_quiet(lambda: BatchPriceQmlDialog(), "批量查价")


def test_hangar_settings_dialog_loads_without_warnings(qapp, monkeypatch):
    """机库设置（阶段 4c）—— 独立一级入口，不由页面弹出。"""
    import services.inventory_manager as im

    monkeypatch.setattr(im, "get_hangars", lambda: [{"id": 1, "name": "矿仓"}])
    from ui_qml.bridge.hangar_settings_bridge import HangarSettingsQmlDialog

    _assert_loads_and_quiet(lambda: HangarSettingsQmlDialog(None), "机库设置")


# ── 批次 2：评分设置（制造/贸易）/ 批量对比 ──


def test_mfg_params_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.score_dialogs_bridge import MfgQmlDialog

    _assert_loads_and_quiet(lambda: MfgQmlDialog(), "制造评分设置")


def test_trade_params_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.score_dialogs_bridge import TradeQmlDialog

    _assert_loads_and_quiet(lambda: TradeQmlDialog(), "贸易评分设置")


def test_compare_dialog_loads_without_warnings(qapp):
    from ui_qml.bridge.compare_bridge import CompareQmlDialog

    _assert_loads_and_quiet(lambda: CompareQmlDialog(), "批量对比")


def test_init_wizard_dialog_loads_without_warnings(qapp):
    """数据初始化向导（阶段 4c）—— 构造期不起线程（worker 只在「开始」时才建），故可直接构造。"""
    from ui_qml.bridge.init_wizard_bridge import InitWizardQmlDialog

    _assert_loads_and_quiet(lambda: InitWizardQmlDialog(), "数据初始化向导")


def test_page_host_shows_a_visible_error_when_qml_fails(qapp):
    """QML 加载失败必须**看得见**，不能只写日志。

    以前只 log + 发信号，而宿主自己不会回退（页面的回退在注册表里，对话框没有回退），
    结果是一块空白 —— 用户只会觉得软件坏了。这条守住「失败要显示出来」。
    """
    from PySide6.QtWidgets import QLabel

    from ui_qml.host import PageHost

    host = PageHost("pages/绝对不存在的页面.qml")
    try:
        _spin(120)
        assert not host.ok(), "这份 QML 本来就该加载失败"
        label = host.findChild(QLabel, "qml_load_error")
        assert label is not None, "加载失败时应当盖一块错误面"
        assert "不存在" in label.text()
    finally:
        host.deleteLater()
        _spin(60)


# ── 真渲染才看得见的一条：底色不能漏 ────────────────────────────────
#
# 这类缺陷**离屏快照与静态扫描都看不见**（用户先发现的）：
# `QWidget.grab()` 会把没画到的空区补成调色板底色，快照一切正常，真窗口却是纯黑。
# 三条用例是当时出问题的那个家族（设置 / 人物设置 / 机库设置）。
# （标签截断那条改由 `test_qml_components.test_ftabbar_keeps_labels_intact_...` 守：
#  在对话框自己的尺寸下它测不出问题，属于没牙的断言。）

_FRAME_CASES = [
    ("系统设置", "ui_qml.bridge.settings_bridge", "SettingsQmlDialog"),
    ("人物设置", "ui_qml.bridge.char_settings_bridge", "CharSettingsQmlDialog"),
    ("机库设置", "ui_qml.bridge.hangar_settings_bridge", "HangarSettingsQmlDialog"),
]


def _build_dialog(module: str, cls: str) -> Any:
    import importlib

    return getattr(importlib.import_module(module), cls)(None)


def _descendants(item: Any, out: list[Any]) -> None:
    for child in item.childItems():
        out.append(child)
        _descendants(child, out)


@pytest.mark.parametrize(("label", "module", "cls"), _FRAME_CASES)
def test_dialog_leaves_no_transparent_hole(qapp, label, module, cls):
    """对话框不能留透明洞：宿主透明清屏，没画到的地方直接透出窗口背后（真窗口下是纯黑）。

    **必须读 `QQuickWidget` 自己的帧缓冲**（`grabFramebuffer()`）。`QWidget.grab()`
    会把空区补成调色板底色，正好把洞盖住 —— 快照工具就是这么漏掉它的：
    `ui_snapshot.py --dialog settings` 一切正常，真窗口抓屏却是 77% 像素纯黑
    （用户报「设置界面是黑的」）。
    """
    dialog = _build_dialog(module, cls)
    try:
        # 必须 show：不显示的话布局不跑，控件全是 0 宽、帧缓冲也是空的（实测过）
        dialog.resize(760, 600)
        dialog.show()
        _spin(400)
        image = dialog._host.grabFramebuffer()
        assert not image.isNull(), f"{label} 没渲染出画面"
        holes = sum(
            1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2) if qAlpha(image.pixel(x, y)) == 0
        )
        assert holes == 0, f"{label} 有 {holes} 个采样点是透明的（没画到），会透出窗口背后"
    finally:
        dialog.hide()
        dialog.deleteLater()
        _spin(80)


def test_destroying_the_dialog_stops_the_bridge(qapp):
    """`deleteLater()`（不经过 `done()` / `closeEvent`）也必须走到桥的 `stop()`。

    桥里的后台线程是**桥的子对象**：桥随对话框一起销毁，而 `QThread` 在**运行中**被
    析构时 Qt 直接中止进程；更阴的是它可能只是在后续某个事件循环里把队列信号投给
    已销毁的 QML 对象 —— 表现成「另一个无关测试的 fixture 拆除处突然段错误」
    （本仓实测：`-m ui` 全量档偶发 access violation，崩点固定在 storage 页的拆除里，
    查了很久，根子在别处）。
    """
    from ui_qml.dialog_host import DialogBridge, QmlDialog

    calls: list[str] = []

    class _Bridge(DialogBridge):
        def stop(self) -> None:
            calls.append("stop")

    dialog = QmlDialog("dialogs/InputDialog.qml", _Bridge())  # 该 QML 不依赖具体桥字段
    dialog.resize(400, 200)
    dialog.deleteLater()
    _spin(150)

    assert calls == ["stop"], "对话框被销毁时没停桥：桥里的 QThread 会在运行中被析构（硬崩）"

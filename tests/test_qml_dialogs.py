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
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QtMsgType, qInstallMessageHandler

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

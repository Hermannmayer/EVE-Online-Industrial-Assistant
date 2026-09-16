import pytest

pytestmark = pytest.mark.ui

"""IndustryPage UI 测试。"""


def test_plan_edit_dialog_batch_sync_gating(industry_page, monkeypatch):
    """批量编辑弹窗：默认不同步流程/并行（复选未勾 → None → 调用方不写库），勾选后才写。

    阶段 4：对话框本体迁到 QML 后，这里同时验证「QML 加载成功」与「桥的取值契约」——
    调用方拿到的仍是 `exec()` + `get_updated_data()` 那一套，所以断言点基本没动。
    """
    from services import inventory_manager
    from ui_qml.bridge.plan_edit_bridge import PlanEditQmlDialog

    monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
    monkeypatch.setattr("services.char_config_resolver.get_character_list", lambda: ["甲"])

    dlg = PlanEditQmlDialog(
        industry_page,
        {"_selected_rows": [1, 2], "runs": 5, "parallels": 3},
        batch_mode=True,
        row_count=2,
    )
    try:
        assert dlg.ok(), "QML 对话框没加载起来：" + "; ".join(str(e) for e in dlg._host.errors())

        data = dlg.get_updated_data()
        assert data["runs"] is None
        assert data["parallels"] is None

        dlg.bridge.setSyncRuns(True)
        data2 = dlg.get_updated_data()
        assert data2["runs"] == 5
        assert data2["parallels"] == 3
    finally:
        dlg.deleteLater()

    # 单行模式不受复选影响，始终返回字段值
    single = PlanEditQmlDialog(industry_page, {"runs": 2, "parallels": 1})
    try:
        result = single.get_updated_data()
        assert result["runs"] == 2
        assert result["parallels"] == 1
    finally:
        single.deleteLater()


def test_industry_page_init(industry_page):
    """验证 IndustryPage 控制器初始化后的关键部件存在。

    ⚠️ 批次 7.4 起它是纯 `QObject` 控制器、**不再自建 QML 宿主**（`_host` 已删）：
    渲染面由外壳按 `ui_qml/industry_page.industry_spec` 装载，本类只留两个桥与计划表控制器。
    页面 Item 确实挂进场景那条断言在 `tests/test_theme_listeners.py` 与 `tests/test_qml_shell.py`。
    """
    assert industry_page is not None
    assert industry_page.bridge is not None
    assert industry_page.plan_table_bridge is not None
    assert industry_page._plan_table_widget is not None


def test_industry_page_default_view(industry_page):
    """默认是数据表格视图。"""
    assert industry_page._bridge.viewMode == "data"
    assert industry_page._bridge.statusVisible is True


def test_industry_page_view_switch(industry_page):
    """切到甘特图后重算排期，并隐藏状态栏/功能按钮。"""
    industry_page._bridge.setViewMode("gantt")
    assert industry_page._bridge.viewMode == "gantt"
    assert industry_page._bridge.statusVisible is False
    assert isinstance(industry_page._bridge.ganttRows, list)

    industry_page._bridge.setViewMode("data")
    assert industry_page._bridge.viewMode == "data"
    assert industry_page._bridge.statusVisible is True


def test_industry_page_save_restore_state(industry_page):
    """验证保存/恢复页面状态。"""
    state = industry_page.save_state()
    assert "v_scroll" in state

    industry_page.restore_state(state)
    # 恢复后不崩溃即可


def test_industry_page_plan_count_text(industry_page):
    """计划计数由桥给出的文案承载（原为 `_plan_count` 标签）。"""
    assert industry_page._bridge.planCountText.startswith("共 ")


def test_industry_filter_defaults_to_all(industry_page):
    """默认筛选「全部」，且切换会触发重载（不抛异常即可）。"""
    assert industry_page._bridge.current_filter() == "全部"
    industry_page._bridge.setFilterIndex(1)
    assert industry_page._bridge.current_filter() == "待排"
    industry_page._bridge.setFilterIndex(0)


def test_procurement_summary_reruns_on_price_change(industry_page, monkeypatch):
    """改价格设置（Hub / 卖价买价 / 倍率）后必须重算汇总，不能命中指纹缓存回吐旧值。

    回归用例：旧指纹只含计划字段，改价格后 `fp == self._proc_fp` 直接命中缓存返回，
    红框「备料中采购」数字永远不动 —— 用户报的「写死的」。

    刻意不碰真实控件：真改控件会经 `IndustryBridge.setPriceSetting → load_plans()` 触发
    真实刷新，且会写 `data/settings.json`。价格设置改从模块级 `get_price_settings` 读，
    故这里直接 patch 它（阶段 2b 前是 patch `_toolbar.get_price_settings`）。
    """
    from core.constants import TRADE_HUB_IDS
    from ui_pyside6.views import industry_view as iv

    settings = {"mat_hub": "Jita", "mat_price_type": "sell", "mat_mult": 1.0}
    started: list[dict] = []

    class _Signal:
        def connect(self, _fn):
            return None

    class _FakeWorker:
        def __init__(self, plans, **kwargs):
            started.append(kwargs)
            self.finished_signal = _Signal()

        def isRunning(self):  # 对齐 QThread 的 camelCase API
            return False

        def start(self):
            return None

    monkeypatch.setattr(iv, "ProcurementSummaryWorker", _FakeWorker)
    monkeypatch.setattr(iv, "_default_mat_hangar_id", lambda: 7)
    monkeypatch.setattr(iv, "get_price_settings", lambda: dict(settings))

    plan = {"id": 1, "materials_ready": 1, "status": "pending", "runs": 1, "parallels": 1, "me_level": 0}

    industry_page._refresh_procurement_summary([plan])
    assert len(started) == 1
    assert started[0]["region_id"] == TRADE_HUB_IDS["Jita"]
    assert started[0]["price_type"] == "sell"
    assert started[0]["price_mult"] == 1.0
    assert started[0]["default_mat_hangar_id"] == 7

    # 模拟后台线程已算完（旧实现正是靠 _proc_result 有值才命中缓存）
    industry_page._proc_result = (100.0, 1.0)

    # 计划一字未改，只改价格设置 → 必须重算
    settings.update({"mat_hub": "Amarr", "mat_price_type": "buy", "mat_mult": 1.1})
    industry_page._refresh_procurement_summary([plan])
    assert len(started) == 2, "改价格设置后必须重算，不能回吐缓存"
    assert started[1]["region_id"] == TRADE_HUB_IDS["Amarr"]
    assert started[1]["price_type"] == "buy"
    assert started[1]["price_mult"] == 1.1


def test_procurement_summary_cached_when_nothing_changed(industry_page, monkeypatch):
    """计划与价格设置都没变时命中缓存，不重复起线程（指纹缓存的正向行为）。"""
    from ui_pyside6.views import industry_view as iv

    settings = {"mat_hub": "Jita", "mat_price_type": "sell", "mat_mult": 1.0}
    started: list[dict] = []

    class _Signal:
        def connect(self, _fn):
            return None

    class _FakeWorker:
        def __init__(self, plans, **kwargs):
            started.append(kwargs)
            self.finished_signal = _Signal()

        def isRunning(self):  # 对齐 QThread 的 camelCase API
            return False

        def start(self):
            return None

    monkeypatch.setattr(iv, "ProcurementSummaryWorker", _FakeWorker)
    monkeypatch.setattr(iv, "_default_mat_hangar_id", lambda: 7)
    monkeypatch.setattr(iv, "get_price_settings", lambda: dict(settings))

    plan = {"id": 1, "materials_ready": 1, "status": "pending", "runs": 1, "parallels": 1, "me_level": 0}

    industry_page._refresh_procurement_summary([plan])
    industry_page._proc_result = (100.0, 1.0)
    industry_page._refresh_procurement_summary([plan])
    assert len(started) == 1, "计划与价格都未变时不应重复查询"


class TestNotesInlineEditPersists:
    """备注列内联编辑必须落库。

    模型层 `setData` 只改内存字典（`industry_models.py` 第 4 列分支），旧实现没有
    任何落库钩子 —— 双击改完备注、下一次刷新就丢。这里是回归防线。
    """

    @staticmethod
    def _table(monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable
        from ui_qml.models.industry_models import PlanTableModel
        from ui_qml.models.plan_table_constants import COL_NOTES

        repo = MagicMock()
        monkeypatch.setattr(
            "ui_pyside6.views.industry.plan_table.get_container",
            lambda: SimpleNamespace(plan_repo=repo),
        )
        table = PlanTable()
        model = PlanTableModel(
            [{"id": 7, "product_name": "渡鸦级", "status": "pending", "notes": "", "char_name": "甲"}]
        )
        table.set_model(model)
        return table, model, repo, COL_NOTES

    def test_notes_edit_writes_to_repo(self, qapp, monkeypatch):
        table, model, repo, col = self._table(monkeypatch)

        assert table.commit_cell_edit(0, col, "改后备注") is True

        repo.update.assert_called_once_with(7, notes="改后备注")

    def test_notes_edit_does_not_trigger_reload(self, qapp, monkeypatch):
        """落库不做整表重载 —— 否则 load_plans → set_plans(重置模型)
        会让每次改备注都全表重载，并打断正在进行的编辑。"""
        table, model, repo, col = self._table(monkeypatch)
        reloads: list = []
        table.plan_updated.connect(lambda: reloads.append(True))

        table.commit_cell_edit(0, col, "x")

        assert reloads == []

    def test_other_editable_column_not_persisted(self, qapp, monkeypatch):
        """本轮只修备注列：人物/设施列内联编辑仍不落库（另开一轮处理）。

        它们改完需要重算派生指标（走 `_edit_plan` 那条会调 `calculate_plan_metrics`
        的路径），单靠 setData 落库会留下与指标不一致的行。
        """
        table, model, repo, _col = self._table(monkeypatch)

        assert table.commit_cell_edit(0, 8, "乙") is True  # 人物列：内存生效
        assert model.get_plan(0)["char_name"] == "乙"

        repo.update.assert_not_called()

    def test_invalid_cell_edit_returns_false(self, qapp, monkeypatch):
        """不可编辑的列（非 _EDITABLE_COLS）必须返回 False，QML 侧据此回滚显示。"""
        table, model, repo, _col = self._table(monkeypatch)

        assert table.commit_cell_edit(0, 3, "产品名不该能改") is False
        repo.update.assert_not_called()


# ── 批次 7.3：plan_table 的原生弹窗全部换掉 ──────────────────────────
#
# 这一批把 `plan_table.py` 里 19 处 `QMessageBox` 换成 `FMessageDialog`（护栏在
# `test_qml_message_dialog.py`）、4 处 `QInputDialog` 换成 `InputQmlDialog`、
# 原 `_batch_set_me_te` 里手搭的那块 `QDialog` 换成 `MeTeDialog.qml`。
# 这里只锁本文件特有的两件：**新对话框能干净加载**、**落库链路一字未改**。


def _spin(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _assert_quiet(make_dialog, label: str) -> None:
    """加载 + 布局不给 Qt 刷告警（与 `test_qml_dialogs._assert_loads_and_quiet` 同口径）。"""
    from pathlib import Path

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    caught: list[str] = []

    def _handler(mode, ctx, msg):
        internal = str(ctx.file).startswith("qrc:/qt-project.org/")
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) and not internal:
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")

    previous = qInstallMessageHandler(_handler)
    try:
        dialog = make_dialog()
        try:
            assert dialog.ok(), f"{label} 的 QML 没加载起来：" + "; ".join(str(e) for e in dialog._host.errors())
            _spin(200)
        finally:
            dialog.deleteLater()
            _spin(60)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, f"{label} 产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))


class _StubPlanModel:
    """`_batch_set_me_te` / `_add_notes` 只用到 `get_plan` 与 `layoutChanged`。"""

    def __init__(self, plans: list[dict]) -> None:
        from unittest.mock import MagicMock

        self._plans = plans
        self.layoutChanged = MagicMock()

    def get_plan(self, row: int) -> dict | None:
        return self._plans[row] if 0 <= row < len(self._plans) else None


def _holder(plans: list[dict]):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    return SimpleNamespace(
        _model=_StubPlanModel(plans),
        _rebuild_subitems=lambda: None,
        plan_updated=MagicMock(),
    )


def _fake_container(repo):
    from types import SimpleNamespace

    return lambda: SimpleNamespace(plan_repo=repo)


class TestMeTeDialog:
    """ME/TE 对话框：两根滑杆与两个数字框**双向**联动（原版是两条 valueChanged 互连）。

    用户路径用「改属性 + 发信号」精确模拟：`Slider.moved` 与 `SpinBox.valueModified`
    都只在用户操作时发，程序化赋值不发 —— 所以下面两条能分清方向，
    不会把「回填」误当成「用户操作」而假绿。
    """

    @staticmethod
    def _open(me: int = 0, te: int = 0, hint: str = ""):
        from ui_qml.bridge.me_te_dialog import MeTeBridge, MeTeQmlDialog

        dlg = MeTeQmlDialog(MeTeBridge(me, te, hint=hint))
        assert dlg.ok(), "MeTeDialog.qml 没加载起来：" + "; ".join(str(e) for e in dlg._host.errors())
        return dlg

    @staticmethod
    def _ctrl(dlg, name: str):
        from PySide6.QtCore import QObject

        item = dlg._host.rootObject().findChild(QObject, name)
        assert item is not None, f"MeTeDialog.qml 里找不到 {name}"
        return item

    @staticmethod
    def _drag(slider, value: int) -> None:
        """模拟用户拖动滑杆：改值 + 发 `moved`（QML 侧 `onMoved` 才会往桥上推）。

        这里发**信号对象**而不是 `QMetaObject.invokeMethod(slider, "moved")`：
        后者在 pre-commit 的隔离环境里过不了 mypy —— 那边 `types-PySide6` 的桩只声明了
        `member: bytes` 的重载，而**本地运行时只接受 `str`**（传 bytes 直接 `TypeError`）。
        两边对不上，发信号对象则既无桩问题、运行时也确定可用。
        """
        slider.setProperty("value", value)
        slider.moved.emit()

    @staticmethod
    def _edit(spin, value: int) -> None:
        """模拟用户改数字框：改值 + 发 `valueModified`（理由同 `_drag`）。"""
        spin.setProperty("value", value)
        spin.valueModified.emit()

    def test_loads_without_qml_warnings(self, qapp):
        from ui_qml.bridge.me_te_dialog import MeTeBridge, MeTeQmlDialog

        _assert_quiet(lambda: MeTeQmlDialog(MeTeBridge(3, 7, hint="已绑定产线的等级以蓝图为准")), "ME/TE 对话框")

    def test_initial_values_come_from_the_caller(self, qapp):
        dlg = self._open(4, 12)
        try:
            assert dlg.bridge.meValue == 4
            assert dlg.bridge.teValue == 12
            assert self._ctrl(dlg, "meSlider").property("value") == 4
            assert self._ctrl(dlg, "teSpin").property("value") == 12
        finally:
            dlg.deleteLater()

    def test_bridge_pushes_to_both_controls(self, qapp):
        dlg = self._open(4, 12)
        try:
            dlg.bridge.setMe(9)
            dlg.bridge.setTe(2)
            assert self._ctrl(dlg, "meSlider").property("value") == 9
            assert self._ctrl(dlg, "meSpin").property("value") == 9
            assert self._ctrl(dlg, "teSlider").property("value") == 2
            assert self._ctrl(dlg, "teSpin").property("value") == 2
        finally:
            dlg.deleteLater()

    def test_dragging_the_slider_moves_the_spin_box(self, qapp):
        """拖滑杆 → 桥 → 数字框跟着走。"""
        dlg = self._open(0, 0)
        try:
            self._drag(self._ctrl(dlg, "meSlider"), 6)
            assert dlg.bridge.meValue == 6
            assert self._ctrl(dlg, "meSpin").property("value") == 6

            self._drag(self._ctrl(dlg, "teSlider"), 15)
            assert dlg.bridge.teValue == 15
            assert self._ctrl(dlg, "teSpin").property("value") == 15
        finally:
            dlg.deleteLater()

    def test_editing_the_spin_box_moves_the_slider(self, qapp):
        """改数字框 → 桥 → 滑杆跟着走。

        先拖一次滑杆再改数字框：这就是「绑定写法会静默失效」的那个形态
        （第一次拖动会摘掉滑杆上的 value 绑定），故专门锁一遍。
        """
        dlg = self._open(0, 0)
        try:
            self._drag(self._ctrl(dlg, "meSlider"), 6)  # 先拖一次
            self._edit(self._ctrl(dlg, "meSpin"), 2)
            assert dlg.bridge.meValue == 2
            assert self._ctrl(dlg, "meSlider").property("value") == 2

            self._edit(self._ctrl(dlg, "teSpin"), 19)
            assert dlg.bridge.teValue == 19
            assert self._ctrl(dlg, "teSlider").property("value") == 19
        finally:
            dlg.deleteLater()

    def test_values_are_clamped_to_the_original_ranges(self, qapp):
        """ME 0..10 / TE 0..20 —— 与原版 `setRange` 一致（越界由桥钳住）。"""
        dlg = self._open(0, 0)
        try:
            dlg.bridge.setMe(99)
            dlg.bridge.setTe(99)
            assert dlg.bridge.result() == (10, 20)
            dlg.bridge.setMe(-5)
            assert dlg.bridge.result() == (0, 20)
        finally:
            dlg.deleteLater()

    def test_ask_returns_none_when_cancelled(self, qapp, monkeypatch):
        """取消 / Esc / 关窗都必须是 None —— 给成 `(0, 0)` 就是「点关闭反而把 ME 清成 0」。"""
        from ui_qml.bridge import me_te_dialog as mtd

        class _Rejecting(mtd.MeTeQmlDialog):
            def exec(self) -> int:
                return 0  # QDialog.DialogCode.Rejected

        monkeypatch.setattr(mtd, "MeTeQmlDialog", _Rejecting)
        assert mtd.MeTeQmlDialog.ask(None, 3, 7) is None


class TestBatchSetMeTe:
    """`PlanTable._batch_set_me_te`：取值走新对话框，落库链路一字未改。"""

    @staticmethod
    def _patch_ask(monkeypatch, reply):
        seen: dict = {}

        def _fake(parent, me, te, *, hint=""):
            seen.update(parent=parent, me=me, te=te, hint=hint)
            return reply

        monkeypatch.setattr("ui_qml.bridge.me_te_dialog.MeTeQmlDialog.ask", staticmethod(_fake))
        return seen

    def test_writes_the_picked_values(self, qapp, monkeypatch):
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        repo = MagicMock()
        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(repo))
        seen = self._patch_ask(monkeypatch, (5, 12))

        plans = [
            {"id": 7, "me_level": 1, "te_level": 2},
            {"id": 8, "me_level": 3, "te_level": 4},
        ]
        holder = _holder(plans)
        PlanTable._batch_set_me_te(holder, [0, 1])

        assert (seen["me"], seen["te"]) == (1, 2), "首行的当前值要作为对话框初值"
        assert seen["hint"] == "", "未绑产线时不显示那条说明"
        assert [p["me_level"] for p in plans] == [5, 5]
        assert [p["te_level"] for p in plans] == [12, 12]
        repo.update_many.assert_called_once_with([7, 8], me_level=5, te_level=12)
        holder.plan_updated.emit.assert_called_once()

    def test_hint_when_the_first_row_has_bound_blueprints(self, qapp, monkeypatch):
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(MagicMock()))
        seen = self._patch_ask(monkeypatch, (0, 0))
        holder = _holder([{"id": 7, "bound_blueprint_ids": [11]}])

        PlanTable._batch_set_me_te(holder, [0])

        assert "未绑定" in seen["hint"], "已绑产线的计划要说清这里只影响未绑定的产线"

    def test_cancel_changes_nothing(self, qapp, monkeypatch):
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        repo = MagicMock()
        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(repo))
        self._patch_ask(monkeypatch, None)

        plans = [{"id": 7, "me_level": 1, "te_level": 2}]
        holder = _holder(plans)
        PlanTable._batch_set_me_te(holder, [0])

        assert (plans[0]["me_level"], plans[0]["te_level"]) == (1, 2)
        repo.update_many.assert_not_called()
        holder.plan_updated.emit.assert_not_called()


class TestMultilineInputDialog:
    """`InputQmlDialog.get_multiline_text` —— 批次 7.3 给「添加备注」补的多行模式。"""

    def test_loads_without_qml_warnings(self, qapp):
        from ui_qml.bridge.input_dialog import MODE_MULTILINE, InputBridge, InputQmlDialog

        _assert_quiet(
            lambda: InputQmlDialog(InputBridge("添加备注", "输入备注内容:", MODE_MULTILINE, text="旧备注")),
            "多行取值对话框",
        )

    def test_editing_writes_through_and_accept_returns_it(self, qapp):
        """换行要能留在文本里（单行模式做不到 —— 这正是补这一档的理由）。"""
        from PySide6.QtCore import QObject

        from ui_qml.bridge.input_dialog import MODE_MULTILINE, InputBridge, InputQmlDialog

        dlg = InputQmlDialog(InputBridge("添加备注", "输入备注内容:", MODE_MULTILINE, text="旧备注"))
        try:
            assert dlg.ok(), "InputDialog.qml 没加载起来：" + "; ".join(str(e) for e in dlg._host.errors())
            area = dlg._host.rootObject().findChild(QObject, "inputMultilineArea")
            assert area is not None, "多行模式下要显示 TextArea"
            assert area.property("text") == "旧备注", "初始文本要铺进去"

            area.setProperty("text", "第一行\n第二行")
            dlg.bridge.accept()
            assert dlg.bridge.text_value() == "第一行\n第二行"
        finally:
            dlg.deleteLater()

    def test_single_line_mode_still_uses_the_old_field(self, qapp):
        """单行模式不能被多行那块顶掉（`mode` 决定显示哪个控件）。"""
        from PySide6.QtCore import QObject

        from ui_qml.bridge.input_dialog import MODE_TEXT, InputBridge, InputQmlDialog

        dlg = InputQmlDialog(InputBridge("标题", "标签", MODE_TEXT, text="甲"))
        try:
            root = dlg._host.rootObject()
            field = root.findChild(QObject, "inputText")
            area = root.findChild(QObject, "inputMultiline")
            assert field is not None and field.property("text") == "甲"
            assert area is not None and area.property("visible") is False
        finally:
            dlg.deleteLater()


class TestPlanTableInputDialogs:
    """`plan_table.py` 四处 `QInputDialog` 的替换点：备注（多行）与流程/并行数。"""

    def test_add_notes_uses_the_multiline_dialog(self, qapp, monkeypatch):
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        repo = MagicMock()
        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(repo))
        seen: dict = {}

        def _fake(parent, title, label, text=""):
            seen.update(title=title, label=label, text=text)
            return ("第一行\n第二行", True)

        monkeypatch.setattr("ui_qml.bridge.input_dialog.InputQmlDialog.get_multiline_text", staticmethod(_fake))

        plan = {"id": 7, "notes": "旧备注"}
        holder = _holder([plan])
        PlanTable._add_notes(holder, 0)

        assert seen["title"] == "添加备注"
        assert seen["text"] == "旧备注", "已有备注要作为初值"
        assert plan["notes"] == "第一行\n第二行"
        repo.update.assert_called_once_with(7, notes="第一行\n第二行")

    def test_add_notes_cancel_keeps_the_old_text(self, qapp, monkeypatch):
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        repo = MagicMock()
        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(repo))
        monkeypatch.setattr(
            "ui_qml.bridge.input_dialog.InputQmlDialog.get_multiline_text",
            staticmethod(lambda *a, **k: ("", False)),
        )

        plan = {"id": 7, "notes": "旧备注"}
        holder = _holder([plan])
        PlanTable._add_notes(holder, 0)

        assert plan["notes"] == "旧备注"
        repo.update.assert_not_called()

    def test_modify_runs_uses_the_int_dialog(self, qapp, monkeypatch):
        """流程数：范围与调用参数（1..99999）一字未改，只换了弹窗实现。"""
        from unittest.mock import MagicMock

        from ui_pyside6.views.industry.plan_table import PlanTable

        repo = MagicMock()
        monkeypatch.setattr("ui_pyside6.views.industry.plan_table.get_container", _fake_container(repo))
        seen: dict = {}

        def _fake(parent, title, label, value=0, minimum=0, maximum=0, step=1):
            seen.update(title=title, value=value, minimum=minimum, maximum=maximum)
            return (10, True)

        monkeypatch.setattr("ui_qml.bridge.input_dialog.InputQmlDialog.get_int", staticmethod(_fake))

        plan = {"id": 7, "runs": 5, "calculated_time": 100, "daily_output": 20}
        holder = _holder([plan])
        PlanTable._modify_runs(holder, 0)

        assert seen == {"title": "修改流程数", "value": 5, "minimum": 1, "maximum": 99999}
        assert plan["runs"] == 10
        assert plan["calculated_time"] == 200  # 按比值即时更新
        repo.update.assert_called_once_with(7, runs=10)


def test_plan_table_has_no_native_dialogs_left():
    """批次 7.3 的判据：`plan_table.py` 里 `QMessageBox` / `QInputDialog` 计数为 0。"""
    from pathlib import Path

    import ui_pyside6.views.industry.plan_table as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "QMessageBox" not in source
    assert "QInputDialog" not in source

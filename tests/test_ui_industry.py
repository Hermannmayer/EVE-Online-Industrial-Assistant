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
    monkeypatch.setattr("ui_pyside6.views.char_settings_view.services_get_character_list", lambda: ["甲"])

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
    """验证 IndustryPage 初始化后关键部件存在。

    阶段 2b 起整页由 QML 渲染：五个 Widgets 子控件换成一个 `PageHost` +
    `IndustryBridge`，业务控制器 `_plan_table_widget`（headless）照旧保留。
    """
    assert industry_page is not None
    assert hasattr(industry_page, "_host")
    assert hasattr(industry_page, "_bridge")
    assert hasattr(industry_page, "_plan_table_widget")
    assert industry_page._host.ok(), "IndustryPage.qml 加载失败"


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

        from ui_pyside6.models.industry_models import PlanTableModel
        from ui_pyside6.views.industry.plan_table import PlanTable
        from ui_pyside6.views.industry.plan_table_constants import COL_NOTES

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

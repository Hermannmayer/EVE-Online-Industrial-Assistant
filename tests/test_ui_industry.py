import pytest

pytestmark = pytest.mark.ui

"""IndustryPage UI 测试。"""


def test_plan_edit_dialog_batch_sync_gating(industry_page, monkeypatch):
    """批量编辑弹窗：默认不同步流程/并行（复选未勾 → None → 调用方不写库），勾选后返回 spin 值。"""
    from services import inventory_manager
    from ui_pyside6.views.industry.plan_edit_dialog import PlanEditDialog

    monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
    monkeypatch.setattr("ui_pyside6.views.char_settings_view.services_get_character_list", lambda: ["甲"])

    dlg = PlanEditDialog(
        industry_page,
        {"_selected_rows": [1, 2], "runs": 5, "parallels": 3},
        batch_mode=True,
        row_count=2,
    )
    try:
        data = dlg.get_updated_data()
        assert data["runs"] is None
        assert data["parallels"] is None

        dlg._sync_runs_cb.setChecked(True)
        data2 = dlg.get_updated_data()
        assert data2["runs"] == 5
        assert data2["parallels"] == 3
    finally:
        dlg.deleteLater()

    # 单行模式不受复选影响，始终返回 spin 值
    single = PlanEditDialog(industry_page, {"runs": 2, "parallels": 1})
    try:
        s = single.get_updated_data()
        assert s["runs"] == 2
        assert s["parallels"] == 1
    finally:
        single.deleteLater()


def test_industry_page_init(industry_page):
    """验证 IndustryPage 初始化后关键组件存在。"""
    assert industry_page is not None
    assert hasattr(industry_page, "_toolbar")
    assert hasattr(industry_page, "_plan_table_widget")
    assert hasattr(industry_page, "_view_stack")
    assert hasattr(industry_page, "_gantt_view")
    assert hasattr(industry_page, "_status_bar")
    assert hasattr(industry_page, "_action_buttons")


def test_industry_page_default_view(industry_page):
    """验证默认视图索引为 0（数据表格视图）。"""
    assert industry_page._view_stack.currentIndex() == 0


def test_industry_page_view_switch(industry_page):
    """验证视图切换（0=数据表格，1=甘特图）。"""
    industry_page._view_stack.setCurrentIndex(1)
    assert industry_page._view_stack.currentIndex() == 1
    industry_page._view_stack.setCurrentIndex(0)
    assert industry_page._view_stack.currentIndex() == 0


def test_industry_page_save_restore_state(industry_page):
    """验证保存/恢复页面状态。"""
    state = industry_page.save_state()
    assert "v_scroll" in state

    industry_page.restore_state(state)
    # 恢复后不崩溃即可


def test_industry_page_plan_count_label(industry_page):
    """验证计划计数标签存在。"""
    assert hasattr(industry_page, "_plan_count")
    assert industry_page._plan_count.text() is not None


def test_procurement_summary_reruns_on_price_change(industry_page, monkeypatch):
    """改价格设置（Hub / 卖价买价 / 倍率）后必须重算汇总，不能命中指纹缓存回吐旧值。

    回归用例：旧指纹只含计划字段，改价格后 `fp == self._proc_fp` 直接命中缓存返回，
    红框「备料中采购」数字永远不动 —— 用户报的「写死的」。

    刻意不碰真实控件：真改控件会经 `price_setting_changed → load_plans()` 触发真实刷新，
    且 `top_toolbar._save_price_settings()` 会写 `data/settings.json`。
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
    monkeypatch.setattr(industry_page._toolbar, "get_price_settings", lambda: dict(settings))

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
    monkeypatch.setattr(industry_page._toolbar, "get_price_settings", lambda: dict(settings))

    plan = {"id": 1, "materials_ready": 1, "status": "pending", "runs": 1, "parallels": 1, "me_level": 0}

    industry_page._refresh_procurement_summary([plan])
    industry_page._proc_result = (100.0, 1.0)
    industry_page._refresh_procurement_summary([plan])
    assert len(started) == 1, "计划与价格都未变时不应重复查询"

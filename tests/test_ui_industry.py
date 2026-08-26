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

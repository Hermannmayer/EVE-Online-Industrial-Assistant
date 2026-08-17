import pytest

pytestmark = pytest.mark.ui

"""IndustryPage UI 测试。"""


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

import pytest

pytestmark = pytest.mark.ui

"""InventoryPage UI 测试。"""


def test_inventory_page_init(inventory_page):
    """验证 InventoryPage 初始化后关键组件存在。"""
    assert inventory_page is not None
    assert hasattr(inventory_page, "_hangar_combo")
    assert hasattr(inventory_page, "_tabs")
    # 机库增删改已统一收拢到底部「机库设置」对话框，本页不再保留管理按钮
    assert not hasattr(inventory_page, "_new_h_btn")
    assert not hasattr(inventory_page, "_rename_h_btn")
    assert not hasattr(inventory_page, "_del_h_btn")


def test_inventory_page_tab_switch(inventory_page):
    """验证标签页切换。"""
    assert inventory_page._tabs.count() >= 2
    inventory_page._tabs.setCurrentIndex(1)
    assert inventory_page._tabs.currentIndex() == 1
    inventory_page._tabs.setCurrentIndex(0)
    assert inventory_page._tabs.currentIndex() == 0


def test_inventory_page_save_restore_state(inventory_page):
    """验证保存/恢复页面状态。"""
    state = inventory_page.save_state()
    assert "tab_index" in state
    # hangar_index 仅在机库列表非空时存在
    if inventory_page._hangar_combo.count() > 0:
        assert "hangar_index" in state

    inventory_page.restore_state(state)
    # 恢复后不崩溃即可

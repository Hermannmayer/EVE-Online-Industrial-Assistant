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


def test_blueprint_sort_survives_rebuild(inventory_page):
    """加计划/过滤后重建模型不得丢排序（此前 _apply_filter 直接 setModel，行序回退为原始顺序）。"""
    from PySide6.QtCore import Qt

    tab = inventory_page._blueprint_tab
    natural = [
        {
            "id": i,
            "blueprint_type_id": 3000 + i,
            "product_type_id": 2000 + i,
            "zh_name": f"蓝图{i}",
            "product_name": f"产物{i}",
            "me_level": me,
            "te_level": 0,
            "runs": 1,
            "is_bpo": True,
            "is_reaction": False,
            "tech_level": 1,
        }
        for i, me in enumerate([5, 1, 3])
    ]

    tab._all_rows = [dict(r) for r in natural]
    tab._apply_filter()
    assert [r["me_level"] for r in tab._bp_model._rows] == [5, 1, 3]

    tab._bp_table.horizontalHeader().setSortIndicator(3, Qt.SortOrder.AscendingOrder)  # 材料等级升序
    assert [r["me_level"] for r in tab._bp_model._rows] == [1, 3, 5]

    # 模拟 _load_blueprints：重新灌入一份自然序数据再重建（模型排序会原地改动 _all_rows）
    tab._all_rows = [dict(r) for r in natural]
    tab._apply_filter()
    assert [r["me_level"] for r in tab._bp_model._rows] == [1, 3, 5]
    assert tab._bp_table.horizontalHeader().sortIndicatorSection() == 3


def test_hangar_sort_survives_refresh(inventory_page):
    """机库页同理：增量粘贴/移库/切页后重建模型不得丢排序。"""
    from unittest.mock import patch

    from PySide6.QtCore import Qt

    tab = inventory_page._hangar_tab
    inventory_page._current_hangar_id = 1
    items = [
        {"id": i, "type_id": 30 + i, "quantity": qty, "cost_price": 0, "display_name": f"物品{i}"}
        for i, qty in enumerate([5, 1, 3])
    ]
    target = "ui_pyside6.views.inventory.hangar_tab.get_items"

    with patch(target, return_value=[dict(it) for it in items]):
        tab._refresh()
    assert [it["quantity"] for it in tab._model._items] == [5, 1, 3]

    tab._table.horizontalHeader().setSortIndicator(2, Qt.SortOrder.AscendingOrder)  # 库存数量升序
    assert [it["quantity"] for it in tab._model._items] == [1, 3, 5]

    with patch(target, return_value=[dict(it) for it in items]):
        tab._refresh()
    assert [it["quantity"] for it in tab._model._items] == [1, 3, 5]

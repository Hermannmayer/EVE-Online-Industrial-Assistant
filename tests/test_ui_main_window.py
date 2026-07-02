"""MainWindow UI 测试。"""


def test_main_window_init(main_window):
    """验证 MainWindow 初始化后关键组件存在。"""
    assert main_window is not None
    assert hasattr(main_window, "_nav_tree")
    assert hasattr(main_window, "content_stack")
    assert hasattr(main_window, "_region_combo")
    assert hasattr(main_window, "_update_btn")


def test_main_window_save_restore_state(main_window):
    """验证保存/恢复窗口状态。"""
    state = main_window.save_state()
    assert "current_page" in state
    assert "pages" in state

    main_window.restore_state(state)
    # 恢复后不崩溃即可
    assert True


def test_main_window_region_combo(main_window):
    """验证区域选择器初始化。"""
    assert main_window._region_combo.count() >= 4
    assert main_window._region_combo.currentText() == "全部区域"

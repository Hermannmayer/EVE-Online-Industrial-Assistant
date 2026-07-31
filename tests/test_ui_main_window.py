from unittest.mock import patch

import pytest

from core.constants import TRADE_HUBS
from ui_pyside6.main_window import MainWindow

pytestmark = pytest.mark.slow

"""MainWindow UI 测试。"""


def test_main_window_init(main_window):
    """验证 MainWindow 初始化后关键组件存在。"""
    assert main_window is not None
    assert hasattr(main_window, "_nav_tree")
    assert hasattr(main_window, "content_stack")
    assert hasattr(main_window, "_region_menu_btn")
    assert hasattr(main_window, "_update_btn")
    assert hasattr(main_window, "_price_age_label")
    assert hasattr(main_window, "_auto_update_btn")


def test_main_window_save_restore_state(main_window):
    """验证保存/恢复窗口状态。"""
    state = main_window.save_state()
    assert "current_page" in state
    assert "pages" in state

    main_window.restore_state(state)
    # 恢复后不崩溃即可
    assert True


def test_region_menu_btn(main_window):
    """区域勾选下拉：独立控件，菜单覆盖全部贸易中心。"""
    assert hasattr(main_window, "_region_menu_btn")
    menu = main_window._region_menu_btn.menu()
    assert menu is not None
    assert set(main_window._region_actions) == set(TRADE_HUBS)


def test_update_btn_is_plain(main_window):
    """更新价格按钮为纯按钮（无下拉菜单）。"""
    assert main_window._update_btn.menu() is None


def test_load_update_regions_default_jita(qapp):
    """settings 无 update_regions 时默认仅 Jita。"""
    with (
        patch("ui_pyside6.main_window.search_history_file", return_value="C:/nonexistent_eve_settings.json"),
        patch.object(MainWindow, "_init_price_check", lambda self: None),
        patch.object(MainWindow, "_register_pages", lambda self: None),
        patch.object(MainWindow, "setStyleSheet", lambda self, x: None),
    ):
        window = MainWindow()
        assert window._update_regions == ["Jita"]
        window.close()


def test_load_update_regions_from_settings(qapp, tmp_path):
    """从 settings.json 读取勾选的更新区域。"""
    settings = tmp_path / "settings.json"
    settings.write_text('{"update_regions": ["Jita", "Hek"]}', encoding="utf-8")
    with (
        patch("ui_pyside6.main_window.search_history_file", return_value=str(settings)),
        patch.object(MainWindow, "_init_price_check", lambda self: None),
        patch.object(MainWindow, "_register_pages", lambda self: None),
        patch.object(MainWindow, "setStyleSheet", lambda self, x: None),
    ):
        window = MainWindow()
        assert window._update_regions == ["Jita", "Hek"]
        window.close()


def test_region_toggle_saves(qapp):
    """勾选变化会更新 _update_regions 并保存设置。"""
    with (
        patch.object(MainWindow, "_load_update_regions", return_value=["Jita", "Hek"]),
        patch.object(MainWindow, "_init_price_check", lambda self: None),
        patch.object(MainWindow, "_register_pages", lambda self: None),
        patch.object(MainWindow, "setStyleSheet", lambda self, x: None),
    ):
        window = MainWindow()
        with patch.object(window, "_save_settings") as save:
            # trigger() 对 checkable QAction 会自动切换勾选状态并发出 triggered
            window._region_actions["Hek"].trigger()
            assert window._update_regions == ["Jita"]
            save.assert_called_once()
        window.close()


# ══════════════════════════════════════
#  自动更新状态指示
# ══════════════════════════════════════


def test_auto_update_indicator(main_window):
    """顶栏自动更新指示存在、可勾选且有文本。"""
    assert hasattr(main_window, "_auto_update_btn")
    assert main_window._auto_update_btn.isCheckable()
    assert main_window._auto_update_btn.text() != ""


def test_auto_update_indicator_toggles(main_window):
    """点击自动更新指示翻转 _auto_update_enabled（不写真实 settings 文件）。"""
    with patch.object(main_window, "_save_settings"):
        before = main_window._auto_update_enabled
        main_window._auto_update_btn.setChecked(not before)
        assert main_window._auto_update_enabled is (not before)
        assert main_window._auto_update_btn.isChecked() is (not before)


# ══════════════════════════════════════
#  价格年龄标签 — 细粒度定时刷新
# ══════════════════════════════════════


def test_price_age_timer_created(main_window):
    """价格年龄标签有独立定时器并已启动（60 秒刷新一次）。"""
    assert hasattr(main_window, "_price_age_timer")
    assert main_window._price_age_timer.isActive()
    assert main_window._price_age_timer.interval() == 60 * 1000


def test_refresh_price_time_updates_label(qapp, temp_db):
    """refresh_price_time 用最新 fetch_time 重算"X分钟前"相对时间标签。"""
    with (
        patch("ui_pyside6.main_window.get_container") as mock_cont,
        patch.object(MainWindow, "_init_price_check", lambda self: None),
    ):
        mock_cont.return_value.db = temp_db
        window = MainWindow()
        window.refresh_price_time()
        assert "分钟前" in window._price_age_label.text()
        window.close()

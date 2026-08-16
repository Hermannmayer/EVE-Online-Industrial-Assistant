"""主窗口单元测试 — MainWindow 状态管理 + NAV_TREE + 辅助方法

测试覆盖:
  - NAV_TREE 导航定义完整性
  - save_state / restore_state 状态序列化
  - PriceUpdateWorker / PriceCheckWorker 异常处理
  - 系统托盘 / 主题切换辅助方法
"""

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt

from ui_pyside6.main_window import MainWindow
from ui_pyside6.main_window_nav import NAV_TREE
from ui_pyside6.workers.main_window_workers import (
    PriceCheckWorker,
    PriceUpdateWorker,
    needs_price_update,
)

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _cleanup_windows():
    """测试中创建的 MainWindow 结束后自动 close。

    MainWindow 构造会注册全局 theme listener（main_window.py:258）并启动后台
    线程；不 close 的 window 会残留，触发后续测试（theme 测试 apply_theme 调用
    残留 listener 卡住 / 后台线程与 Qt 清理冲突 segfault）。closeEvent 会移除
    listener 并停止价格线程，故统一在此清理。
    """
    created: list[MainWindow] = []
    orig_init = MainWindow.__init__

    def _tracked_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created.append(self)

    MainWindow.__init__ = _tracked_init
    yield
    MainWindow.__init__ = orig_init
    for w in created:
        w.close()


# ══════════════════════════════════════
#  NAV_TREE — 导航定义
# ══════════════════════════════════════


class TestNavTree:
    """导航树结构定义"""

    def test_nav_tree_structure(self):
        """NAV_TREE 应为元组列表"""
        assert isinstance(NAV_TREE, list)
        assert len(NAV_TREE) > 0

    def test_section_entries_have_correct_format(self):
        """分组标题格式正确"""
        sections = [e for e in NAV_TREE if e[0] == "__section__"]
        assert len(sections) >= 1
        for sec in sections:
            assert len(sec) == 2
            assert sec[0] == "__section__"
            assert isinstance(sec[1], str)

    def test_nav_entries_have_correct_format(self):
        """导航项格式正确"""
        nav_items = [e for e in NAV_TREE if e[0] != "__section__"]
        assert len(nav_items) >= 5  # 至少5个核心功能
        for item in nav_items:
            assert len(item) == 3 or len(item) == 4
            assert isinstance(item[0], str)  # key
            assert isinstance(item[1], str)  # label

    def test_has_essential_pages(self):
        """应包含所有必要页面"""
        keys = {e[0] for e in NAV_TREE if e[0] != "__section__"}
        essential = {"estimate", "query", "industry", "trade", "watchlist", "storage"}
        assert essential.issubset(keys), f"缺少页面: {essential - keys}"

    def test_no_duplicate_keys(self):
        """不应有重复的导航 key"""
        keys = [e[0] for e in NAV_TREE if e[0] != "__section__"]
        assert len(keys) == len(set(keys))


# ══════════════════════════════════════
#  PriceUpdateWorker
# ══════════════════════════════════════


class TestPriceUpdateWorker:
    """价格更新后台线程"""

    def test_worker_can_be_created(self, qapp):
        """可构造 Worker 实例"""
        worker = PriceUpdateWorker()
        assert worker is not None


# ══════════════════════════════════════
#  PriceCheckWorker
# ══════════════════════════════════════


class TestPriceCheckWorker:
    """价格时效检查后台线程"""

    def test_default_interval(self, qapp):
        """默认检查间隔 30 分钟"""
        worker = PriceCheckWorker()
        assert worker._interval == 30 * 60

    def test_custom_interval(self, qapp):
        """自定义检查间隔"""
        worker = PriceCheckWorker(interval_minutes=60)
        assert worker._interval == 60 * 60

    def test_fresh_data_no_update(self, qapp):
        """数据未到（间隔-60s）不需要更新"""
        assert needs_price_update(5 * 60, 30) is False  # 5 分钟前
        assert needs_price_update(28 * 60, 30) is False  # 28 分钟（容差窗口内）

    def test_stale_data_triggers_update(self, qapp):
        """数据 ≥ 间隔-60s 触发更新（消除严格 > 导致的 2× 周期跳过）"""
        assert needs_price_update(30 * 60, 30) is True  # 正好 30 分钟（旧实现会跳过）
        assert needs_price_update(29 * 60 + 5, 30) is True  # 29:05 分钟
        assert needs_price_update(56 * 60, 30) is True  # 用户观察到的 56 分钟

    def test_interval_edge(self, qapp):
        """其它间隔：容差为 60s"""
        assert needs_price_update(10 * 60, 10) is True  # 10 分钟正好到点
        assert needs_price_update(9 * 60 + 30, 10) is True  # 9:30
        assert needs_price_update(8 * 60, 10) is False  # 8 分钟（容差窗口内）


# ══════════════════════════════════════
#  MainWindow — save_state / restore_state
# ══════════════════════════════════════


class TestMainWindowState:
    """主窗口状态序列化"""

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    def test_save_state_returns_dict(self, qapp):
        """save_state 返回字典"""
        window = MainWindow()
        try:
            state = window.save_state()
            assert isinstance(state, dict)
            assert "version" in state
            assert "current_page" in state
            assert "pages" in state
        finally:
            window.close()

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    def test_save_state_version(self, qapp):
        """save_state 版本号为 1"""
        window = MainWindow()
        try:
            state = window.save_state()
            assert state["version"] == 1
        finally:
            window.close()

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    def test_pin_button_toggles_window_stays_on_top(self, qapp):
        """置顶按钮切换 → 非 Windows 平台 windowFlags 含 WindowStaysOnTopHint，并持久化"""
        import os

        if os.name == "nt":
            return  # Windows 走 SetWindowPos，不设 windowFlags
        window = MainWindow()
        try:
            assert not window._pin_btn.isChecked()
            window._pin_btn.setChecked(True)
            assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            assert window._load_window_pin() is True
            window._pin_btn.setChecked(False)
            assert not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            assert window._load_window_pin() is False
        finally:
            window.close()

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    @patch.object(MainWindow, "_init_price_check", lambda self: None)
    @patch.object(MainWindow, "setStyleSheet", lambda self, x: None)
    def test_restore_state_empty(self, qapp):
        """restore_state 空数据不崩溃"""
        window = MainWindow()
        window.restore_state({})  # 不应报错

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    @patch.object(MainWindow, "_init_price_check", lambda self: None)
    @patch.object(MainWindow, "setStyleSheet", lambda self, x: None)
    def test_restore_state_none(self, qapp):
        """restore_state None 不崩溃"""
        window = MainWindow()
        window.restore_state(None)  # 不应报错

    @patch.object(MainWindow, "_register_pages", lambda self: None)
    @patch.object(MainWindow, "_init_price_check", lambda self: None)
    @patch.object(MainWindow, "setStyleSheet", lambda self, x: None)
    def test_restore_state_unknown_key_ignored(self, qapp):
        """restore_state 未知页面 key 被忽略"""
        window = MainWindow()
        window.restore_state({"current_page": "nonexistent"})  # 不应报错


# ══════════════════════════════════════
#  MainWindow — 辅助方法
# ══════════════════════════════════════


class TestMainWindowHelpers:
    """MainWindow 辅助方法"""

    def test_show_progress_sets_label(self, qapp):
        """show_progress 设置状态文本"""
        window = MainWindow()
        window.show_progress("测试处理")
        assert window._status_label.text() == "测试处理"

    def test_hide_progress_resets_label(self, qapp):
        """hide_progress 重置状态文本"""
        window = MainWindow()
        window.show_progress("处理中...")
        window.hide_progress("完成")
        assert window._status_label.text() == "完成"

    def test_toggle_theme_changes_current(self, qapp):
        """_toggle_theme 切换主题"""
        import ui_pyside6.theme as theme

        old_theme = theme.current_theme()
        window = MainWindow()

        # 避免样式表错误
        with patch.object(window, "setStyleSheet"):
            window._toggle_theme()
            new_theme = theme.current_theme()
            assert new_theme != old_theme

        # 恢复
        window._toggle_theme()
        assert theme.current_theme() == old_theme


# ══════════════════════════════════════
#  MainWindow — 图标绘制
# ══════════════════════════════════════


class TestMainWindowIcons:
    """图标创建"""

    def test_create_person_icon_returns_qicon(self, qapp):
        """_create_person_icon 返回 QIcon"""
        window = MainWindow()
        icon = window._create_person_icon()
        from PySide6.QtGui import QIcon

        assert isinstance(icon, QIcon)

    def test_create_settings_icon_returns_qicon(self, qapp):
        """_create_settings_icon 返回 QIcon"""
        window = MainWindow()
        icon = window._create_settings_icon()
        from PySide6.QtGui import QIcon

        assert isinstance(icon, QIcon)

    def test_create_person_icon_custom_size(self, qapp):
        """自定义尺寸"""
        window = MainWindow()
        icon = window._create_person_icon(size=32)
        assert icon is not None
        assert not icon.isNull()

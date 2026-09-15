"""主题监听器支持测试

验证各页面/对话框在主题切换后能正确重新应用内联样式表。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QShowEvent

import ui_pyside6.theme as theme
from ui_pyside6.theme import FLUENT_LIGHT, apply_theme
from ui_qml.bridge import theme_singleton

pytestmark = pytest.mark.ui


class _FakeModel(QAbstractItemModel):
    def index(self, row, col, parent=None):
        return self.createIndex(row, col)

    def parent(self, index):
        return QModelIndex()

    def rowCount(self, parent=None):
        return 0

    def columnCount(self, parent=None):
        return 0

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        return None


class _FakeProxy(QSortFilterProxyModel):
    """用于 QTableView.setModel 的最小代理模型"""


@pytest.fixture(autouse=True)
def reset_theme():
    yield
    apply_theme("dark")


def _wait():
    QCoreApplication.processEvents()


# ── 已验证通过：import theme as module 后主题切换正确传播 ──


def test_industry_page_theme_listener(qapp, mock_db):
    """工业页已整页迁 QML（阶段 2b）：主题由 QML 绑定 `Theme` 单例跟随，
    不再走 QSS + `_on_theme_changed` 那条路。

    所以这里改成守两件事：页面确实挂上了 QML 宿主，且切主题不炸。
    （QML 侧的 token 有效性由 test_qml_theme_bridge 的静态扫描覆盖。）
    """
    # mock_db 只 patch core.container.get_container，而 industry_view 通过
    # `from core.container import get_container` 绑定旧引用，patch 不生效；
    # 构造 IndustryPage 会触发后台重算 worker 访问真实容器写库（full 集合下暴露）。
    # 这里显式 patch industry_view.get_container，隔离真实 DB/容器。
    mock_cont = MagicMock()
    mock_mgr = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value = mock_cursor
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_conn)
    mock_cm.__exit__ = MagicMock(return_value=False)
    mock_mgr.connect.return_value = mock_cm
    mock_cont.db = mock_mgr
    mock_cont.plan_repo = MagicMock()

    with (
        patch("ui_pyside6.views.industry_view.init_plan_db"),
        patch("ui_pyside6.views.industry_view.get_container", return_value=mock_cont),
    ):
        from ui_pyside6.views.industry_view import IndustryPage

        page = IndustryPage(None)
        assert page._host.ok(), "IndustryPage.qml 加载失败"
        assert not hasattr(page, "_on_theme_changed"), "QSS 主题钩子应已随迁移移除"

        apply_theme("light")
        _wait()
        assert page._host.ok(), "切主题后页面不应失效"
        assert theme_singleton().themeId == "fluent-light"


def test_char_settings_dialog_show_event(qapp, mock_db):
    with (
        patch("ui_pyside6.views.char_settings_view.load_all_data") as mock_load,
        patch("ui_pyside6.views.char_settings_pages.load_implants", return_value=[]),
        patch("ui_pyside6.views.char_settings_view.save_all_data"),
    ):
        mock_load.return_value = {
            "current": "main",
            "characters": {"main": {"skills": {}, "implants": [None, None, None], "market": {}}},
        }
        from ui_pyside6.views.char_settings_view import CharSettingsDialog

        dlg = CharSettingsDialog()
        apply_theme("light")
        dlg.showEvent(QShowEvent())
        assert FLUENT_LIGHT["BG_DARK"] in dlg.styleSheet()


def test_listener_freed_after_object_gc():
    """对象销毁后监听器自动失效（弱引用）：
    1. 存活时收到通知；2. 销毁后 notify 不崩溃；3. 失效引用被清理
    """
    import gc

    n0 = len(theme._theme_listeners)

    class _Listener:
        def __init__(self):
            self.called = 0

        def on_theme(self):
            self.called += 1

    obj = _Listener()
    theme.add_theme_listener(obj.on_theme)
    assert len(theme._theme_listeners) == n0 + 1

    apply_theme("light")
    assert obj.called == 1, "存活对象应收到通知"

    del obj
    gc.collect()
    # 销毁后 notify 不应崩溃（弱引用失效被过滤）
    apply_theme("dark")

    # 自己的监听器应被清理；其他测试的监听器也可能被 GC 清理（数量只会减少）
    assert len(theme._theme_listeners) < n0 + 1, "对象销毁后其监听器应被移除"


def test_remove_theme_listener_still_works():
    """显式 remove 仍然有效（兼容旧调用方）"""

    class _Listener:
        def on_theme(self):
            pass

    obj = _Listener()
    theme.add_theme_listener(obj.on_theme)
    before = len(theme._theme_listeners)
    theme.remove_theme_listener(obj.on_theme)
    assert len(theme._theme_listeners) == before - 1


def test_add_theme_listener_accepts_lambda():
    """add_theme_listener 支持普通函数/lambda（WeakMethod 只接受绑定方法，否则会崩）"""

    calls = {"n": 0}

    def _cb():
        calls["n"] += 1

    remove = theme.add_theme_listener(_cb)  # 不再抛 TypeError

    apply_theme("light")
    assert calls["n"] == 1, "lambda 监听器应被调用"

    remove()
    apply_theme("dark")
    assert calls["n"] == 1, "remove 后不应再被调用"


# ── ThemeSelector 卡片选择器（原 test_theme_selector.py） ──

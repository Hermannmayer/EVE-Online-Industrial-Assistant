"""主题监听器支持测试

验证各页面/对话框在主题切换后能正确重新应用内联样式表。
"""

from unittest.mock import patch

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QShowEvent

import ui_qml.theme.registry as theme
from ui_qml.bridge import theme_singleton
from ui_qml.theme.registry import FLUENT_LIGHT, apply_theme

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


def test_industry_page_theme_listener(qapp, main_window):
    """工业页已整页迁 QML：主题由 QML 绑定 `Theme` 单例跟随，
    不再走 QSS + `_on_theme_changed` 那条路。

    ⚠️ 批次 7.4 起控制器是纯 `QObject`、**不再自建宿主**（`page._host` 已删），
    页面 Item 只存在于外壳的场景里 —— 所以这里从**外壳**取页面。
    守的性质没变：页面确实挂进了场景，且切主题不炸。
    （QML 侧的 token 有效性由 test_qml_theme_bridge 的静态扫描覆盖。）
    """
    main_window.navigate_to("industry")
    page = main_window._pages["industry"]
    assert page.item is not None, "工业页不是挂进场景的 QML Item"
    assert callable(getattr(page.hooks, "on_shown", None)), "外壳的 on_shown 钩子没接到控制器上"
    assert not hasattr(page.hooks, "_on_theme_changed"), "QSS 主题钩子应已随迁移移除"

    apply_theme("light")
    _wait()
    assert page.item is not None, "切主题后页面不应失效"
    assert theme_singleton().themeId == "fluent-light"


def test_char_settings_dialog_show_event(qapp, mock_db):
    with (
        patch("ui_pyside6.views.char_settings_view.services_load_all_data") as mock_load,
        patch("ui_pyside6.views.char_settings_pages.load_implants", return_value=[]),
        patch("ui_pyside6.views.char_settings_view.services_save_all_data"),
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
    """绑定方法监听器必须是**弱引用**（不持有实例，故不会泄漏）。

    这条原先靠「`del obj` + `gc.collect()` 之后全局条数回落」来验，**在本仓是不可靠的**：
    `_theme_listeners` 是进程级共享列表，同一进程里跑过的每个外壳与桥都会往里加条目，
    而条目只在 `apply_theme` 时惰性剪除；加上 Qt 对象的析构时机不受测试控制，
    实测同一份代码同一种顺序会**一次过、一次挂**（2026-09-16，UI 全档里挂了两次）。
    那种写法量的是「这一轮 GC 是否恰好把对象收走」，不是「监听器是否为弱引用」。

    改为直接验机制本身，**与 GC 时机、与别的测试注册了什么全都无关**：

    1. 注册**不得**抬高实例的引用计数 —— 这正是「不持有实例」的定义，
       也正是 `_StrongCallback` 会违反的那一条（lambda / 普通函数走强引用包装）；
    2. 存进列表的必须是 `weakref.WeakMethod`（而不是 `_StrongCallback`）；
    3. 存活时照常收到通知；
    4. 对象被丢掉之后再切主题，不许崩（失效弱引用要能被过滤掉）。
    """
    import gc
    import sys
    import weakref

    class _Listener:
        def __init__(self):
            self.called = 0

        def on_theme(self):
            self.called += 1

    obj = _Listener()
    before = sys.getrefcount(obj)
    theme.add_theme_listener(obj.on_theme)
    after = sys.getrefcount(obj)
    assert after == before, f"注册监听器抬高了引用计数（{before} → {after}）——说明存的是强引用，对象销毁后回调不会失效"

    ref = theme._theme_listeners[-1]
    assert isinstance(ref, weakref.WeakMethod), f"绑定方法应当存成 WeakMethod，实际是 {type(ref).__name__}"

    apply_theme("light")
    assert obj.called == 1, "存活对象应收到通知"

    del obj
    gc.collect()
    # 销毁后 notify 不应崩溃：失效的弱引用要被过滤掉（这一步**不**断言对象已被回收 ——
    # 收没收走取决于进程里还有谁留着帧或异常栈，不是本用例该管的事；断言了就是测运气）。
    apply_theme("dark")


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

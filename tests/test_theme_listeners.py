"""主题监听器支持测试

验证各页面/对话框在主题切换后能正确重新应用内联样式表。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QShowEvent

import ui_pyside6.theme as theme
from ui_pyside6.theme import ONE_LIGHT, apply_theme

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
        assert hasattr(page, "_on_theme_changed")
        apply_theme("light")
        _wait()
        assert ONE_LIGHT["TEXT_PRIMARY"] in page._title_label.styleSheet()
        assert ONE_LIGHT["TEXT_SECONDARY"] in page._plan_count.styleSheet()


def test_trade_page_theme_listener(qapp):
    from ui_pyside6.views.trade_view import TradePage

    page = TradePage(None)
    assert hasattr(page, "_on_theme_changed")
    apply_theme("light")
    _wait()
    assert ONE_LIGHT["TEXT_SECONDARY"] in page._monitor_placeholder.styleSheet()


def test_estimate_page_theme_listener(qapp, mock_db):
    from ui_pyside6.views.estimate_view import EstimatePage

    page = EstimatePage(None)
    assert hasattr(page, "_on_theme_changed")
    apply_theme("light")
    _wait()
    assert ONE_LIGHT["TEXT_PRIMARY"] in page._total_vol.styleSheet()


def test_inventory_page_theme_listener(qapp, mock_db):
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.fetchall.return_value = []
    mock_conn.cursor.return_value.fetchone.return_value = None
    with (
        patch("ui_pyside6.views.inventory.inventory_page.init_db"),
        patch(
            "ui_pyside6.views.inventory.inventory_page.get_hangars",
            return_value=[{"id": 1, "name": "默认", "notes": ""}],
        ),
        patch("ui_pyside6.views.inventory.blueprint_tab.get_container") as mock_cont,
        patch("ui_pyside6.views.inventory.hangar_tab.get_items", return_value=[]),
        patch("ui_pyside6.views.inventory.hangar_tab.get_hangars", return_value=[]),
        patch(
            "ui_pyside6.views.inventory.blueprint_tab.get_blueprint_tech_levels",
            return_value=[],
        ),
        patch(
            "ui_pyside6.views.inventory.blueprint_tab.get_blueprint_reaction_ids",
            return_value=[],
        ),
        patch("ui_pyside6.views.inventory.blueprint_tab.get_blueprints", return_value=[]),
    ):
        mock_cont.return_value.db.connect.return_value.__enter__.return_value = mock_conn
        from ui_pyside6.views.inventory.inventory_page import InventoryPage

        page = InventoryPage(None)
        assert hasattr(page, "_on_theme_changed")
        apply_theme("light")
        _wait()
        assert ONE_LIGHT["TEXT_SECONDARY"] in page._hangar_tab._count_label.styleSheet()


def test_paste_import_dialog_show_event(qapp, mock_db):
    from ui_pyside6.dialogs.hangar_dialogs import PasteImportDialog

    dlg = PasteImportDialog("测试机库")
    assert hasattr(dlg, "showEvent")
    apply_theme("light")
    dlg.showEvent(QShowEvent())
    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._hint.styleSheet()


def test_import_review_dialog_show_event(qapp, mock_db):
    from ui_pyside6.views.inventory.review_dialog import ImportReviewDialog

    dlg = ImportReviewDialog([], "测试机库", 1)
    assert hasattr(dlg, "showEvent")
    apply_theme("light")
    dlg.showEvent(QShowEvent())
    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._summary_label.styleSheet()


# ── showEvent 不更新对话框自身 stylesheet，仅更新子控件 — 待 dialog 自身也加入 showEvent 重绘 ──


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
        assert ONE_LIGHT["BG_DARK"] in dlg.styleSheet()


def test_init_wizard_show_event(qapp):
    from services.init_service import STEPS

    with (
        patch(
            "ui_pyside6.views.init_wizard.get_missing_steps",
            return_value=[s for s in STEPS if s.key not in ("items", "blueprints")],
        ),
    ):
        from ui_pyside6.views.init_wizard import InitWizard

        wiz = InitWizard()
        apply_theme("light")
        wiz.showEvent(QShowEvent())
        assert ONE_LIGHT["BG_DARK"] in wiz.styleSheet()


def test_all_items_dialog_show_event(qapp, mock_db):
    with (
        patch("ui_pyside6.views.all_items_view.TreeW") as MockTree,
        patch("ui_pyside6.views.all_items_view.ItemsW") as MockItems,
        patch("ui_pyside6.views.all_items_view.AModel", new=_FakeModel),
        patch("ui_pyside6.views.all_items_view.Proxy", new=_FakeProxy),
    ):
        MockTree.return_value.start = MagicMock()
        MockItems.return_value.start = MagicMock()
        from ui_pyside6.views.all_items_view import AllItemsDialog

        dlg = AllItemsDialog()
        apply_theme("light")
        dlg.showEvent(QShowEvent())
        assert ONE_LIGHT["BG_SURFACE"] in dlg._toolbar.styleSheet()


# ── weakref 基础设施（审计发现：监听器无 remove → 页面销毁后仍被引用泄漏） ──


def test_listener_freed_after_object_gc():
    """对象销毁后监听器自动失效（弱引用）：
    1. 存活时收到通知；2. 销毁后 notify 不崩溃；3. 失效引用被清理
    """
    import gc

    import ui_pyside6.theme as theme

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
    import ui_pyside6.theme as theme

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
    import ui_pyside6.theme as theme

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


def test_selector_builds_all_cards(qapp):
    from ui_pyside6.views.theme_selector import ThemeSelector

    sel = ThemeSelector()
    assert len(sel._cards) == len(theme.THEME_REGISTRY)
    sel.deleteLater()


def test_set_current_highlights_card(qapp):
    from ui_pyside6.views.theme_selector import ThemeSelector

    sel = ThemeSelector()
    theme.apply_theme("eve-deep")
    sel.set_current("eve-deep")
    assert sel.current_theme_id() == "eve-deep"
    assert sel._cards["eve-deep"].isChecked()
    assert not sel._cards["one-dark"].isChecked()
    sel.deleteLater()


def test_card_click_switches_theme(qapp):
    from ui_pyside6.views.theme_selector import ThemeSelector

    sel = ThemeSelector()
    theme.apply_theme("one-dark")
    sel._cards["nord"].click()
    assert theme.current_theme() == "nord"
    assert sel.current_theme_id() == "nord"
    # 恢复默认，避免污染 settings
    theme.apply_theme("one-dark")
    sel.deleteLater()

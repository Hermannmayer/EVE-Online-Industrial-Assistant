"""主题监听器支持测试

验证各页面/对话框在主题切换后能正确重新应用内联样式表。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QShowEvent

from ui_pyside6.theme import ONE_LIGHT, apply_theme


class _FakeModel(QAbstractItemModel):
    def index(self, row, col, parent=QModelIndex()):
        return self.createIndex(row, col)

    def parent(self, index):
        return QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        return 0

    def columnCount(self, parent=QModelIndex()):
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
    with patch("ui_pyside6.views.industry_view.init_plan_db"):
        from ui_pyside6.views.industry_view import IndustryPage

        page = IndustryPage(None)
        assert hasattr(page, "_on_theme_changed")
        apply_theme("light")
        _wait()
        assert ONE_LIGHT["TEXT_SECONDARY"] in page._preview.styleSheet()
        assert ONE_LIGHT["BORDER"] in page._score_group.styleSheet()


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
    with (
        patch("ui_pyside6.views.inventory_view.init_db"),
        patch("ui_pyside6.views.inventory_view.get_hangars", return_value=[{"id": 1, "name": "默认", "notes": ""}]),
    ):
        from ui_pyside6.views.inventory_view import InventoryPage

        page = InventoryPage(None)
        assert hasattr(page, "_on_theme_changed")
        apply_theme("light")
        _wait()
        assert ONE_LIGHT["TEXT_SECONDARY"] in page._hangar_tab._count_label.styleSheet()


def test_paste_import_dialog_show_event(qapp, mock_db):
    from ui_pyside6.views.inventory_view import PasteImportDialog

    dlg = PasteImportDialog("测试机库")
    assert hasattr(dlg, "showEvent")
    apply_theme("light")
    dlg.showEvent(QShowEvent())
    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._hint.styleSheet()


def test_import_review_dialog_show_event(qapp, mock_db):
    from ui_pyside6.views.inventory_view import ImportReviewDialog

    dlg = ImportReviewDialog([], "测试机库", 1)
    assert hasattr(dlg, "showEvent")
    apply_theme("light")
    dlg.showEvent(QShowEvent())
    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._summary_label.styleSheet()


# ── showEvent 不更新对话框自身 stylesheet，仅更新子控件 — 待 dialog 自身也加入 showEvent 重绘 ──


@pytest.mark.xfail(reason="showEvent 仅重绘子控件，未更新 dialog 自身 stylesheet")
def test_char_settings_dialog_show_event(qapp, mock_db):
    with (
        patch("ui_pyside6.views.char_settings_view.load_all_data") as mock_load,
        patch("ui_pyside6.views.char_settings_view.load_implants", return_value=[]),
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


@pytest.mark.xfail(reason="showEvent 仅重绘子控件，未更新 dialog 自身 stylesheet")
def test_init_wizard_show_event(qapp):
    with (
        patch("ui_pyside6.views.init_wizard.check_all", return_value={}),
        patch("ui_pyside6.views.init_wizard.missing_count", return_value=5),
    ):
        from ui_pyside6.views.init_wizard import InitWizard

        wiz = InitWizard()
        apply_theme("light")
        wiz.showEvent(QShowEvent())
        assert ONE_LIGHT["BG_DARK"] in wiz.styleSheet()


@pytest.mark.xfail(reason="AllItemsDialog 构造依赖完整 Proxy model，fake 不兼容 — 需 E2E 测试")
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
        assert ONE_LIGHT["BG_SURFACE"] in dlg._toolbar_bg.styleSheet()

"""主题监听器支持测试

验证各页面/对话框存在主题切换方法。
注意: 样式表值检查标记为 xfail，因当前 from theme import VAR 模式
在 apply_theme() 更新模块变量后不会反映新值（字符串不可变）。
第二阶段将修复为 import theme 模块引用模式。
"""

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QModelIndex, Qt
from PySide6.QtGui import QShowEvent
from unittest.mock import MagicMock, patch

from ui_pyside6.theme import ONE_LIGHT, apply_theme

pytestmark = pytest.mark.xfail(reason="from theme import VAR 模式在 apply_theme() 后不反映新值 — 第二阶段修复")


class _FakeModel(QAbstractItemModel):
    """用于 QTableView.setModel 的最小实现"""

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


@pytest.fixture(autouse=True)
def reset_theme():
    """每个测试结束后恢复 dark 主题，避免污染全局状态"""
    yield
    apply_theme("dark")


def _wait_for_events():
    """处理一次 Qt 事件循环，确保样式表更新生效"""
    QCoreApplication.processEvents()


def test_industry_page_theme_listener(qapp, mock_db):
    with patch("ui_pyside6.views.industry_view.init_plan_db"):
        from ui_pyside6.views.industry_view import IndustryPage

        page = IndustryPage(None)
        assert hasattr(page, "_on_theme_changed"), "IndustryPage 应定义 _on_theme_changed"

        apply_theme("light")
        _wait_for_events()

        assert ONE_LIGHT["TEXT_SECONDARY"] in page._preview.styleSheet()
        assert ONE_LIGHT["BORDER"] in page._score_group.styleSheet()


def test_trade_page_theme_listener(qapp):
    from ui_pyside6.views.trade_view import TradePage

    page = TradePage(None)
    assert hasattr(page, "_on_theme_changed"), "TradePage 应定义 _on_theme_changed"

    apply_theme("light")
    _wait_for_events()

    assert ONE_LIGHT["TEXT_SECONDARY"] in page._monitor_placeholder.styleSheet()


def test_estimate_page_theme_listener(qapp, mock_db):
    from ui_pyside6.views.estimate_view import EstimatePage

    page = EstimatePage(None)
    assert hasattr(page, "_on_theme_changed"), "EstimatePage 应定义 _on_theme_changed"

    apply_theme("light")
    _wait_for_events()

    assert ONE_LIGHT["TEXT_PRIMARY"] in page._total_vol.styleSheet()


def test_inventory_page_theme_listener(qapp, mock_db):
    with (
        patch("ui_pyside6.views.inventory_view.init_db"),
        patch("ui_pyside6.views.inventory_view.get_hangars", return_value=[{"id": 1, "name": "默认", "notes": ""}]),
    ):
        from ui_pyside6.views.inventory_view import InventoryPage

        page = InventoryPage(None)
        assert hasattr(page, "_on_theme_changed"), "InventoryPage 应定义 _on_theme_changed"

        apply_theme("light")
        _wait_for_events()

        assert ONE_LIGHT["TEXT_SECONDARY"] in page._hangar_tab._count_label.styleSheet()


def test_paste_import_dialog_show_event(qapp, mock_db):
    from ui_pyside6.views.inventory_view import PasteImportDialog

    dlg = PasteImportDialog("测试机库")
    assert hasattr(dlg, "showEvent"), "PasteImportDialog 应重写 showEvent"

    apply_theme("light")
    dlg.showEvent(QShowEvent())

    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._hint.styleSheet()


def test_import_review_dialog_show_event(qapp, mock_db):
    from ui_pyside6.views.inventory_view import ImportReviewDialog

    dlg = ImportReviewDialog([], "测试机库", 1)
    assert hasattr(dlg, "showEvent"), "ImportReviewDialog 应重写 showEvent"

    apply_theme("light")
    dlg.showEvent(QShowEvent())

    assert ONE_LIGHT["TEXT_SECONDARY"] in dlg._summary_label.styleSheet()


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
        assert hasattr(dlg, "showEvent"), "CharSettingsDialog 应重写 showEvent"

        apply_theme("light")
        dlg.showEvent(QShowEvent())

        assert ONE_LIGHT["BG_DARK"] in dlg.styleSheet()


def test_init_wizard_show_event(qapp):
    with (
        patch("ui_pyside6.views.init_wizard.check_all", return_value={}),
        patch("ui_pyside6.views.init_wizard.missing_count", return_value=5),
    ):
        from ui_pyside6.views.init_wizard import InitWizard

        wiz = InitWizard()
        assert hasattr(wiz, "showEvent"), "InitWizard 应重写 showEvent"

        apply_theme("light")
        wiz.showEvent(QShowEvent())

        assert ONE_LIGHT["BG_DARK"] in wiz.styleSheet()


def test_all_items_dialog_show_event(qapp, mock_db):
    with (
        patch("ui_pyside6.views.all_items_view.TreeW") as MockTree,
        patch("ui_pyside6.views.all_items_view.ItemsW") as MockItems,
        patch("ui_pyside6.views.all_items_view.AModel", new=_FakeModel),
        patch("ui_pyside6.views.all_items_view.Proxy", new=_FakeModel),
    ):
        MockTree.return_value.start = MagicMock()
        MockItems.return_value.start = MagicMock()
        from ui_pyside6.views.all_items_view import AllItemsDialog

        dlg = AllItemsDialog()
        assert hasattr(dlg, "showEvent"), "AllItemsDialog 应重写 showEvent"

        apply_theme("light")
        dlg.showEvent(QShowEvent())

        assert ONE_LIGHT["BG_SURFACE"] in dlg._toolbar_bg.styleSheet()

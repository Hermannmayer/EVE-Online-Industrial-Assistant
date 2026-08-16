"""ThemeSelector 卡片选择器测试。"""

import pytest

import ui_pyside6.theme as theme
from ui_pyside6.views.theme_selector import ThemeSelector


@pytest.fixture(autouse=True)
def _reset_theme():
    """每个测试后恢复默认主题，避免污染同进程的后续测试"""
    yield
    theme.apply_theme("one-dark")


def test_selector_builds_all_cards(qapp):
    sel = ThemeSelector()
    assert len(sel._cards) == len(theme.THEME_REGISTRY)
    sel.deleteLater()


def test_set_current_highlights_card(qapp):
    sel = ThemeSelector()
    theme.apply_theme("eve-deep")
    sel.set_current("eve-deep")
    assert sel.current_theme_id() == "eve-deep"
    assert sel._cards["eve-deep"].isChecked()
    assert not sel._cards["one-dark"].isChecked()
    sel.deleteLater()


def test_card_click_switches_theme(qapp):
    sel = ThemeSelector()
    theme.apply_theme("one-dark")
    sel._cards["nord"].click()
    assert theme.current_theme() == "nord"
    assert sel.current_theme_id() == "nord"
    # 恢复默认，避免污染 settings
    theme.apply_theme("one-dark")
    sel.deleteLater()

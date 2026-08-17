"""标题栏 / 边缘缩放过滤器 / DWM 毛玻璃纯逻辑测试。"""

from unittest.mock import patch

import pytest

from ui_pyside6.dwm import apply_dwm_backdrop
from ui_pyside6.title_bar import TitleBar

pytestmark = pytest.mark.ui


def test_dwm_returns_false_without_hwnd():
    assert apply_dwm_backdrop(0, "acrylic", True) is False


def test_dwm_returns_false_on_non_windows():
    with patch("ui_pyside6.dwm.sys.platform", "linux"):
        assert apply_dwm_backdrop(1, "acrylic", True) is False


def test_title_bar_has_all_controls(qapp):
    tb = TitleBar("EVE 商人助手")
    assert tb._title_label.text() == "EVE 商人助手"
    assert tb._pin_btn.isCheckable()
    for btn in (tb._min_btn, tb._max_btn, tb._close_btn):
        assert not btn.icon().isNull()
    tb.deleteLater()


def test_title_bar_maximize_icon_swaps(qapp):
    tb = TitleBar("测试")
    assert tb._max_btn.toolTip() == "最大化"
    tb.set_maximized(True)
    assert tb._max_btn.toolTip() == "还原"
    tb.set_maximized(False)
    assert tb._max_btn.toolTip() == "最大化"
    tb.deleteLater()

"""DWM 毛玻璃纯逻辑测试。

原文件还测 Widgets 版标题栏（`ui_pyside6.title_bar.TitleBar`）—— 批次 6.2 连同
Widgets 外壳一起删掉了；QML 标题栏的等价断言在 `tests/test_qml_shell.py` 的图标组里。
"""

from unittest.mock import patch

import pytest

from ui_qml.dwm import apply_dwm_backdrop

pytestmark = pytest.mark.ui


def test_dwm_returns_false_without_hwnd():
    assert apply_dwm_backdrop(0, "acrylic", True) is False


def test_dwm_returns_false_on_non_windows():
    with patch("ui_qml.dwm.sys.platform", "linux"):
        assert apply_dwm_backdrop(1, "acrylic", True) is False

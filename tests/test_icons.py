"""Phosphor 图标系统测试 — 渲染、染色、缓存失效、语义映射覆盖。"""

import os

import pytest
from PySide6.QtCore import QSize

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme


@pytest.fixture(autouse=True)
def _reset_theme():
    """每个测试后恢复默认主题，避免污染同进程的后续测试"""
    yield
    theme.apply_theme("one-dark")


def _opaque_colors(icon, size=24):
    img = icon.pixmap(QSize(size, size)).toImage()
    return {
        img.pixelColor(x, y).name()
        for x in range(img.width())
        for y in range(img.height())
        if img.pixelColor(x, y).alpha() > 0
    }


def test_icon_map_files_exist():
    for key, filename in icons.ICON_MAP.items():
        path = os.path.join(icons._ICONS_DIR, filename + ".svg")
        assert os.path.exists(path), f"{key} → {filename}.svg 缺失"


def test_all_semantic_keys_render_nonempty(qapp):
    for key in icons.ICON_MAP:
        icon = icons.themed_icon(key, 24)
        assert not icon.isNull(), f"{key} isNull"
        assert _opaque_colors(icon), f"{key} 渲染为空"


def test_icon_tints_by_color(qapp):
    a = _opaque_colors(icons.themed_icon("settings", 24, "#5c6370"))
    b = _opaque_colors(icons.themed_icon("settings", 24, "#6B7380"))
    assert a and b
    assert a != b


def test_status_icon_green_red_differ(qapp):
    ok = _opaque_colors(icons.status_icon(True, 16))
    bad = _opaque_colors(icons.status_icon(False, 16))
    assert ok and bad
    assert ok != bad


def test_theme_change_clears_icon_cache(qapp):
    theme.apply_theme("one-dark")
    icons.themed_icon("settings", 24, theme.TEXT_SECONDARY).pixmap(QSize(24, 24))
    assert len(icons._pixmap_cache) > 0
    theme.apply_theme("eve-deep")
    assert len(icons._pixmap_cache) == 0

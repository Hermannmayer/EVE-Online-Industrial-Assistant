"""主题注册表 / legacy 迁移 / WCAG 对比度测试。"""

import re
from unittest.mock import patch

import pytest

from ui_pyside6.theme import (
    ONE_DARK_PRO,
    ONE_LIGHT,
    THEME_REGISTRY,
    apply_theme,
    current_theme,
    load_theme_preference,
    toggle_theme,
)

_COLOR_KEYS = {
    "BG_DARK",
    "BG_SURFACE",
    "BG_SURFACE_LIGHT",
    "BG_HOVER",
    "PRIMARY",
    "ACCENT_RED",
    "ACCENT_GREEN",
    "ACCENT_YELLOW",
    "ACCENT_ORANGE",
    "ACCENT_PURPLE",
    "ACCENT_CYAN",
    "TEXT_PRIMARY",
    "TEXT_BRIGHT",
    "TEXT_SECONDARY",
    "TEXT_ON_PRIMARY",
    "BORDER",
}

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@pytest.fixture(autouse=True)
def _reset_theme():
    """每个测试后恢复默认主题，避免污染同进程的后续测试"""
    yield
    apply_theme("one-dark")


def _rel_lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    l1, l2 = sorted((_rel_lum(a), _rel_lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# ── 注册表完整性 ──


def test_registry_has_at_least_10_themes():
    assert len(THEME_REGISTRY) >= 10


def test_every_theme_spec_is_valid():
    for tid, spec in THEME_REGISTRY.items():
        assert spec["id"] == tid, f"{tid} id 不一致"
        assert spec["name_zh"]
        assert spec["mode"] in ("dark", "light")
        assert spec["material"] in ("acrylic", "mica", "solid")
        assert isinstance(spec["radius"], int) and 0 < spec["radius"] <= 12
        assert set(spec["colors"]) == _COLOR_KEYS, f"{tid} 颜色键不完整"
        for key in _COLOR_KEYS:
            assert _HEX_RE.match(spec["colors"][key]), f"{tid}.{key} 非法: {spec['colors'][key]}"


def test_one_dark_and_one_light_reuse_existing_palettes():
    assert THEME_REGISTRY["one-dark"]["colors"] == ONE_DARK_PRO
    assert THEME_REGISTRY["one-light"]["colors"] == ONE_LIGHT


# ── legacy 迁移 ──


def test_apply_theme_legacy_dark_resolves_to_one_dark():
    apply_theme("dark")
    assert current_theme() == "one-dark"


def test_apply_theme_legacy_light_resolves_to_one_light():
    apply_theme("light")
    assert current_theme() == "one-light"


def test_load_theme_preference_migrates_legacy():
    with (
        patch("services.user_settings.load_settings", return_value={"theme": "light"}),
        patch("services.user_settings.save_settings") as mock_save,
    ):
        assert load_theme_preference() == "one-light"
        mock_save.assert_called_once_with({"theme": "one-light"})


def test_load_theme_preference_default_one_dark():
    with patch("services.user_settings.load_settings", return_value={}):
        assert load_theme_preference() == "one-dark"


def test_toggle_theme_involution():
    apply_theme("one-dark")
    first = toggle_theme()
    assert first == "one-light"
    assert toggle_theme() == "one-dark"


# ── WCAG 对比度 ──
# 亮色主题为硬约束（TEXT_SECONDARY 在亮底 ≥ 4.5）；暗色主题次要文字本就有意低对比，
# 仅设 2.0 底线防异常值。主文字对底色全部要求 ≥ 4.5。


def _spec(theme_id):
    return THEME_REGISTRY[theme_id]


@pytest.mark.parametrize("theme_id", sorted(THEME_REGISTRY))
def test_primary_text_contrast_on_dark(theme_id):
    """TEXT_PRIMARY vs BG_DARK 对比度 ≥ 4.5（主文字）"""
    colors = _spec(theme_id)["colors"]
    ratio = _contrast(colors["TEXT_PRIMARY"], colors["BG_DARK"])
    assert ratio >= 4.5, f"{theme_id} TEXT_PRIMARY/BG_DARK 对比度 {ratio:.2f} < 4.5"


@pytest.mark.parametrize("theme_id", sorted(THEME_REGISTRY))
def test_secondary_text_contrast_on_surface(theme_id):
    """TEXT_SECONDARY vs BG_SURFACE：亮色 ≥ 4.5（硬约束），暗色 ≥ 3.0（可读底线）"""
    colors = _spec(theme_id)["colors"]
    ratio = _contrast(colors["TEXT_SECONDARY"], colors["BG_SURFACE"])
    floor = 4.5 if _spec(theme_id)["mode"] == "light" else 3.0
    assert ratio >= floor, f"{theme_id} TEXT_SECONDARY/BG_SURFACE 对比度 {ratio:.2f} < {floor}"


@pytest.mark.parametrize("theme_id", sorted(THEME_REGISTRY))
def test_on_primary_contrast(theme_id):
    """TEXT_ON_PRIMARY vs PRIMARY ≥ 2.0（按钮文字基本可读）"""
    colors = _spec(theme_id)["colors"]
    ratio = _contrast(colors["TEXT_ON_PRIMARY"], colors["PRIMARY"])
    assert ratio >= 2.0, f"{theme_id} TEXT_ON_PRIMARY/PRIMARY 对比度 {ratio:.2f} < 2.0"

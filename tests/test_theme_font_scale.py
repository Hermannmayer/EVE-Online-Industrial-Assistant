"""全局字号缩放测试 — 纯计算，无需 QApplication。"""

import pytest

import ui_pyside6.theme as theme


@pytest.fixture(autouse=True)
def _restore_scale():
    """每个用例后恢复出厂缩放，避免污染同进程的后续测试。"""
    yield
    theme.set_font_scale(1.0)


class TestFs:
    def test_identity_at_default_scale(self):
        """scale=1.0 时恒等 —— 这是「token 化不改变外观」的基础保证。"""
        theme.set_font_scale(1.0)
        assert theme.fs(11) == 11
        assert theme.fs(13) == 13
        assert theme.fs(18) == 18

    def test_scales_with_factor(self):
        theme.set_font_scale(1.5)
        assert theme.fs(13) == 20  # round(19.5)，Python 银行家进位
        assert theme.fs(11) == 16  # round(16.5)
        assert theme.fs(20) == 30

    def test_has_floor(self):
        theme.set_font_scale(0.5)
        assert theme.fs(10) == 8  # max(8, round(5))

    def test_font_point_size_matches_legacy_default(self):
        """13px ≈ 9.75pt，取整后必须等于历史值 10pt，否则启动字体外观会变。"""
        theme.set_font_scale(1.0)
        assert theme.font_point_size() == 10


class TestSetFontScale:
    def test_clamps_to_supported_range(self):
        theme.set_font_scale(99)
        assert theme.FONT_SCALE == 2.0
        theme.set_font_scale(0)
        assert theme.FONT_SCALE == 0.5

    def test_stylesheet_font_sizes_follow_scale(self):
        theme.set_font_scale(1.0)
        base = theme.get_stylesheet()
        theme.set_font_scale(1.5)
        scaled = theme.get_stylesheet()
        assert base != scaled
        assert "font-size: 13px" in base
        assert "font-size: 20px" in scaled
        assert "font-size: 13px" not in scaled


class TestApplyThemeSafety:
    def test_apply_theme_without_qapplication_does_not_raise(self):
        """无 QApplication 时 apply_theme 必须静默跳过字体同步。

        tests/test_theme_registry.py 的 autouse fixture 会在无 qapp 的情况下调用它。
        """
        theme.apply_theme("one-dark")


class TestLoadFontScale:
    def test_defaults_to_one_when_unset(self, monkeypatch):
        monkeypatch.setattr("services.user_settings.load_settings", lambda: {})
        assert theme.load_font_scale() == 1.0

    def test_converts_pixels_to_scale(self, monkeypatch):
        monkeypatch.setattr("services.user_settings.load_settings", lambda: {"font_size": 20})
        assert theme.load_font_scale() == pytest.approx(20 / theme.BASE_FONT_PX)

    def test_out_of_range_value_is_clamped(self, monkeypatch):
        monkeypatch.setattr("services.user_settings.load_settings", lambda: {"font_size": 999})
        assert theme.load_font_scale() == 2.0

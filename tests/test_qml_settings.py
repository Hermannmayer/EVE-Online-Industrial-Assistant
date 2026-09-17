"""系统设置 / 主题选择器的 QML 桥业务契约（阶段 4b）。

只放**业务契约**：设置是否写回宿主、主题卡片是否真的换肤、字号是否推给 theme。
「QML 能否加载 / 有没有告警」是统一护栏的事，不在本文件重复。

宿主用替身而不是真 `MainWindow`：`SettingsBridge` 只碰那几个成员
（`_save_settings` / `_start_price_timer` / `_update_interval_minutes` …），
把它们摆出来就足够锁住契约，也不会因为主窗口改版就红一大片。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from tests.qml_click import spin as _spin
from ui_qml.bridge.settings_bridge import SettingsBridge, SettingsQmlDialog, ThemeSelectorBridge
from ui_qml.theme import registry as theme

pytestmark = pytest.mark.ui


class _Host:
    """宿主替身：给 `SettingsBridge` 读写的那些成员。"""

    def __init__(self, interval: int = 30, auto: bool = True) -> None:
        self._update_interval_minutes = interval
        self._auto_update_enabled = auto
        self._status_label = MagicMock()
        self.saved = 0
        self.started = 0
        self.stopped = 0
        self.wizard = 0
        self.about = 0

    def _save_settings(self) -> None:
        self.saved += 1

    def _start_price_timer(self) -> None:
        self.started += 1

    def _stop_price_timer(self) -> None:
        self.stopped += 1

    def _show_init_wizard(self) -> None:
        self.wizard += 1

    def _show_about(self) -> None:
        self.about += 1


class _WidgetHost(QWidget):
    """带窗口体的宿主 —— `SettingsQmlDialog(main_window)` 的 main_window 得是 QWidget。"""

    def __init__(self) -> None:
        super().__init__()
        self._update_interval_minutes = 45
        self._auto_update_enabled = False
        self._status_label = QLabel()

    def _save_settings(self) -> None: ...

    def _start_price_timer(self) -> None: ...

    def _stop_price_timer(self) -> None: ...


# ── 读宿主状态 / 写回 ──────────────────────────────────────────


def test_bridge_reads_the_host_state(qapp):
    bridge = SettingsBridge(_Host(interval=45, auto=False))
    assert bridge.interval == 45
    assert bridge.autoUpdate is False
    # 字号从 theme 取（原 `_load_state` 的 `round(BASE_FONT_PX * FONT_SCALE)`）
    assert bridge.fontSize == round(theme.BASE_FONT_PX * theme.FONT_SCALE)


def test_apply_writes_back_saves_and_starts_the_timer(qapp):
    host = _Host(interval=30, auto=True)
    bridge = SettingsBridge(host)

    bridge.setInterval(15)
    bridge.setAutoUpdate(True)
    bridge.apply()

    assert host._update_interval_minutes == 15
    assert host._auto_update_enabled is True
    assert host.saved == 1
    assert host.started == 1
    assert host.stopped == 0
    host._status_label.setText.assert_called_with("设置已保存（间隔: 15 分钟）")


def test_apply_stops_the_timer_when_disabled(qapp):
    """间隔为 0（= 关闭）或没勾自动更新时，只停不启 —— 原 `_on_apply` 的分支。"""
    host = _Host(interval=30, auto=True)
    bridge = SettingsBridge(host)

    bridge.setInterval(0)
    bridge.setAutoUpdate(True)
    bridge.apply()
    assert (host.started, host.stopped) == (0, 1)

    bridge.setInterval(30)
    bridge.setAutoUpdate(False)
    bridge.apply()
    assert (host.started, host.stopped) == (0, 2)


def test_accept_applies_then_closes(qapp):
    host = _Host()
    bridge = SettingsBridge(host)
    closed: list[bool] = []
    bridge.accepted.connect(lambda: closed.append(True))

    bridge.setInterval(20)
    bridge.accept()

    assert closed == [True], "点「确定」必须关窗（宿主接到 accepted 才会退出 exec）"
    assert host.saved == 1, "关窗前要先应用，不能只发信号"


def test_apply_without_a_host_is_a_noop(qapp):
    """宿主为 None（纯展示 / 单测）时不能炸 —— 原版每处都有 `if not self._mw` 兜底。"""
    bridge = SettingsBridge(None)
    bridge.apply()  # 不抛异常即可
    bridge.openInitWizard()
    bridge.openAbout()


# ── 字号 ─────────────────────────────────────────────────────


def test_font_size_pushes_the_scale_and_persists_it(qapp, monkeypatch):
    scales: list[float] = []
    monkeypatch.setattr(theme, "FONT_SCALE", 1.0)
    monkeypatch.setattr(theme, "set_font_scale", scales.append)
    monkeypatch.setattr(theme, "save_font_scale", scales.append)

    bridge = SettingsBridge(_Host())
    bridge.setFontSize(20)
    bridge.apply()

    assert scales == [20 / theme.BASE_FONT_PX, 20 / theme.BASE_FONT_PX], "缩放与持久化都要收到同一个值"


def test_unchanged_font_size_does_not_reapply_the_theme(qapp, monkeypatch):
    """默认字号 = 当前缩放 → 不该白重放一次主题（各页面都跟着重套样式，代价不小）。"""
    calls: list[float] = []
    monkeypatch.setattr(theme, "FONT_SCALE", 1.0)
    monkeypatch.setattr(theme, "set_font_scale", calls.append)

    bridge = SettingsBridge(_Host())
    assert bridge.fontSize == theme.BASE_FONT_PX
    bridge.apply()

    assert calls == []


# ── 数据初始化 / 关于 ────────────────────────────────────────


def test_init_wizard_closes_the_dialog_before_opening(qapp):
    """先关设置再弹向导，且要排到下一个事件循环（原版 QTimer.singleShot(0) 的时序）。"""
    host = _Host()
    bridge = SettingsBridge(host)
    closed: list[bool] = []
    bridge.accepted.connect(lambda: closed.append(True))

    bridge.openInitWizard()
    assert closed == [True], "向导是模态的，得先退出设置的 exec 循环"
    assert host.wizard == 0, "同一个事件循环里不能立刻弹第二个模态窗"

    _spin()
    assert host.wizard == 1


def test_about_is_delegated_to_the_host(qapp):
    host = _Host()
    SettingsBridge(host).openAbout()
    assert host.about == 1


# ── 主题选择器 ───────────────────────────────────────────────


def test_themes_come_from_the_registry_with_their_own_colours(qapp):
    """卡片预览的是**各主题自己的**色值，必须直取 THEME_REGISTRY，不能借用当前主题 token。"""
    bridge = ThemeSelectorBridge()
    themes = bridge.themes

    assert [t["id"] for t in themes] == list(theme.THEME_REGISTRY)
    for card, spec in zip(themes, theme.THEME_REGISTRY.values(), strict=True):
        assert card["name"] == spec["name_zh"]
        assert card["badge"] == ("暗" if spec["mode"] == "dark" else "亮")
        assert [s["color"] for s in card["swatches"]] == [
            spec["colors"]["BG_SURFACE"],
            spec["colors"]["PRIMARY"],
            spec["colors"]["TEXT_PRIMARY"],
        ]
        assert all(s["border"] == spec["colors"]["BORDER"] for s in card["swatches"])


def test_set_current_only_syncs_the_highlight(qapp, monkeypatch):
    """`set_current` 是「回填选中态」，不许触发切换 —— 原版注释写死的语义。"""
    monkeypatch.setattr(theme, "current_theme", lambda: "fluent-dark")
    bridge = ThemeSelectorBridge()

    bridge.set_current("fluent-light")
    assert bridge.currentThemeId == "fluent-light"
    assert theme.current_theme() == "fluent-dark", "同步选中态不该改全局主题"


def test_card_click_switches_the_theme(qapp):
    original = theme.current_theme()
    try:
        theme.apply_theme("fluent-dark")
        bridge = ThemeSelectorBridge()
        picked: list[str] = []
        bridge.themeSelected.connect(picked.append)

        bridge.setCurrentTheme("fluent-light")
        assert theme.current_theme() == "fluent-light"
        assert bridge.currentThemeId == "fluent-light"
        assert picked == ["fluent-light"]

        # 再点当前主题：既不重复 apply，也不重复发信号
        bridge.setCurrentTheme("fluent-light")
        assert picked == ["fluent-light"]
    finally:
        theme.apply_theme(original)


def test_unknown_theme_id_is_ignored(qapp):
    original = theme.current_theme()
    try:
        bridge = ThemeSelectorBridge()
        bridge.setCurrentTheme("no-such-theme")
        assert theme.current_theme() == original
    finally:
        theme.apply_theme(original)


def test_theme_selector_is_exposed_to_qml(qapp):
    """宿主桥把选择器当 QML 属性暴露 —— 内嵌组件的接法就是这个属性。"""
    bridge = SettingsBridge(_Host())
    assert isinstance(bridge.themeSelector, ThemeSelectorBridge)
    assert bridge.themeSelector.currentThemeId == theme.current_theme()


# ── 宿主对话框的构造签名 ─────────────────────────────────────


def test_dialog_keeps_the_original_constructor_shape(qapp):
    """`SettingsDialog(main_window, parent)` 的调用方只换类名就能用。"""
    host = _WidgetHost()
    dialog = SettingsQmlDialog(host, host)
    try:
        assert dialog.ok()
        assert dialog.bridge.interval == 45
        assert dialog.bridge.autoUpdate is False
    finally:
        dialog.deleteLater()


def test_bridge_does_not_keep_the_host_alive(qapp):
    """桥不许**强引用**宿主 —— 那会连成一个跨所有权的引用环，GC 收环时直接崩。

    宿主同时是这个对话框的 Qt 父窗口（`SettingsQmlDialog` 的 `parent=parent or main_window`），
    于是「宿主（C++ 父）→ 对话框（Python 包装）→ 桥 → 宿主」成环。Python 的 GC 会在**任意**
    分配点收这个环，而析构顺序会跨过 Qt 的父子边界 → access violation；崩点还在别处
    （`-m ui` 全量档偶发崩在 storage 页的 fixture 拆除里，追了很久才找到这里）。
    这条钉住「弱引用」这个修法不被改回强引用。
    """
    import gc
    import weakref

    host = _WidgetHost()
    bridge = SettingsBridge(host)
    assert bridge._mw is host, "正常路径下应当能读到宿主"

    ref = weakref.ref(host)
    del host
    gc.collect()

    assert ref() is None, "桥把宿主强引用住了：会连成引用环，GC 收环时跨 Qt 父子边界析构 → 崩溃"
    assert bridge._mw is None, "宿主没了之后桥应当读到 None（各处已有 None 兜底）"

"""主题 token 桥 —— 把 `ui_pyside6.theme` 的设计 token 暴露给 QML。

**单一 token 源**：所有颜色/圆角/间距/动效值都取自 `ui_pyside6.theme`，
QML 侧禁止写颜色或尺寸字面量（等价于 CLAUDE.md 里「配色一律从 theme 导入」的铁律）。

由 `ui_qml.host.PageHost` 以 context property 名 `Theme` 注入，QML 侧直接写：

    Rectangle { color: Theme.bgDark; radius: Theme.radius }

⚠️ **属性名一律用 camelCase**：PySide6 以 Python 属性名作为 QML 里的名字，
写成 snake_case 会导致 QML 侧 `Theme.bgDark` 静默解析为 undefined
（不报错，只是拿到空值）。本类专为 QML 而存在，故例外采用 camelCase。
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

import ui_pyside6.theme as theme

__all__ = ["ThemeBridge", "COLOR_TOKENS", "theme_singleton", "CONTEXT_NAME"]

# QML 侧以 context property 的形式访问：`Theme.xxx`（由 PageHost 注入）
CONTEXT_NAME = "Theme"

# 与 tests/test_theme_registry.py 的 _COLOR_KEYS 同序，方便比对
COLOR_TOKENS: tuple[str, ...] = (
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
)

# SPI_GETCLIENTAREAANIMATION：Windows「辅助功能 → 视觉效果 → 动画效果」开关
_SPI_GETCLIENTAREAANIMATION = 0x1042

# 单例必须比引擎活得久，用模块级引用托住，避免被 GC 回收
_singleton: ThemeBridge | None = None


def _detect_reduced_motion() -> bool:
    """系统是否要求减弱动效。非 Windows 或调用失败一律返回 False（不减弱）。"""
    if sys.platform != "win32":
        return False
    try:
        enabled = ctypes.c_int(0)
        ok = ctypes.windll.user32.SystemParametersInfoW(_SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        if not ok:
            return False
        return not bool(enabled.value)
    except Exception:
        return False


class ThemeBridge(QObject):
    """QML 可读的主题 token 视图；主题切换时发 `changed`。"""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._remove_listener = theme.add_theme_listener(self._on_theme_changed)
        self._apply_palette()

    # ── 生命周期 ──

    def _on_theme_changed(self) -> None:
        self._apply_palette()
        self.changed.emit()

    def _apply_palette(self) -> None:
        """把整套主题色写进 QPalette，并同步深浅色方案。

        QML 控件**不认 QSS**，它们只认 `QPalette` 与 `styleHints.colorScheme`——
        本项目十套主题原本只驱动 QSS，因此必须在切主题时同步这两处，
        否则 QML 侧控件会脱离主题（实测：colorScheme 为 Unknown 时，
        Qt 的 Fluent 样式会走暗色分支，控件渲染成黑块）。

        - `Accent` 决定 Fluent 控件的强调色（读 `control.palette.accent`）。
        - 其余角色决定控件表面/文字/边框，让 QML 跟随同一套主题。
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        palette = app.palette()
        setter = palette.setColor
        setter(QPalette.ColorRole.Accent, QColor(theme.PRIMARY))
        setter(QPalette.ColorRole.Highlight, QColor(theme.PRIMARY))
        setter(QPalette.ColorRole.HighlightedText, QColor(theme.TEXT_ON_PRIMARY))
        setter(QPalette.ColorRole.Link, QColor(theme.PRIMARY))

        setter(QPalette.ColorRole.Window, QColor(theme.BG_DARK))
        setter(QPalette.ColorRole.WindowText, QColor(theme.TEXT_PRIMARY))
        setter(QPalette.ColorRole.Base, QColor(theme.BG_SURFACE))
        setter(QPalette.ColorRole.AlternateBase, QColor(theme.BG_SURFACE_LIGHT))
        setter(QPalette.ColorRole.Text, QColor(theme.TEXT_PRIMARY))
        setter(QPalette.ColorRole.Button, QColor(theme.BG_SURFACE))
        setter(QPalette.ColorRole.ButtonText, QColor(theme.TEXT_PRIMARY))
        setter(QPalette.ColorRole.BrightText, QColor(theme.TEXT_BRIGHT))
        setter(QPalette.ColorRole.PlaceholderText, QColor(theme.TEXT_SECONDARY))

        setter(QPalette.ColorRole.Mid, QColor(theme.BORDER))
        setter(QPalette.ColorRole.Shadow, QColor(theme.BORDER))
        setter(QPalette.ColorRole.Dark, QColor(theme.BG_SURFACE_LIGHT))
        setter(QPalette.ColorRole.Light, QColor(theme.BG_SURFACE_LIGHT))

        setter(QPalette.ColorRole.ToolTipBase, QColor(theme.BG_SURFACE))
        setter(QPalette.ColorRole.ToolTipText, QColor(theme.TEXT_PRIMARY))

        app.setPalette(palette)

        hints = app.styleHints()
        scheme = Qt.ColorScheme.Dark if self._is_dark() else Qt.ColorScheme.Light
        try:
            hints.setColorScheme(scheme)
        except (AttributeError, TypeError):
            # Qt < 6.8 没有 setColorScheme，控件会退回默认分支（不致命）
            pass

    def detach(self) -> None:
        """注销监听器（宿主销毁时调用）。"""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    def _color(self, token: str) -> QColor:
        return QColor(getattr(theme, token))

    # ── 颜色 token（16 个，逐一暴露以保证 QML 绑定可重算）──
    # 属性名即 QML 里的名字，见模块 docstring 的 camelCase 说明。

    bgDark = Property(QColor, lambda self: self._color("BG_DARK"), notify=changed)
    bgSurface = Property(QColor, lambda self: self._color("BG_SURFACE"), notify=changed)
    bgSurfaceLight = Property(QColor, lambda self: self._color("BG_SURFACE_LIGHT"), notify=changed)
    bgHover = Property(QColor, lambda self: self._color("BG_HOVER"), notify=changed)
    primary = Property(QColor, lambda self: self._color("PRIMARY"), notify=changed)
    accentRed = Property(QColor, lambda self: self._color("ACCENT_RED"), notify=changed)
    accentGreen = Property(QColor, lambda self: self._color("ACCENT_GREEN"), notify=changed)
    accentYellow = Property(QColor, lambda self: self._color("ACCENT_YELLOW"), notify=changed)
    accentOrange = Property(QColor, lambda self: self._color("ACCENT_ORANGE"), notify=changed)
    accentPurple = Property(QColor, lambda self: self._color("ACCENT_PURPLE"), notify=changed)
    accentCyan = Property(QColor, lambda self: self._color("ACCENT_CYAN"), notify=changed)
    textPrimary = Property(QColor, lambda self: self._color("TEXT_PRIMARY"), notify=changed)
    textBright = Property(QColor, lambda self: self._color("TEXT_BRIGHT"), notify=changed)
    textSecondary = Property(QColor, lambda self: self._color("TEXT_SECONDARY"), notify=changed)
    textOnPrimary = Property(QColor, lambda self: self._color("TEXT_ON_PRIMARY"), notify=changed)
    border = Property(QColor, lambda self: self._color("BORDER"), notify=changed)

    # 浮起表面（卡片等）。不是注册表里的 16 键之一，而是从 BG_DARK 按材质模式派生：
    # 本项目原有 BG_SURFACE < BG_DARK（卡片比页面暗），直接用会让卡片像凹坑而非浮起。
    bgElevated = Property(QColor, lambda self: QColor(theme.bg_elevated()), notify=changed)

    # ── 形状 / 材质 / 主题元信息 ──

    radius = Property(int, lambda self: theme.RADIUS, notify=changed)
    radiusSmall = Property(int, lambda self: theme.RADIUS_SMALL, notify=changed)
    material = Property(str, lambda self: theme.MATERIAL, notify=changed)
    themeId = Property(str, lambda self: theme.current_theme(), notify=changed)

    def _is_dark(self) -> bool:
        spec = theme.current_theme_spec()
        return spec is not None and spec["mode"] == "dark"

    isDark = Property(bool, lambda self: self._is_dark(), notify=changed)

    # ── 间距刻度 ──

    spacingXs = Property(int, lambda self: theme.SPACING_XS, notify=changed)
    spacingSm = Property(int, lambda self: theme.SPACING_SM, notify=changed)
    spacingMd = Property(int, lambda self: theme.SPACING_MD, notify=changed)
    spacingLg = Property(int, lambda self: theme.SPACING_LG, notify=changed)

    # ── 动效 ──

    durationFast = Property(int, lambda self: theme.DURATION_FAST, notify=changed)
    durationCard = Property(int, lambda self: theme.DURATION_CARD, notify=changed)
    reducedMotion = Property(bool, lambda self: _detect_reduced_motion(), notify=changed)

    # ── 焦点环 ──

    focusRingWidth = Property(int, lambda self: theme.FOCUS_RING_WIDTH, notify=changed)
    focusRingOffset = Property(int, lambda self: theme.FOCUS_RING_OFFSET, notify=changed)

    # ── 字体（随「全局字号」缩放）──

    fontFamily = Property(str, lambda self: theme.FONT_FAMILY, notify=changed)

    @Slot(int, result=int)
    def fs(self, px: int) -> int:
        """基准像素字号 → 当前缩放下的像素字号。"""
        return theme.fs(px)

    # ── 高度（elevation）──
    # Qt 只支持单层阴影，规范的双层阴影已近似为单层（见 theme.ELEVATION 注释）。

    @Slot(int, result=float)
    def elevationBlur(self, level: int) -> float:
        """MultiEffect 的 shadowBlur：**0..1 归一化值**，不是像素（传像素会没有阴影）。"""
        return theme.ELEVATION.get(level, theme.ELEVATION[1])[0]

    @Slot(int, result=float)
    def elevationOffset(self, level: int) -> float:
        """shadowVerticalOffset：单位是真像素。"""
        return theme.ELEVATION.get(level, theme.ELEVATION[1])[1]

    @Slot(int, result=float)
    def elevationAlpha(self, level: int) -> float:
        """阴影不透明度。暗色主题下按 `DARK_SHADOW_BOOST` 抬高。

        黑色阴影在深色底上几乎不可见——用规范原值（0.13）实测完全看不出层次，
        所以暗色主题需要更强的阴影才能读出「浮起」。
        """
        alpha = theme.ELEVATION.get(level, theme.ELEVATION[1])[2]
        if self._is_dark():
            alpha = min(theme.DARK_SHADOW_ALPHA_MAX, alpha * theme.DARK_SHADOW_BOOST)
        return alpha


def theme_singleton() -> ThemeBridge:
    """取进程内唯一的 `ThemeBridge` 实例（首次调用时创建）。

    由 `PageHost` 以 context property 名 `Theme` 注入 QML，
    QML 侧直接写 `Theme.bgDark` 即可，无需 import。

    注：PySide6 的 `qmlRegisterSingletonInstance`/`qmlRegisterSingletonType`
    在本版本签名不兼容（要求 factory 回调却拒绝普通可调用对象），
    故改用 context property——语义等价且更简单。
    """
    global _singleton
    if _singleton is None:
        _singleton = ThemeBridge()
    return _singleton

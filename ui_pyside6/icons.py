"""Phosphor 图标系统 — QIconEngine 按当前主题动态取色（Widgets 专有的那一半）

图标资源、语义键映射 `ICON_MAP` 与 SVG 文本读取已经搬到 `ui_qml/icons.py`
—— 那一份零 Qt（QML 侧的 `icon_provider` 直接读原始 SVG 自己染），
本模块从这里导入它们。

这里只留渲染与染色：把 SVG 变成按当前主题取色的 `QPixmap` / `QIcon`，
主题切换后任一重绘自动重染。`ICON_MAP` / `svg_path` / `load_svg` 仍可从本模块
导入（转自 `ui_qml.icons`），旧调用方与 `tests/test_icons.py` 不必改。
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QToolButton

import ui_qml.theme.registry as theme
from ui_qml.icons import ICON_MAP, ICONS_DIR, load_svg

#: 兼容旧引用（`tests/test_icons.py` 用它拼 SVG 路径）；真值在 `ui_qml.icons`
_ICONS_DIR = ICONS_DIR

_pixmap_cache: dict[tuple, QPixmap] = {}


def _device_pixel_ratio() -> float:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return 1.0
    screen = app.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def _render_pixmap(filename: str, color: str, size: int) -> QPixmap:
    key = (filename, color, size)
    pm = _pixmap_cache.get(key)
    if pm is not None:
        return pm
    svg = load_svg(filename)
    if not svg:
        pm = QPixmap(1, 1)
        pm.fill(Qt.GlobalColor.transparent)
        _pixmap_cache[key] = pm
        return pm
    # Phosphor 把 fill 写在 <svg> 根上，QSvgRenderer 又不把根级 fill 继承给 <path>
    # （且该 Qt 版本对路径弧线命令 a/A 有 bug），故直接给 <path> 注入颜色，
    # 并用 QPixmap.loadFromData（与 QIcon 相同的 SVG 图片插件）渲染。
    tinted = svg.replace("<path ", f'<path fill="{color}" ', 1)
    src = QPixmap()
    if not src.loadFromData(tinted.encode("utf-8")):
        pm = QPixmap(1, 1)
        pm.fill(Qt.GlobalColor.transparent)
        _pixmap_cache[key] = pm
        return pm
    dpr = _device_pixel_ratio()
    device_size = max(1, int(size * dpr))
    pm = src.scaled(
        device_size, device_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    pm.setDevicePixelRatio(dpr)
    _pixmap_cache[key] = pm
    return pm


class _ThemedIconEngine(QIconEngine):
    """paint 时按当前主题取色：主题切换后无需重建 QIcon，重绘即重染"""

    def __init__(self, filename: str, size: int, color: str | None):
        super().__init__()
        self._filename = filename
        self._size = size
        self._color = color

    def _resolved_color(self) -> str:
        return self._color if self._color else theme.TEXT_SECONDARY

    def paint(self, painter: QPainter, rect: QRect, mode, state):
        size = rect.width() or self._size
        pm = _render_pixmap(self._filename, self._resolved_color(), size)
        painter.drawPixmap(rect, pm)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return _render_pixmap(self._filename, self._resolved_color(), size.width())

    def clone(self) -> QIconEngine:
        return _ThemedIconEngine(self._filename, self._size, self._color)


def themed_icon(key: str, size: int = 20, color: str | None = None) -> QIcon:
    """按语义键创建主题图标。color 为 None 时跟随当前主题 TEXT_SECONDARY。

    QIcon(engine) 会接管 engine 所有权（随 QIcon 销毁而释放），故每次新建 engine。
    """
    filename = ICON_MAP.get(key)
    if not filename:
        return QIcon()
    return QIcon(_ThemedIconEngine(filename, size, color))


def themed_icon_from_file(filename: str, size: int = 20, color: str | None = None) -> QIcon:
    """按 SVG 文件名直接创建主题图标（绕过 ICON_MAP，供实心/特殊权重图标等场景）"""
    return QIcon(_ThemedIconEngine(filename, size, color))


def set_button_icon(btn, key: str, color=None, size: int = 20, text: str | None = None):
    """给 QPushButton/QToolButton 设置主题图标（可带文字，图标+文字并排）"""
    btn.setIcon(themed_icon(key, size, color))
    btn.setIconSize(QSize(size, size))
    if text is not None:
        btn.setText(text)
    if isinstance(btn, QToolButton):
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


def status_icon(ok: bool, size: int = 16) -> QIcon:
    """✓/✗ 状态图标（绿色 check / 红色 x）"""
    color = theme.ACCENT_GREEN if ok else theme.ACCENT_RED
    return themed_icon("check" if ok else "close", size, color)


def clear_icon_cache():
    """主题切换时清空渲染缓存，下次 paint 用新主题色重染"""
    _pixmap_cache.clear()


theme.add_theme_listener(clear_icon_cache)

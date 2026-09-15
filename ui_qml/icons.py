"""Phosphor 图标的**资源与语义键** —— 零 Qt 依赖的那一半。

图标以 Phosphor（MIT）regular 线框 SVG 打包在 `ui_qml/assets/icons/`，
语义键 → 文件名统一由 `ICON_MAP` 中心映射（铁律：禁止散落硬编码文件名）。

这里只有「路径怎么拼」和「SVG 文本怎么读」，**没有任何 Qt 类型**：
QML 侧的 `icon_provider` 拿原始文本自己注入 `fill` 染色，所以它只需要本模块。
按主题取色、把 SVG 渲染成 `QPixmap`、`QIconEngine` 那一半是 Widgets 专有，
留在 `ui_pyside6/icons.py`（它从这里导入，并对旧调用方保持原 API）。
"""

import os

__all__ = ["ICON_MAP", "ICONS_DIR", "load_svg", "svg_path"]

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")

# 语义键 → Phosphor SVG 文件名
ICON_MAP: dict[str, str] = {
    "refresh": "arrows-clockwise",
    "pin": "push-pin",
    "clock": "clock",
    "settings": "gear-six",
    "user": "user",
    "hangar": "warehouse",
    "factory": "factory",
    "chart": "chart-line",
    "bell": "bell",
    "contract": "file-text",
    "package": "package",
    "coins": "coins",
    "lightning": "lightning",
    "search": "magnifying-glass",
    "star": "star",
    "details": "clipboard-text",
    "recycle": "recycle",
    "check": "check",
    "close": "x",
    "warning": "warning",
    "plus": "plus",
    "minus": "minus",
    "maximize": "square",
    "restore": "copy",
    "trash": "trash",
    "play": "play",
    "caret-down": "caret-down",
    "trend-up": "trend-up",
    "lightbulb": "lightbulb",
    "flask": "flask",
    "caret-right": "caret-right",
    "dna": "dna",
    "shield": "shield",
    "microscope": "microscope",
    "sailboat": "sailboat",
    "globe": "globe",
    "wrench": "wrench",
    "buildings": "buildings",
    "book": "book",
    "spiral": "spiral",
    "test-tube": "test-tube",
    "info": "info",
    "circle": "circle",
}

_svg_cache: dict[str, str] = {}


def svg_path(filename: str) -> str:
    """Phosphor SVG 的绝对路径（不检查存在性，由调用方判断）。

    给 QML 侧的 `Image.source` 用：那边要的是 `file://` URL，且拿不到
    `QIconEngine` 的 paint 时染色，只能读原始 SVG 自己染。
    """
    if not filename.endswith(".svg"):
        filename += ".svg"
    return os.path.join(ICONS_DIR, filename)


def load_svg(filename: str) -> str:
    """读 Phosphor SVG 文本（带缓存）；缺失返回空串。

    QML 侧的 `icon_provider` 要拿原始文本自己注入 `fill` 染色。
    """
    if not filename.endswith(".svg"):
        filename += ".svg"
    svg = _svg_cache.get(filename)
    if svg is None:
        try:
            with open(svg_path(filename), encoding="utf-8") as f:
                svg = f.read()
        except OSError:
            svg = ""
        _svg_cache[filename] = svg
    return svg

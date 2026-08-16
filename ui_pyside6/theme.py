"""
One Dark Pro / One Light 主题系统 — 支持运行时切换
"""

import json
import logging
import os
import weakref
from collections.abc import Callable
from typing import TypedDict, cast

_logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
#  色板定义
# ═══════════════════════════════════════════

ONE_DARK_PRO = {
    "BG_DARK": "#282c34",
    "BG_SURFACE": "#21252b",
    "BG_SURFACE_LIGHT": "#2c323c",  # 选中/悬浮
    "BG_HOVER": "#3a3f4b",
    "PRIMARY": "#61afef",  # 蓝色强调
    "ACCENT_RED": "#e06c75",
    "ACCENT_GREEN": "#98c379",
    "ACCENT_YELLOW": "#e5c07b",
    "ACCENT_ORANGE": "#d19a66",
    "ACCENT_PURPLE": "#c678dd",
    "ACCENT_CYAN": "#56b6c2",
    "TEXT_PRIMARY": "#abb2bf",
    "TEXT_BRIGHT": "#e5e7eb",
    "TEXT_SECONDARY": "#7a8290",  # 调亮（原 #5c6370 对比度仅 2.55，不易读）
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#3e4452",
}

ONE_LIGHT = {
    "BG_DARK": "#f5f2ed",
    "BG_SURFACE": "#eae7e2",
    "BG_SURFACE_LIGHT": "#ddd9d2",
    "BG_HOVER": "#d2cec7",
    "PRIMARY": "#4078f2",
    "ACCENT_RED": "#e45649",
    "ACCENT_GREEN": "#50a14f",
    "ACCENT_YELLOW": "#986801",
    "ACCENT_ORANGE": "#da854d",
    "ACCENT_PURPLE": "#a626a4",
    "ACCENT_CYAN": "#0184bc",
    "TEXT_PRIMARY": "#4a4a4a",
    "TEXT_BRIGHT": "#2a2a2a",
    "TEXT_SECONDARY": "#666666",  # WCAG AA：亮底 ≥4.5:1（原 #8a8a8a 仅 ~2.8）
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#d4d0cb",
}

# 8 套新增配色（theme_design_guide.md 第三节）。
# 指南中的玻璃材质用 rgba() 描述（如 BG_SURFACE 为 6% 白玻璃），这里统一合成
# 为该颜色叠加在 BG_DARK 上的不透明 hex——保证 QSS/QColor/对比度测试全部可靠，
# 玻璃质感由 DWM 毛玻璃 + get_stylesheet 的 _surface_color() 半透明处理实现。

EVE_DEEP = {
    "BG_DARK": "#0b0e14",
    "BG_SURFACE": "#1a1c22",  # 白色 6% 玻璃合成
    "BG_SURFACE_LIGHT": "#1b2130",
    "BG_HOVER": "#242c3d",
    "PRIMARY": "#4d9fff",
    "ACCENT_RED": "#e05252",
    "ACCENT_GREEN": "#58c08c",
    "ACCENT_YELLOW": "#e8b13d",
    "ACCENT_ORANGE": "#d19a66",
    "ACCENT_PURPLE": "#9b6bff",
    "ACCENT_CYAN": "#46b6c8",
    "TEXT_PRIMARY": "#c8cdd6",
    "TEXT_BRIGHT": "#ffffff",
    "TEXT_SECONDARY": "#6b7380",
    "TEXT_ON_PRIMARY": "#0b0e14",
    "BORDER": "#23262b",  # 白色 10% 玻璃合成
}

EVE_POLAR = {
    "BG_DARK": "#e8eaef",
    "BG_SURFACE": "#f5f6f8",  # 白色 55% 玻璃合成
    "BG_SURFACE_LIGHT": "#d5dae3",
    "BG_HOVER": "#c8cfda",
    "PRIMARY": "#005fb8",
    "ACCENT_RED": "#d13438",
    "ACCENT_GREEN": "#107c41",
    "ACCENT_YELLOW": "#b8860b",
    "ACCENT_ORANGE": "#c55a11",
    "ACCENT_PURPLE": "#7b5cd6",
    "ACCENT_CYAN": "#0099a8",
    "TEXT_PRIMARY": "#2b2f36",
    "TEXT_BRIGHT": "#111318",
    "TEXT_SECONDARY": "#5f6876",  # WCAG AA：亮底 ≥4.5:1（原 #6b7280 仅 ~4.4）
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#ccced2",  # 黑色 12% 玻璃合成
}

FLUENT_BLUE = {
    "BG_DARK": "#202020",
    "BG_SURFACE": "#2b2b2b",  # 白色 5% 玻璃合成
    "BG_SURFACE_LIGHT": "#333333",
    "BG_HOVER": "#3d3d3d",
    "PRIMARY": "#4cc2ff",
    "ACCENT_RED": "#ff99a4",
    "ACCENT_GREEN": "#6ccb5f",
    "ACCENT_YELLOW": "#fce100",
    "ACCENT_ORANGE": "#f7630c",
    "ACCENT_PURPLE": "#c29bff",
    "ACCENT_CYAN": "#4cc2ff",
    "TEXT_PRIMARY": "#f3f3f3",
    "TEXT_BRIGHT": "#ffffff",
    "TEXT_SECONDARY": "#a0a0a0",
    "TEXT_ON_PRIMARY": "#0f0f0f",
    "BORDER": "#323232",  # 白色 8% 玻璃合成
}

FLUENT_BRIGHT = {
    "BG_DARK": "#f3f3f3",
    "BG_SURFACE": "#fafafa",  # 白色 60% 玻璃合成
    "BG_SURFACE_LIGHT": "#e5e5e5",
    "BG_HOVER": "#dadada",
    "PRIMARY": "#005fb8",
    "ACCENT_RED": "#c42b1c",
    "ACCENT_GREEN": "#0f7b0f",
    "ACCENT_YELLOW": "#9d5d00",
    "ACCENT_ORANGE": "#c55a11",
    "ACCENT_PURPLE": "#8764b8",
    "ACCENT_CYAN": "#038387",
    "TEXT_PRIMARY": "#1a1a1a",
    "TEXT_BRIGHT": "#000000",
    "TEXT_SECONDARY": "#616161",
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#e0e0e0",  # 黑色 8% 玻璃合成
}

CYBER_NEON = {
    "BG_DARK": "#05060a",
    "BG_SURFACE": "#0d0f1a",
    "BG_SURFACE_LIGHT": "#141828",
    "BG_HOVER": "#1c2240",
    "PRIMARY": "#00f0ff",
    "ACCENT_RED": "#ff2e63",
    "ACCENT_GREEN": "#00ff9f",
    "ACCENT_YELLOW": "#ffe600",
    "ACCENT_ORANGE": "#ff9f1c",
    "ACCENT_PURPLE": "#bc13fe",
    "ACCENT_CYAN": "#00f0ff",
    "TEXT_PRIMARY": "#d0f8ff",
    "TEXT_BRIGHT": "#ffffff",
    "TEXT_SECONDARY": "#5a6b8c",
    "TEXT_ON_PRIMARY": "#05060a",
    "BORDER": "#035860",  # 青色 35% 玻璃合成
}

NORD = {
    "BG_DARK": "#2e3440",
    "BG_SURFACE": "#3b4252",
    "BG_SURFACE_LIGHT": "#434c5e",
    "BG_HOVER": "#4c566a",
    "PRIMARY": "#88c0d0",
    "ACCENT_RED": "#bf616a",
    "ACCENT_GREEN": "#a3be8c",
    "ACCENT_YELLOW": "#ebcb8b",
    "ACCENT_ORANGE": "#d08770",
    "ACCENT_PURPLE": "#b48ead",
    "ACCENT_CYAN": "#8fbcbb",
    "TEXT_PRIMARY": "#d8dee9",
    "TEXT_BRIGHT": "#eceff4",
    "TEXT_SECONDARY": "#81a1c1",
    "TEXT_ON_PRIMARY": "#2e3440",
    "BORDER": "#4c566a",
}

TOKYO_NIGHT = {
    "BG_DARK": "#1a1b26",
    "BG_SURFACE": "#24283b",
    "BG_SURFACE_LIGHT": "#2f3549",
    "BG_HOVER": "#3b4261",
    "PRIMARY": "#7aa2f7",
    "ACCENT_RED": "#f7768e",
    "ACCENT_GREEN": "#9ece6a",
    "ACCENT_YELLOW": "#e0af68",
    "ACCENT_ORANGE": "#ff9e64",
    "ACCENT_PURPLE": "#bb9af7",
    "ACCENT_CYAN": "#7dcfff",
    "TEXT_PRIMARY": "#a9b1d6",
    "TEXT_BRIGHT": "#c0caf5",
    "TEXT_SECONDARY": "#727c98",  # 调亮（原 #565f89 对比度仅 2.35，不易读）
    "TEXT_ON_PRIMARY": "#1a1b26",
    "BORDER": "#3b4261",
}

WARM_SUN = {
    "BG_DARK": "#f7f3ec",
    "BG_SURFACE": "#ffffff",
    "BG_SURFACE_LIGHT": "#efe9df",
    "BG_HOVER": "#e4dccc",
    "PRIMARY": "#c4704a",
    "ACCENT_RED": "#c2453d",
    "ACCENT_GREEN": "#5b8c51",
    "ACCENT_YELLOW": "#a8862e",
    "ACCENT_ORANGE": "#c4704a",
    "ACCENT_PURPLE": "#8e6ba4",
    "ACCENT_CYAN": "#3e8e8e",
    "TEXT_PRIMARY": "#3d3830",
    "TEXT_BRIGHT": "#26221c",
    "TEXT_SECONDARY": "#6a6356",  # WCAG AA：亮底 ≥4.5:1（原 #8c8476 仅 ~3.7）
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#e3e0d9",  # 黑色 8% 玻璃合成
}


class ThemeSpec(TypedDict):
    id: str
    name_zh: str
    mode: str  # "dark" | "light"
    material: str  # "acrylic" | "mica" | "solid"
    radius: int
    colors: dict[str, str]


THEME_REGISTRY: dict[str, ThemeSpec] = {
    "eve-deep": {
        "id": "eve-deep",
        "name_zh": "EVE 深空",
        "mode": "dark",
        "material": "acrylic",
        "radius": 6,
        "colors": EVE_DEEP,
    },
    "eve-polar": {
        "id": "eve-polar",
        "name_zh": "EVE 极昼",
        "mode": "light",
        "material": "acrylic",
        "radius": 6,
        "colors": EVE_POLAR,
    },
    "fluent-blue": {
        "id": "fluent-blue",
        "name_zh": "Fluent 蓝",
        "mode": "dark",
        "material": "mica",
        "radius": 4,
        "colors": FLUENT_BLUE,
    },
    "fluent-bright": {
        "id": "fluent-bright",
        "name_zh": "Fluent 亮",
        "mode": "light",
        "material": "mica",
        "radius": 4,
        "colors": FLUENT_BRIGHT,
    },
    "cyber-neon": {
        "id": "cyber-neon",
        "name_zh": "赛博霓虹",
        "mode": "dark",
        "material": "solid",
        "radius": 2,
        "colors": CYBER_NEON,
    },
    "nord": {"id": "nord", "name_zh": "Nord", "mode": "dark", "material": "solid", "radius": 6, "colors": NORD},
    "tokyo-night": {
        "id": "tokyo-night",
        "name_zh": "Tokyo Night",
        "mode": "dark",
        "material": "solid",
        "radius": 8,
        "colors": TOKYO_NIGHT,
    },
    "warm-sun": {
        "id": "warm-sun",
        "name_zh": "暖阳",
        "mode": "light",
        "material": "solid",
        "radius": 10,
        "colors": WARM_SUN,
    },
    "one-dark": {
        "id": "one-dark",
        "name_zh": "One Dark",
        "mode": "dark",
        "material": "solid",
        "radius": 6,
        "colors": ONE_DARK_PRO,
    },
    "one-light": {
        "id": "one-light",
        "name_zh": "One Light",
        "mode": "light",
        "material": "solid",
        "radius": 6,
        "colors": ONE_LIGHT,
    },
}

# legacy settings.json 里的旧主题 id → canonical id 迁移
_LEGACY_MAP = {"dark": "one-dark", "light": "one-light"}

# 兼容层：旧调用方 / 测试仍可引用 THEMES["dark"/"light"]
THEMES = {
    "dark": ONE_DARK_PRO,
    "light": ONE_LIGHT,
}

# ── 模块级变量（运行时被 apply_theme 更新） ──
# 默认使用 One Dark Pro
BG_DARK = ONE_DARK_PRO["BG_DARK"]
BG_SURFACE = ONE_DARK_PRO["BG_SURFACE"]
BG_SURFACE_LIGHT = ONE_DARK_PRO["BG_SURFACE_LIGHT"]
BG_HOVER = ONE_DARK_PRO["BG_HOVER"]
PRIMARY = ONE_DARK_PRO["PRIMARY"]
ACCENT_RED = ONE_DARK_PRO["ACCENT_RED"]
ACCENT_GREEN = ONE_DARK_PRO["ACCENT_GREEN"]
ACCENT_YELLOW = ONE_DARK_PRO["ACCENT_YELLOW"]
ACCENT_ORANGE = ONE_DARK_PRO["ACCENT_ORANGE"]
ACCENT_PURPLE = ONE_DARK_PRO["ACCENT_PURPLE"]
ACCENT_CYAN = ONE_DARK_PRO["ACCENT_CYAN"]
TEXT_PRIMARY = ONE_DARK_PRO["TEXT_PRIMARY"]
TEXT_BRIGHT = ONE_DARK_PRO["TEXT_BRIGHT"]
TEXT_SECONDARY = ONE_DARK_PRO["TEXT_SECONDARY"]
TEXT_ON_PRIMARY = ONE_DARK_PRO["TEXT_ON_PRIMARY"]
BORDER = ONE_DARK_PRO["BORDER"]

# 材质与圆角（随主题切换）
MATERIAL = "solid"
RADIUS = 6
RADIUS_SMALL = max(2, RADIUS - 2)

_current_theme = "one-dark"


class _StrongCallback:
    """普通函数/lambda 的强引用包装（WeakMethod 只支持绑定方法）"""

    def __init__(self, callback: Callable[[], None]):
        self._callback = callback

    def __call__(self) -> Callable[[], None]:
        return self._callback


# 监听器以弱引用存储：页面销毁后自动失效（GC 回收 → 引用失效），
# 避免「页面常驻 stack 不销毁 + 匿名 lambda 永不 remove」导致的内存泄漏。
_theme_listeners: list[weakref.ref | _StrongCallback] = []

# ── 向后兼容别名 ──
GREEN = ACCENT_GREEN
RED = ACCENT_RED
YELLOW = ACCENT_YELLOW

WINDOW_GEOMETRY_FILE: str | None = None


def _resolve_theme_id(name: str) -> str:
    """把（可能是 legacy 的）主题 id 解析为注册表中的 canonical id"""
    return _LEGACY_MAP.get(name, name)


def apply_theme(theme_name: str) -> None:
    """
    切换主题并更新模块级变量。
    所有 `from ui_pyside6.theme import XXX` 的地方会自动反映新值。
    """
    global _current_theme, BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, BG_HOVER
    global PRIMARY, ACCENT_RED, ACCENT_GREEN, ACCENT_YELLOW
    global ACCENT_ORANGE, ACCENT_PURPLE, ACCENT_CYAN
    global TEXT_PRIMARY, TEXT_BRIGHT, TEXT_SECONDARY, TEXT_ON_PRIMARY, BORDER
    global MATERIAL, RADIUS, RADIUS_SMALL
    global GREEN, RED, YELLOW

    canonical = _resolve_theme_id(theme_name)
    spec = THEME_REGISTRY.get(canonical)
    if not spec:
        return

    _current_theme = canonical
    for key, value in spec["colors"].items():
        globals()[key] = value

    # 材质与圆角 token
    MATERIAL = spec["material"]
    RADIUS = spec["radius"]
    RADIUS_SMALL = max(2, spec["radius"] - 2)

    # 更新别名
    globals()["GREEN"] = globals()["ACCENT_GREEN"]
    globals()["RED"] = globals()["ACCENT_RED"]
    globals()["YELLOW"] = globals()["ACCENT_YELLOW"]

    # 持久化主题偏好（canonical id）
    save_theme_preference(canonical)

    # 通知监听器（过滤已失效的弱引用）
    dead = []
    for ref in _theme_listeners:
        try:
            listener = ref()
        except ReferenceError:
            dead.append(ref)
            continue
        if listener is None:
            dead.append(ref)
            continue
        try:
            listener()
        except Exception:
            _logger.exception("主题监听器回调失败")
    for ref in dead:
        _theme_listeners.remove(ref)


def current_theme() -> str:
    return _current_theme


def current_theme_spec() -> ThemeSpec | None:
    return THEME_REGISTRY.get(_current_theme)


def theme_material() -> str:
    return MATERIAL


def theme_radius() -> int:
    return RADIUS


def toggle_theme() -> str:
    """在当前主题 mode 基础上在 one-dark / one-light 之间确定性互切，返回新主题 id"""
    spec = current_theme_spec()
    target = "one-light" if (spec and spec["mode"] == "dark") else "one-dark"
    apply_theme(target)
    return target


def add_theme_listener(callback: Callable[[], None]):
    """注册主题切换时的回调（返回 remove 函数便于显式注销）

    绑定方法用 WeakMethod 弱引用（不持有实例，避免泄漏）；普通函数/lambda
    用强引用包装（weakref.ref 对 lambda 立即失效，回调不会触发）。
    注意：强引用场景下，调用方在回调不再需要后应调用返回的 remove 函数，
    否则闭包引用的对象会被长期持有。
    """
    try:
        ref: weakref.ref | _StrongCallback = weakref.WeakMethod(callback)
    except TypeError:
        ref = _StrongCallback(callback)
    _theme_listeners.append(ref)
    return lambda: remove_theme_listener(callback)


def remove_theme_listener(callback: Callable[[], None]):
    """移除主题监听器（兼容旧调用方；弱引用实现下通常无需手动移除）"""
    for ref in list(_theme_listeners):
        try:
            if ref() == callback:  # 绑定方法按实例比较（weakref.WeakMethod 语义）
                _theme_listeners.remove(ref)
        except ReferenceError:
            _theme_listeners.remove(ref)


def save_theme_preference(theme_name: str):
    """保存主题偏好到 settings.json（走 services.user_settings 统一入口）"""
    try:
        from services.user_settings import save_settings

        save_settings({"theme": theme_name})
    except Exception:
        pass


def load_theme_preference() -> str:
    """从 settings.json 读取主题偏好，默认 one-dark；legacy "dark"/"light" 自动迁移落盘"""
    try:
        from services.user_settings import load_settings

        raw = cast(str, load_settings().get("theme", "one-dark"))
    except Exception:
        return "one-dark"
    canonical = _resolve_theme_id(raw)
    if canonical != raw:
        save_theme_preference(canonical)
    return canonical


def themed_menu(parent, object_name: str = ""):
    """创建已应用全局主题的 QMenu，禁止调用方再 setStyleSheet"""
    from PySide6.QtWidgets import QMenu

    menu = QMenu(parent)
    if object_name:
        menu.setObjectName(object_name)
    return menu


def set_geometry_file(path: str):
    global WINDOW_GEOMETRY_FILE
    WINDOW_GEOMETRY_FILE = path


def save_window_geometry(window):
    if WINDOW_GEOMETRY_FILE is None:
        return
    try:
        geo = window.geometry()
        data = {"x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()}
        os.makedirs(os.path.dirname(WINDOW_GEOMETRY_FILE), exist_ok=True)
        with open(WINDOW_GEOMETRY_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def restore_window_geometry(window):
    if WINDOW_GEOMETRY_FILE is None:
        return
    try:
        if os.path.exists(WINDOW_GEOMETRY_FILE):
            with open(WINDOW_GEOMETRY_FILE) as f:
                data = json.load(f)
            window.setGeometry(data["x"], data["y"], data["w"], data["h"])
        else:
            window.resize(1400, 800)
    except Exception:
        window.resize(1400, 800)


def _surface_color(color_hex: str, alpha: int = 242) -> str:
    """材质表面颜色：solid 材质返回不透明 hex；acrylic/mica 返回 rgba（玻璃面板）。

    alpha 默认 242（95%）：信息密度高区域（导航）优先可读，少透桌面；
    标题栏等装饰性表面可传更低值（如 225）让毛玻璃更明显。
    """
    if MATERIAL == "solid" or not color_hex.startswith("#") or len(color_hex) != 7:
        return color_hex
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _frost_overlay() -> str:
    """磨砂质感：对角细微高光/暗角叠加在玻璃表面上（solid 材质不叠加）"""
    if MATERIAL == "solid":
        return "none"
    return (
        "qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        "stop:0 rgba(255,255,255,26), stop:0.45 rgba(255,255,255,8),"
        "stop:0.55 rgba(0,0,0,0), stop:1 rgba(0,0,0,16))"
    )


def _global_styles() -> str:
    return f"""
    QMainWindow {{
        background-color: transparent;
    }}
    QWidget {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    """


def _menu_styles() -> str:
    return f"""
    QMenuBar {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border-bottom: 1px solid {BORDER};
        padding: 2px;
    }}
    QMenuBar::item {{
        padding: 4px 12px;
        border-radius: {RADIUS_SMALL};
    }}
    QMenuBar::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
    }}
    QMenu {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 32px 6px 16px;
        border-radius: {RADIUS_SMALL};
    }}
    QMenu::item:selected {{
        background-color: {PRIMARY};
        color: {TEXT_ON_PRIMARY};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER};
        margin: 4px 8px;
    }}
    """


def _statusbar_toolbar_styles() -> str:
    return f"""
    QStatusBar {{
        background-color: {BG_SURFACE};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {BORDER};
        font-size: 11px;
        padding: 2px 8px;
    }}
    QToolBar {{
        background-color: {BG_SURFACE};
        border-bottom: 1px solid {BORDER};
        padding: 2px 4px;
        spacing: 4px;
    }}
    QToolBar::separator {{
        width: 1px;
        background-color: {BORDER};
        margin: 4px 6px;
    }}
    """


def _tree_tab_styles() -> str:
    return f"""
    QTreeWidget {{
        background-color: {BG_SURFACE};
        border: none;
        outline: none;
        color: {TEXT_PRIMARY};
    }}
    QTreeWidget::item {{
        padding: 6px 8px;
        border-radius: {RADIUS_SMALL};
        color: {TEXT_SECONDARY};
    }}
    QTreeWidget::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_BRIGHT};
    }}
    QTreeWidget::item:hover {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
    }}
    QTreeWidget::branch {{
        background-color: {BG_SURFACE};
    }}
    QTabWidget::pane {{
        background-color: {BG_DARK};
        border: none;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {TEXT_SECONDARY};
        padding: 8px 20px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {PRIMARY};
        border-bottom: 2px solid {PRIMARY};
    }}
    QTabBar::tab:hover {{
        color: {TEXT_PRIMARY};
    }}
    """


def _input_styles() -> str:
    return f"""
    QLineEdit {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 6px 10px;
        selection-background-color: {PRIMARY};
    }}
    QLineEdit:focus {{
        border-color: {PRIMARY};
    }}
    QComboBox {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 4px 8px;
        min-width: 80px;
    }}
    QComboBox:hover {{
        border-color: {PRIMARY};
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SMALL};
        selection-background-color: {BG_SURFACE_LIGHT};
        outline: none;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    """


def _button_styles() -> str:
    return f"""
    QPushButton {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 6px 16px;
    }}
    QPushButton:hover {{
        background-color: {BG_HOVER};
        border-color: {PRIMARY};
        color: {TEXT_BRIGHT};
    }}
    QPushButton:pressed {{
        background-color: {BG_SURFACE_LIGHT};
    }}
    QPushButton:disabled {{
        background-color: {BG_SURFACE};
        color: {TEXT_SECONDARY};
    }}
    QToolButton {{
        background-color: transparent;
        color: {TEXT_SECONDARY};
        border: none;
        border-radius: {RADIUS_SMALL};
        padding: 4px;
    }}
    QToolButton:hover {{
        background-color: {BG_HOVER};
        color: {TEXT_PRIMARY};
    }}
    """


def _table_styles() -> str:
    return f"""
    QTableView {{
        background-color: {BG_DARK};
        alternate-background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        gridline-color: {BORDER};
        selection-background-color: {PRIMARY};
        selection-color: {TEXT_ON_PRIMARY};
        outline: none;
    }}
    QTableView::item {{
        padding: 4px 8px;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:selected {{
        background-color: {PRIMARY};
        color: {TEXT_ON_PRIMARY};
    }}
    QTableView::item:selected:!active {{
        background-color: {PRIMARY};
        color: {TEXT_ON_PRIMARY};
    }}
    QTableView::indicator {{
        width: 16px;
        height: 16px;
        border: 2px solid {BORDER};
        border-radius: {RADIUS_SMALL};
        background-color: {BG_SURFACE};
    }}
    QTableView::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}
    QHeaderView::section {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        padding: 6px 8px;
        border: none;
        border-right: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        font-weight: bold;
        font-size: 12px;
    }}
    QHeaderView::section:hover {{
        background-color: {BG_HOVER};
    }}
    """


def _splitter_styles() -> str:
    return f"""
    QSplitter::handle {{
        background-color: {BORDER};
        margin: 1px;
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:vertical {{
        height: 2px;
    }}
    """


def _progress_checkbox_scroll_styles() -> str:
    return f"""
    QProgressBar {{
        background-color: {BG_SURFACE};
        border: none;
        border-radius: {RADIUS_SMALL};
        height: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {PRIMARY};
        border-radius: {RADIUS_SMALL};
    }}
    QCheckBox {{
        spacing: 8px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SMALL};
        background-color: {BG_SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}
    QScrollBar:vertical {{
        background-color: {BG_DARK};
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BORDER};
        border-radius: {RADIUS_SMALL};
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_SECONDARY};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: {BG_DARK};
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {BORDER};
        border-radius: {RADIUS_SMALL};
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {TEXT_SECONDARY};
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    """


def _list_tooltip_styles() -> str:
    return f"""
    QListWidget {{
        background-color: {BG_DARK};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        outline: none;
    }}
    QListWidget::item {{
        padding: 4px 8px;
        border-bottom: 1px solid {BORDER};
    }}
    QListWidget::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_BRIGHT};
    }}
    QTextBrowser {{
        background-color: {BG_DARK};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        color: {TEXT_PRIMARY};
    }}
    QToolTip {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SMALL};
        padding: 4px 8px;
        font-size: 12px;
    }}
    """


def _mainwindow_specific_styles() -> str:
    return f"""
    #central_widget {{
        background-color: transparent;
    }}
    #nav_panel {{
        background-color: {_surface_color(BG_SURFACE, 230)};
        background-image: {_frost_overlay()};
    }}
    #nav_panel QWidget {{
        background-color: transparent;
    }}
    #content_stack {{
        background-color: {BG_DARK};
    }}
    #nav_tree {{
        background-color: transparent;
        border: none;
        outline: none;
    }}
    #nav_tree::item {{
        padding: 6px 8px;
        border-radius: {RADIUS_SMALL};
        color: {TEXT_SECONDARY};
    }}
    #nav_tree::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_BRIGHT};
    }}
    #nav_tree::item:hover {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
    }}
    #price_time_label {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
        padding-right: 16px;
    }}
    #status_label {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
    }}
    #update_btn {{
        background-color: {PRIMARY};
        color: {TEXT_ON_PRIMARY};
        border: none;
        border-radius: {RADIUS_SMALL};
        font-size: 11px;
        padding: 2px 10px;
        min-height: 22px;
    }}
    #update_btn:hover {{
        background-color: {ACCENT_RED};
    }}
    #update_btn:disabled {{
        background-color: {TEXT_SECONDARY};
    }}
    #char_settings_btn, #sys_settings_btn {{
        background-color: {BG_DARK};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 0px;
    }}
    #char_settings_btn:hover, #sys_settings_btn:hover {{
        background-color: {BG_HOVER};
        border: 1px solid {PRIMARY};
    }}
    """


def _page_specific_styles() -> str:
    return f"""
    #query_page, #industry_page, #trade_page, #inventory_page {{
        background-color: {BG_DARK};
    }}
    #query_toolbar, #industry_toolbar {{
        background-color: {BG_SURFACE};
        border-bottom: 1px solid {BORDER};
    }}
    #query_status {{
        background-color: {BG_DARK};
        padding: 2px 16px;
    }}
    #product_label {{
        color: {TEXT_SECONDARY};
        padding: 4px 16px;
        font-size: 12px;
    }}
    #bp_selector {{
        background-color: {BG_SURFACE};
        border-bottom: 1px solid {BORDER};
        padding: 4px 12px;
    }}
    #industry_summary {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        font-size: 13px;
        padding: 8px 12px;
    }}
    #sys_menu {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 4px;
    }}
    #sys_menu::item {{
        padding: 6px 24px;
        border-radius: {RADIUS_SMALL};
    }}
    #sys_menu::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_BRIGHT};
    }}
    """


def _titlebar_styles() -> str:
    return f"""
    #title_bar {{
        background-color: {_surface_color(BG_SURFACE, 217)};
        background-image: {_frost_overlay()};
        border-bottom: 1px solid {BORDER};
        spacing: 2px;
        padding: 0 4px 0 12px;
    }}
    #title_bar QWidget {{
        background-color: transparent;
    }}
    #title_label {{
        color: {TEXT_BRIGHT};
        font-size: 13px;
        font-weight: bold;
        background: transparent;
    }}
    #title_btn {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_SMALL};
        min-width: 26px;
        min-height: 24px;
        max-width: 26px;
        max-height: 24px;
    }}
    #title_btn:hover {{
        background-color: {BG_HOVER};
    }}
    #title_btn:pressed {{
        background-color: {BG_SURFACE_LIGHT};
    }}
    #title_btn:checked {{
        background-color: {PRIMARY};
    }}
    #title_close_btn {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_SMALL};
        min-width: 26px;
        min-height: 24px;
        max-width: 26px;
        max-height: 24px;
    }}
    #title_close_btn:hover {{
        background-color: {ACCENT_RED};
    }}
    #title_close_btn:pressed {{
        background-color: {ACCENT_RED};
    }}
    """


def _theme_selector_styles() -> str:
    return f"""
    #theme_card {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
        padding: 2px;
    }}
    #theme_card:hover {{
        background-color: {BG_HOVER};
        border-color: {PRIMARY};
    }}
    #theme_card:checked {{
        background-color: {BG_SURFACE_LIGHT};
        border: 2px solid {PRIMARY};
    }}
    #theme_card:pressed {{
        background-color: {BG_SURFACE_LIGHT};
    }}
    """


def get_stylesheet() -> str:
    """根据当前主题生成 QSS 样式表 — 按组件类别组装"""
    return "".join(
        [
            _global_styles(),
            _menu_styles(),
            _statusbar_toolbar_styles(),
            _tree_tab_styles(),
            _input_styles(),
            _button_styles(),
            _table_styles(),
            _splitter_styles(),
            _progress_checkbox_scroll_styles(),
            _list_tooltip_styles(),
            _mainwindow_specific_styles(),
            _titlebar_styles(),
            _theme_selector_styles(),
            _page_specific_styles(),
        ]
    )

"""
主题系统 —— 色板 / 注册表 / 运行时 token / 切换与持久化。支持运行时切换。

**单一 token 源**：QML 的 `Theme` 单例（经 `ui_qml.bridge.theme_bridge`）与所有
`theme.XXX` 取值都读这里，禁止在别处写颜色字面量。

本模块原先在 `ui_pyside6/theme.py`，因为 QML 侧要读同一份 token 才搬到 `ui_qml/`。
搬迁期间 `ui_pyside6/` 下留过一层同名转发器，批次 7.0 已随引用方全部改指而删除 ——
那个旧路径现在不存在，新代码一律 import 本模块。

批次 7.5 之前这里还带着 QSS 生成（14 个 `_*_styles()` + `get_stylesheet()` +
`themed_menu()`），那是 Widgets 外壳专有的；外壳在 6.1 换成 QML 之后它就已是死代码，
7.5 随 `ui_pyside6/` 一并删除（本文件 1099 行 → 494 行）。
**QML 侧不套 QSS**，它靠 `Theme` 绑定的属性重绘。
"""

import json
import os
import weakref
from collections.abc import Callable
from typing import TypedDict, cast

from core.logger import log

# ═══════════════════════════════════════════
#  色板定义 —— 微软 Fluent Design
# ═══════════════════════════════════════════
# 取值来源：Fluent Design 规范。主蓝 #0078d4 是规范里的标志性蓝；
# 强调色也取规范给的高饱和值（#e81123 / #00cc6a / #ffb900），
# 避免整屏只有灰蓝、显得死气沉沉。
#
# 每套色板必须提供完全相同的 16 个键（由 tests/test_theme_registry.py 强制）。

FLUENT_LIGHT = {
    # 浅色按用户指定的 Desert Night 配色（深靛蓝 + 琥珀）。
    # 主色 #1A237E / 辅助 #303F9F / 浅靛 #3949AB / 琥珀 #FFB300 / 浅琥珀 #FFE082。
    # 红绿仍保留语义（估价页的卖价/买价要靠它们区分），只取同族的深饱和值。
    "BG_DARK": "#f2f4fb",  # 页面底（带靛蓝倾向的浅灰）
    "BG_SURFACE": "#ffffff",  # 卡片
    "BG_SURFACE_LIGHT": "#e6eaf8",  # 选中/悬浮
    "BG_HOVER": "#d8dff5",
    "PRIMARY": "#1a237e",  # 深靛蓝
    "ACCENT_RED": "#c62828",
    "ACCENT_GREEN": "#2e7d32",
    "ACCENT_YELLOW": "#ffb300",  # 琥珀
    "ACCENT_ORANGE": "#ff8f00",
    "ACCENT_PURPLE": "#4527a0",
    "ACCENT_CYAN": "#3949ab",  # 浅靛
    "TEXT_PRIMARY": "#1a1c2e",
    "TEXT_BRIGHT": "#0d0f1f",
    "TEXT_SECONDARY": "#565c78",
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#d6dbf0",
}

FLUENT_DARK = {
    # 深色按用户指定的 Cyberpunk Dark Mode 配色（Tailwind slate + sky/purple/pink）。
    # 底色 #0F172A / 浮起面 #1E293B 是 slate-900/800，强调色取 sky-400 等高明度色，
    # 这样在深底上既亮眼又不刺眼。
    "BG_DARK": "#0f172a",  # slate-900
    "BG_SURFACE": "#1e293b",  # slate-800
    "BG_SURFACE_LIGHT": "#24334b",  # 选中/悬浮
    "BG_HOVER": "#2e4460",
    "PRIMARY": "#38bdf8",  # sky-400：主色
    "ACCENT_RED": "#f472b6",  # pink-400
    "ACCENT_GREEN": "#34d399",  # emerald-400
    "ACCENT_YELLOW": "#fbbf24",  # amber-400
    "ACCENT_ORANGE": "#fb923c",  # orange-400
    "ACCENT_PURPLE": "#c084fc",  # purple-400
    "ACCENT_CYAN": "#22d3ee",  # cyan-400
    "TEXT_PRIMARY": "#e2e8f0",  # slate-200
    "TEXT_BRIGHT": "#f8fafc",  # slate-50
    "TEXT_SECONDARY": "#94a3b8",  # slate-400
    "TEXT_ON_PRIMARY": "#0f172a",  # 亮青底上用深字（对比度远高于白字）
    "BORDER": "#334155",  # slate-700
}


class ThemeSpec(TypedDict):
    id: str
    name_zh: str
    mode: str  # "dark" | "light"
    material: str  # "acrylic" | "mica" | "solid"
    radius: int
    colors: dict[str, str]


THEME_REGISTRY: dict[str, ThemeSpec] = {
    "fluent-dark": {
        "id": "fluent-dark",
        "name_zh": "Fluent 深色",
        "mode": "dark",
        "material": "mica",
        "radius": 4,
        "colors": FLUENT_DARK,
    },
    "fluent-light": {
        "id": "fluent-light",
        "name_zh": "Fluent 浅色",
        "mode": "light",
        "material": "mica",
        "radius": 4,
        "colors": FLUENT_LIGHT,
    },
}

# 旧主题 id → 现存主题。历史上的 8 套配色已删除，用户 settings 里残留的旧 id
# 在此兜底，避免升级后主题失效。
_LEGACY_MAP = {
    "dark": "fluent-dark",
    "light": "fluent-light",
    "one-dark": "fluent-dark",
    "one-light": "fluent-light",
    "eve-deep": "fluent-dark",
    "eve-polar": "fluent-light",
    "fluent-blue": "fluent-dark",
    "fluent-bright": "fluent-light",
    "cyber-neon": "fluent-dark",
    "nord": "fluent-dark",
    "tokyo-night": "fluent-dark",
    "warm-sun": "fluent-light",
}

# 兼容层：旧调用方 / 测试仍可引用 THEMES["dark"/"light"]
THEMES = {
    "dark": FLUENT_DARK,
    "light": FLUENT_LIGHT,
}

# ── 模块级变量（运行时被 apply_theme 更新） ──
# 默认使用 Fluent 深色
BG_DARK = FLUENT_DARK["BG_DARK"]
BG_SURFACE = FLUENT_DARK["BG_SURFACE"]
BG_SURFACE_LIGHT = FLUENT_DARK["BG_SURFACE_LIGHT"]
BG_HOVER = FLUENT_DARK["BG_HOVER"]
PRIMARY = FLUENT_DARK["PRIMARY"]
ACCENT_RED = FLUENT_DARK["ACCENT_RED"]
ACCENT_GREEN = FLUENT_DARK["ACCENT_GREEN"]
ACCENT_YELLOW = FLUENT_DARK["ACCENT_YELLOW"]
ACCENT_ORANGE = FLUENT_DARK["ACCENT_ORANGE"]
ACCENT_PURPLE = FLUENT_DARK["ACCENT_PURPLE"]
ACCENT_CYAN = FLUENT_DARK["ACCENT_CYAN"]
TEXT_PRIMARY = FLUENT_DARK["TEXT_PRIMARY"]
TEXT_BRIGHT = FLUENT_DARK["TEXT_BRIGHT"]
TEXT_SECONDARY = FLUENT_DARK["TEXT_SECONDARY"]
TEXT_ON_PRIMARY = FLUENT_DARK["TEXT_ON_PRIMARY"]
BORDER = FLUENT_DARK["BORDER"]

# 材质与圆角（随主题切换）
MATERIAL = "solid"
RADIUS = 6
RADIUS_SMALL = max(2, RADIUS - 2)

# ── Fluent 设计 token ──
# 唯一来源：QML 侧经 ui_qml.bridge.theme_bridge 读取，禁止在 QML 里写字面量。
#
# ELEVATION = (阴影模糊, 垂直偏移, 不透明度)，层数 1=静止 4=悬停。
#
# ⚠️ **模糊值是 0..1 的归一化值，不是像素半径**。
# QML 的 MultiEffect.shadowBlur 按元素尺寸归一化（Qt 文档：0=无模糊，1=最大模糊）；
# 把规范的像素值直接传进去会得到「完全没有阴影」——实测 blur=0.8 正常、
# blur=14.4 无阴影。
#
# ⚠️ **正因为按尺寸归一化，大小元素必须用两套值**：同一个 0.35 在 240x140 的卡片上
# 散开约 13px（合适），在 130x32 的按钮上却散开约 8px——相对按钮自身高度太大，
# 看上去就是又大又脏的一块（用户反馈「这个阴影好丑」）。故拆成控件级与卡片级。
# 数值都是对着实际尺寸实测标定的：
#   控件 130x32：0.16 ≈ 3.3px（对齐规范 small 的 3.6px）
#   卡片 240x140：0.35 ≈ 5px / 0.55 ≈ 7px / 0.80 ≈ 13px（对齐规范 3.6/7.2/14.4）
ELEVATION_CARD: dict[int, tuple[float, float, float]] = {
    1: (0.35, 1.6, 0.13),  # 规范 3.6px
    2: (0.55, 3.2, 0.13),  # 规范 7.2px
    3: (0.80, 6.4, 0.13),  # 规范 14.4px
    4: (0.88, 6.4, 0.18),  # 悬停：阴影扩张（规范 hover 档）
}

ELEVATION_CONTROL: dict[int, tuple[float, float, float]] = {
    1: (0.16, 1.0, 0.13),  # 静止（规范 small）
    4: (0.24, 1.6, 0.18),  # 悬停：略微扩张
}

# 兼容旧名（卡片级）
ELEVATION = ELEVATION_CARD

# 暗色主题下黑色阴影在深底上几乎不可见，需按此系数抬高不透明度。
# 控件级系数更小：小面积上叠一块 0.5 alpha 的深影同样会显得脏。
DARK_SHADOW_BOOST = 4.0
DARK_SHADOW_BOOST_CONTROL = 2.2
DARK_SHADOW_ALPHA_MAX = 0.85


def _shift_lightness(color_hex: str, amount: float) -> str:
    """把颜色朝白/黑方向线性移动 `amount`（0..1），返回 hex。"""
    if not color_hex.startswith("#") or len(color_hex) != 7:
        return color_hex
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)
    if amount >= 0:
        mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    else:
        mix = lambda c: round(c * (1 + amount))  # noqa: E731
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def token(name: str) -> str:
    """按 token 名取当前主题色值；名字不存在返回空串。

    给需要「动态 token 名」的场景用（如表格模型按状态返回 `ACCENT_RED` /
    `TEXT_SECONDARY`）；固定取色的调用方直接引模块级常量即可。

    QML 侧原先有 6 份逐字相同的本地副本（2 个桥 + 5 个模型），汇总到这一处。
    """
    return str(globals().get(name) or "")


def bg_elevated() -> str:
    """浮起表面（卡片等）的颜色。

    Fluent 的层次是「底色最暗、越往上越亮」，而本项目原有的
    `BG_SURFACE < BG_DARK`（卡片比页面**暗**）——直接用会让卡片看起来是凹坑
    而不是浮起，这正是「界面不立体」的一大来源。
    这里按材质模式给出真正的浮起表面：暗色在 BG_DARK 上提亮，浅色用白。
    """
    return _shift_lightness(BG_DARK, 0.08) if is_dark_mode() else "#ffffff"


def is_dark_mode() -> bool:
    """当前主题是否深色。

    需要按主题选**不同资源**的调用方用它（如外壳侧栏 logo 的深浅两张图）；
    只按主题取色的一律直接用 token，不要读这个。
    """
    spec = THEME_REGISTRY.get(_current_theme)
    return spec is None or spec["mode"] == "dark"


# 动效时长（毫秒）。Fluent 是流畅利落的，规范硬上限 200ms。
DURATION_FAST = 150  # 按钮与控件
DURATION_CARD = 200  # 卡片

# 间距刻度（px），对齐规范里的 gap-2/3/4 与 p-4/p-5
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16

# 焦点环（规范 focus:ring-2 focus:ring-offset-2）
FOCUS_RING_WIDTH = 2
FOCUS_RING_OFFSET = 2

# ── 字体 token（由「系统设置 → 全局字号」驱动） ──
# 所有 QSS / 内联样式表的字号一律写 {fs(NN)}px，禁止写死像素值。
FONT_FAMILY = "Microsoft YaHei UI"
FONT_FAMILY_QSS = f'"{FONT_FAMILY}", "Segoe UI", sans-serif'
BASE_FONT_PX = 13  # QSS 基准字号（与 settings.json 的 font_size 默认值一致）
FONT_SCALE = 1.0  # 由 set_font_scale() 更新；1.0 = 出厂外观


def fs(px: int) -> int:
    """基准像素字号 → 当前缩放下的像素字号（scale=1.0 时恒等）。"""
    return max(8, round(px * FONT_SCALE))


def font_point_size() -> int:
    """QApplication 默认字体的点值。13px ≈ 9.75pt，取整后与历史值 10pt 一致。"""
    return max(6, round(BASE_FONT_PX * 0.75 * FONT_SCALE))


_current_theme = "fluent-dark"


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

    读 token 一律用**属性访问**（`theme.BG_DARK`，或本模块内的裸 `BG_DARK`）——
    那是调用时取值，切主题后立即是新值。`from ... import BG_DARK` 是导入期快照，
    只在**导入前后主题不再变**的场景才安全。
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

    # 同步 QApplication 默认字体（字号缩放后需要重设）
    _apply_app_font()

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
            log.exception("主题监听器回调失败")
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
    """在当前主题 mode 基础上在 fluent-dark / fluent-light 之间确定性互切，返回新主题 id"""
    spec = current_theme_spec()
    target = "fluent-light" if (spec and spec["mode"] == "dark") else "fluent-dark"
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
    """从 settings.json 读取主题偏好，默认 fluent-dark；legacy "dark"/"light" 自动迁移落盘"""
    try:
        from services.user_settings import load_settings

        raw = cast(str, load_settings().get("theme", "fluent-dark"))
    except Exception:
        return "fluent-dark"
    canonical = _resolve_theme_id(raw)
    if canonical != raw:
        save_theme_preference(canonical)
    return canonical


def _apply_app_font() -> None:
    """同步 QApplication 默认字体。

    无 QApplication 时静默跳过：测试会直接调用 apply_theme（见 tests/test_theme_registry.py），
    此时 instance() 为 None，不判空会抛 AttributeError。
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.setFont(QFont(FONT_FAMILY, font_point_size()))


def set_font_scale(scale: float) -> None:
    """设置全局字号缩放并重放主题，触发监听器重新套用内联样式表。"""
    global FONT_SCALE
    FONT_SCALE = max(0.5, min(2.0, float(scale)))
    apply_theme(_current_theme)


def load_font_scale() -> float:
    """从 settings.json 读取字号（像素值）并换算为缩放因子。"""
    try:
        from services.user_settings import load_settings

        px = float(load_settings().get("font_size", BASE_FONT_PX))
    except Exception:
        return 1.0
    return max(0.5, min(2.0, px / BASE_FONT_PX))


def save_font_scale(scale: float) -> None:
    """把缩放因子换算回像素值持久化（走 services.user_settings 统一入口）。"""
    try:
        from services.user_settings import save_settings

        save_settings({"font_size": round(BASE_FONT_PX * scale)})
    except Exception:
        pass


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


#: 无保存值（首次启动 / 文件损坏 / 位置已失效）时的默认窗口尺寸。
#: 会被夹进主屏可用区域，所以小屏上不会溢出。
_DEFAULT_WINDOW_SIZE = (1400, 800)


def _screen_for(rect) -> object | None:
    """返回可承载 `rect` 的屏幕；没有就返回 None。

    **判据是「中心点落在某块屏幕的可用区域内」，不是 `x >= 0`**：左侧副屏
    合法占用负坐标，用 `x >= 0` 会把副屏上的窗口判成越界并强行搬到主屏。
    `screenAt()` 也优于 `intersects()` —— 后者对「只露出几十像素的一条缝」判为有效
    （实测坏值 `(-1310, -6, 1400, 900)` 在主屏 2560x1400 上的相交区只剩 90px 宽，
    仍然相交），于是窗口照旧几乎全在屏幕外，自愈路径永远不触发。
    """
    from PySide6.QtGui import QGuiApplication

    if rect is None or rect.isEmpty():
        return None
    return QGuiApplication.screenAt(rect.center())


def _center_on(screen, width: int, height: int) -> tuple[int, int, int, int]:
    """把 `width`x`height` 居中到 `screen` 的可用区域，尺寸夹进该区域。"""
    avail = screen.availableGeometry()
    width = max(1, min(width, avail.width()))
    height = max(1, min(height, avail.height()))
    x = avail.x() + (avail.width() - width) // 2
    y = avail.y() + (avail.height() - height) // 2
    return x, y, width, height


def restore_window_geometry(window):
    """恢复上次的窗口矩形；结果保证落在某块屏幕的可用区域内。

    保存值可用（中心点在某块屏幕上）时**行为与历史完全一致**：原样 `setGeometry`。
    无文件 / 解析失败 / 位置已失效（例如旧版本写下的 `(-1310, -6)`）→ 主屏居中，
    尺寸夹进主屏可用区域 —— 这是「主窗口打开到屏幕外」缺陷的自愈路径。

    惰性 import Qt（与 `apply_theme` 内的 `from PySide6.QtGui import QFont` 同一惯例），
    保持模块顶层无 Qt：`tests/test_theme_registry.py` 会在没有 QApplication 的情况下调本模块。
    """
    if WINDOW_GEOMETRY_FILE is None:
        return
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        # 没有屏幕信息（无 QApplication）—— 无从判定，保持历史兜底行为
        window.resize(*_DEFAULT_WINDOW_SIZE)
        return

    data = None
    try:
        if os.path.exists(WINDOW_GEOMETRY_FILE):
            with open(WINDOW_GEOMETRY_FILE) as f:
                data = json.load(f)
    # 文件损坏 / 缺字段 / 类型不对 → 落到下面的居中分支
    except Exception:
        data = None

    rect = None
    if data is not None:
        try:
            rect = QRect(int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))
        except Exception:
            rect = None

    if rect is not None:
        saved_screen = _screen_for(rect)
        if saved_screen is not None:
            # 保存值依然落在一块屏幕上 —— 原样套用，行为与历史一致
            window.setGeometry(rect)
            return

    window.setGeometry(*_center_on(screen, *_DEFAULT_WINDOW_SIZE))

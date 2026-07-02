"""
One Dark Pro / One Light 主题系统 — 支持运行时切换
"""

import json
import os

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
    "TEXT_SECONDARY": "#5c6370",
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
    "TEXT_SECONDARY": "#8a8a8a",
    "TEXT_ON_PRIMARY": "#ffffff",
    "BORDER": "#d4d0cb",
}

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

_current_theme = "dark"
_theme_listeners = []

# ── 向后兼容别名 ──
GREEN = ACCENT_GREEN
RED = ACCENT_RED
YELLOW = ACCENT_YELLOW

WINDOW_GEOMETRY_FILE: str | None = None


def apply_theme(theme_name: str) -> None:
    """
    切换主题并更新模块级变量。
    所有 `from ui_pyside6.theme import XXX` 的地方会自动反映新值。
    """
    global _current_theme, BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, BG_HOVER
    global PRIMARY, ACCENT_RED, ACCENT_GREEN, ACCENT_YELLOW
    global ACCENT_ORANGE, ACCENT_PURPLE, ACCENT_CYAN
    global TEXT_PRIMARY, TEXT_BRIGHT, TEXT_SECONDARY, TEXT_ON_PRIMARY, BORDER
    global GREEN, RED, YELLOW

    colors = THEMES.get(theme_name)
    if not colors:
        return

    _current_theme = theme_name
    for key, value in colors.items():
        globals()[key] = value

    # 更新别名
    globals()["GREEN"] = globals()["ACCENT_GREEN"]
    globals()["RED"] = globals()["ACCENT_RED"]
    globals()["YELLOW"] = globals()["ACCENT_YELLOW"]

    # 持久化主题偏好
    save_theme_preference(theme_name)

    # 通知监听器
    for listener in _theme_listeners:
        try:
            listener()
        except Exception:
            pass


def current_theme() -> str:
    return _current_theme


def add_theme_listener(callback):
    """注册主题切换时的回调"""
    _theme_listeners.append(callback)


def remove_theme_listener(callback):
    if callback in _theme_listeners:
        _theme_listeners.remove(callback)


def save_theme_preference(theme_name: str):
    """保存主题偏好到 settings.json"""
    try:
        from core.paths import search_history_file

        p = search_history_file().replace("search_history", "settings")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        data["theme"] = theme_name
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_theme_preference() -> str:
    """从 settings.json 读取主题偏好，默认 dark"""
    try:
        from core.paths import search_history_file

        p = search_history_file().replace("search_history", "settings")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("theme", "dark")
    except Exception:
        pass
    return "dark"


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
            with open(WINDOW_GEOMETRY_FILE, "r") as f:
                data = json.load(f)
            window.setGeometry(data["x"], data["y"], data["w"], data["h"])
        else:
            window.resize(1400, 800)
    except Exception:
        window.resize(1400, 800)


def _global_styles() -> str:
    return f"""
    QMainWindow {{
        background-color: {BG_DARK};
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
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
    }}
    QMenu {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 32px 6px 16px;
        border-radius: 4px;
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
        border-radius: 4px;
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
        border-radius: 6px;
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
        border-radius: 6px;
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
        border-radius: 4px;
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
        border-radius: 6px;
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
        border-radius: 4px;
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
        border-radius: 6px;
        gridline-color: {BORDER};
        selection-background-color: {PRIMARY};
        selection-color: {TEXT_BRIGHT};
        outline: none;
    }}
    QTableView::item {{
        padding: 4px 8px;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:selected {{
        background-color: {PRIMARY};
        color: {TEXT_BRIGHT};
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
        border-radius: 2px;
        height: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {PRIMARY};
        border-radius: 2px;
    }}
    QCheckBox {{
        spacing: 8px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER};
        border-radius: 3px;
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
        border-radius: 4px;
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
        border-radius: 4px;
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
        border-radius: 6px;
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
        border-radius: 6px;
        color: {TEXT_PRIMARY};
    }}
    QToolTip {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """


def _mainwindow_specific_styles() -> str:
    return f"""
    #central_widget {{
        background-color: {BG_DARK};
    }}
    #nav_panel {{
        background-color: {BG_SURFACE};
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
        border-radius: 4px;
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
        border-radius: 4px;
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
        border-radius: 6px;
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
        border-radius: 6px;
        font-size: 13px;
        padding: 8px 12px;
    }}
    #sys_menu {{
        background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
    }}
    #sys_menu::item {{
        padding: 6px 24px;
        border-radius: 4px;
    }}
    #sys_menu::item:selected {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_BRIGHT};
    }}
    """


def get_stylesheet() -> str:
    """根据当前主题生成 QSS 样式表 — 按组件类别组装"""
    return "".join([
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
        _page_specific_styles(),
    ])

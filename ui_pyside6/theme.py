"""
QSS 暗色主题 — 与原有 Flet 配色方案一致
"""
import os
import json
from PySide6.QtCore import QDir

# ── 基础色板 ──
BG_DARK = "#1a1a2e"
BG_SURFACE = "#16213e"
BG_SURFACE_LIGHT = "#0f3460"
PRIMARY = "#e94560"
TEXT_PRIMARY = "#e0e0e0"
TEXT_SECONDARY = "#888888"
BORDER = "#2a2a4a"
GREEN = "#00ff88"
RED = "#ff6b6b"
YELLOW = "#ffcc00"

WINDOW_GEOMETRY_FILE: str | None = None


def set_geometry_file(path: str):
    """Set the path for saving/loading window geometry."""
    global WINDOW_GEOMETRY_FILE
    WINDOW_GEOMETRY_FILE = path


def save_window_geometry(window):
    """Save window position and size to JSON file."""
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
    """Restore window position and size from JSON file."""
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


def get_stylesheet() -> str:
    """Return the application-wide QSS stylesheet."""
    return f"""
    /* ── 全局 ── */
    QMainWindow {{
        background-color: {BG_DARK};
    }}

    QWidget {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
    }}

    /* ── 菜单栏 ── */
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
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER};
        margin: 4px 8px;
    }}

    /* ── 状态栏 ── */
    QStatusBar {{
        background-color: {BG_SURFACE};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {BORDER};
        font-size: 11px;
        padding: 2px 8px;
    }}

    /* ── 工具栏 ── */
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

    /* ── 树控件 (导航) ── */
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
        color: {TEXT_PRIMARY};
    }}
    QTreeWidget::item:hover {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
    }}
    QTreeWidget::branch {{
        background-color: {BG_SURFACE};
    }}

    /* ── 选项卡 ── */
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

    /* ── 输入框 ── */
    QLineEdit {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        selection-background-color: {PRIMARY};
    }}
    QLineEdit:focus {{
        border-color: {PRIMARY};
    }}

    /* ── 下拉框 ── */
    QComboBox {{
        background-color: {BG_SURFACE_LIGHT};
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
        selection-background-color: {PRIMARY};
        outline: none;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}

    /* ── 按钮 ── */
    QPushButton {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY};
    }}
    QPushButton:disabled {{
        background-color: #333;
        color: #666;
    }}

    QToolButton {{
        background-color: transparent;
        color: {TEXT_SECONDARY};
        border: none;
        border-radius: 4px;
        padding: 4px;
    }}
    QToolButton:hover {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
    }}

    /* ── 表格 ── */
    QTableView {{
        background-color: {BG_DARK};
        alternate-background-color: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: 6px;
        gridline-color: {BORDER};
        selection-background-color: {PRIMARY};
        selection-color: white;
        outline: none;
    }}
    QTableView::item {{
        padding: 4px 8px;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:selected {{
        background-color: {PRIMARY};
    }}
    QHeaderView::section {{
        background-color: {BG_SURFACE_LIGHT};
        color: {TEXT_PRIMARY};
        padding: 6px 8px;
        border: none;
        border-right: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        font-weight: bold;
        font-size: 12px;
    }}
    QHeaderView::section:hover {{
        background-color: #1a3a5e;
    }}

    /* ── 分割器 ── */
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

    /* ── 进度条 ── */
    QProgressBar {{
        background-color: {BG_SURFACE_LIGHT};
        border: none;
        border-radius: 2px;
        height: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {PRIMARY};
        border-radius: 2px;
    }}

    /* ── 复选框 ── */
    QCheckBox {{
        spacing: 8px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER};
        border-radius: 3px;
        background-color: {BG_SURFACE_LIGHT};
    }}
    QCheckBox::indicator:checked {{
        background-color: {PRIMARY};
        border-color: {PRIMARY};
    }}

    /* ── 滚动条 ── */
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

    /* ── 列表控件 ── */
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
        background-color: {PRIMARY};
    }}

    /* ── 文本浏览器 ── */
    QTextBrowser {{
        background-color: {BG_DARK};
        border: 1px solid {BORDER};
        border-radius: 6px;
        color: {TEXT_PRIMARY};
    }}

    /* ── 提示 ── */
    QToolTip {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """

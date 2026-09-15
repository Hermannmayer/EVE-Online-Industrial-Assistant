"""对比对话框的 QSS 构建（Widgets 专有）。

`CompareTableModel` 与 `_format_isk` / `_fmt_tag` 已搬到 `ui_qml/models/compare_models.py`，
这里只剩样式表构造函数 —— QML 侧不套 QSS，等 Widgets 对话框删掉后本文件一并消失。
"""

import ui_pyside6.theme as theme

# ═══════════════════════════════════════════


def build_dialog_stylesheet():
    """构建对话框主样式表"""
    return f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"


def build_search_input_stylesheet():
    """构建搜索框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 8px;"
    )


def build_primary_btn_stylesheet():
    """构建主按钮样式表"""
    return (
        f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
        f"border:none;border-radius:4px;padding:4px 12px;font-size:{theme.fs(11)}px;}}"
        f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
    )


def build_item_list_stylesheet():
    """构建物品列表样式表"""
    return (
        f"QListWidget{{background:{theme.BG_SURFACE};border:1px solid {theme.BORDER};"
        f"border-radius:4px;font-size:{theme.fs(11)}px;}}"
        f"QListWidget::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
        f"QListWidget::item:hover{{background:{theme.BG_HOVER};}}"
    )


def build_combo_stylesheet():
    """构建下拉框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 6px;font-size:{theme.fs(11)}px;"
    )


def build_spin_stylesheet():
    """构建数字输入框样式表"""
    return (
        f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px;"
    )


def build_compare_btn_stylesheet():
    """构建对比按钮样式表"""
    return (
        f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
        f"border:none;border-radius:4px;padding:5px 16px;font-size:{theme.fs(12)}px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
        f"QPushButton:disabled{{background:{theme.TEXT_SECONDARY};color:{theme.BG_SURFACE};}}"
    )


def build_export_btn_stylesheet():
    """构建导出按钮样式表"""
    return (
        f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 12px;font-size:{theme.fs(11)}px;}}"
        f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.PRIMARY};}}"
    )


def build_status_stylesheet():
    """构建状态栏样式表"""
    return f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;"


def build_progress_stylesheet():
    """构建进度条样式表"""
    return (
        f"QProgressBar{{background:{theme.BG_SURFACE};border:none;border-radius:1px;height:3px;}}"
        f"QProgressBar::chunk{{background:{theme.PRIMARY};border-radius:1px;}}"
    )


def build_label_stylesheet():
    """构建标签样式表"""
    return f"color:{theme.TEXT_SECONDARY};font-size:{theme.fs(11)}px;"


def build_clear_btn_stylesheet():
    """构建清空按钮样式表"""
    return (
        f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 8px;font-size:{theme.fs(10)}px;}}"
        f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.ACCENT_RED};}}"
    )


def build_table_stylesheet():
    """构建表格样式表"""
    return (
        f"QTableView{{background:{theme.BG_DARK};alternate-background-color:{theme.BG_SURFACE};"
        f"border:1px solid {theme.BORDER};border-radius:4px;gridline-color:{theme.BORDER};"
        f"selection-background-color:{theme.PRIMARY};selection-color:{theme.TEXT_BRIGHT};outline:none;}}"
        f"QTableView::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
        f"QTableView::item:selected{{background:{theme.PRIMARY};color:{theme.TEXT_BRIGHT};}}"
        f"QHeaderView::section{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
        f"padding:4px 6px;border:none;border-right:1px solid {theme.BORDER};"
        f"border-bottom:1px solid {theme.BORDER};font-weight:bold;font-size:{theme.fs(11)}px;}}"
        f"QHeaderView::section:hover{{background:{theme.BG_HOVER};}}"
    )

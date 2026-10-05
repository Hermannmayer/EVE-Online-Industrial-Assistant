"""两套 UI 共享的展示常量。

这里放「只影响界面怎么分组/怎么显示、不影响业务计算」的常量。**配色不在此列**
—— 颜色一律从 `ui_qml.theme.registry` 取（铁律）。
"""

from services.terminology import term

__all__ = ["CATEGORIES", "MFG_CATEGORIES", "NAV_TREE"]

#: 左侧导航条目：`(key, 标题, 图标语义键, 图标配色)`；`key` 就是页面键，顺序即显示顺序。
#: 原先在 `ui_pyside6/main_window_nav.py`，QML 外壳也要这份，故上移成单一来源。
#: （曾经首项是 `("__section__", "核心功能", "lightning")` 分组标题，已按界面改版去掉。）
#:
#: 配色写的是**主题 token 名**而不是色值：本模块刻意不依赖 Qt / 主题（QML 与 Widgets
#: 两侧都要能取），由外壳桥把它解析成当前主题的实际颜色 —— 并且过一遍
#: `domain.theme_contrast.ensure_contrast`。浅色主题下琥珀/橙的对比度不足 3:1
#: （WCAG 1.4.11 对图形的要求），桥那边会自动压暗到达标，所以这里可以放心写 token 名。
NAV_TREE = [
    ("query", "物品查询", "search", "PRIMARY"),
    ("estimate", "估价", "coins", "ACCENT_YELLOW"),
    ("industry", "工业制造", "factory", "ACCENT_ORANGE"),
    ("trade", "市场贸易", "chart", "ACCENT_GREEN"),
    ("watchlist", "价格监控", "bell", "ACCENT_RED"),
    ("contract", "合同市场", "contract", "ACCENT_PURPLE"),
    ("storage", "仓库管理", "package", "ACCENT_CYAN"),
]

#: 「全部物品查询」的分类下拉项（含不可制造项）
CATEGORIES = [
    term.market_category("all"),
    term.market_category("unmanufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
    term.market_category("planetary"),
]

#: 同上，但只列可制造项（「可制造物品」对话框与对应桥用）
MFG_CATEGORIES = [
    term.market_category("all_manufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
]

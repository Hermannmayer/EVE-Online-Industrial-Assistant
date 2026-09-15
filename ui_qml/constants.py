"""两套 UI 共享的展示常量。

这里放「只影响界面怎么分组/怎么显示、不影响业务计算」的常量。**配色不在此列**
—— 颜色一律从 `ui_qml.theme.registry` 取（铁律）。
"""

from services.terminology import term

__all__ = ["CATEGORIES", "MFG_CATEGORIES", "NAV_TREE"]

#: 左侧导航条目：`(key, 标题, 图标)`；`key == "__section__"` 的是分组标题（不可点）。
#: 原先在 `ui_pyside6/main_window_nav.py`，QML 外壳也要这份，故上移成单一来源。
NAV_TREE = [
    ("__section__", "核心功能", "lightning"),
    ("estimate", "估价", "coins"),
    ("query", "物品查询", "search"),
    ("industry", "工业制造", "factory"),
    ("trade", "市场贸易", "chart"),
    ("watchlist", "价格监控", "bell"),
    ("contract", "合同市场", "contract"),
    ("storage", "仓库管理", "package"),
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
